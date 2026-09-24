"""Ledger authenticity envelope. HMAC backend always; Ed25519 when a keystore key is active.

Key custody rule: private keys live in the filesystem keystore (0600 dir) or an
operator-provided path — never in the DB, source, exports, or anchors.
"""

import hashlib
import hmac
import re

from trace_core.core.errors import ApplicationError

HMAC_KEY_ID = "hmac-v1"
ED25519_PREFIX = "ed25519:"
_KEY_SUFFIX_RE = re.compile(r"^[0-9a-f]{16}$")
_DEV_KEY_SENTINEL = "trace-local-dev-key-change-in-production"
_KEYSTORE_UNAVAILABLE_MESSAGE = (
    "Ledger signing key {key_id} unavailable in keystore; case writes are paused until it is restored."
)
_warned_default_key = False
_warned_pointer = False


def _secret() -> bytes:
    from trace_core.core.settings import settings

    return settings.secret_key.get_secret_value().encode("utf-8")


def _warn_default_key() -> None:
    global _warned_default_key
    if _warned_default_key:
        return
    _warned_default_key = True
    import structlog

    structlog.get_logger().warning(
        "Signing ledger with the default development key; set TRACE_SECRET_KEY in production."
    )


def expected_signature(key_id: str | None, data: bytes) -> str:
    """Recomputed signature, or '' when the key is unknown (retired/foreign)."""
    if key_id != HMAC_KEY_ID:
        return ""
    return hmac.new(_secret(), data, hashlib.sha256).hexdigest()


def verify_bytes(key_id: str | None, data: bytes, signature: str) -> bool:
    """Constant-time envelope check. Unknown keys fail closed."""
    if key_id and key_id.startswith(ED25519_PREFIX):
        return _verify_ed25519(key_id, data, signature)
    expected = expected_signature(key_id, data)
    return bool(expected) and hmac.compare_digest(expected, signature)


def _keystore_dir():  # type: ignore[no-untyped-def]
    from pathlib import Path

    from trace_core.core.fs import ensure_dir
    from trace_core.core.settings import settings

    return ensure_dir(Path(settings.storage_root) / "keys")


def _active_pointer():  # type: ignore[no-untyped-def]
    return _keystore_dir() / "active"


def active_key_id() -> str:
    """Selected signing key, defaulting to the HMAC envelope. Never raises.

    The pointer file holds `<key-id> [# comment]` (see init_key). Anything else
    is refused loudly (one warning) and falls back to HMAC so a corrupt pointer
    degrades availability visibly instead of signing under a wrong identity.
    """
    try:
        raw = _active_pointer().read_text(encoding="utf-8").strip()
    except OSError:
        return HMAC_KEY_ID
    if not raw:
        return HMAC_KEY_ID
    first = raw.split()[0]
    if first == HMAC_KEY_ID or (
        first.startswith(ED25519_PREFIX) and _KEY_SUFFIX_RE.match(first[len(ED25519_PREFIX) :])
    ):
        return first
    _warn_pointer(raw)
    return HMAC_KEY_ID


def _warn_pointer(raw: str) -> None:
    global _warned_pointer
    if _warned_pointer:
        return
    _warned_pointer = True
    import structlog

    structlog.get_logger().warning(
        "Ignoring malformed signing-key pointer; using HMAC envelope.",
        pointer=raw[:64],
    )


def init_key(label: str = "default") -> str:
    """Generate an Ed25519 signing key, store it 0600, and select it. Returns key_id."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    clean = "".join(c for c in label.strip().lower() if c.isalnum() or c in ("-", "_")) or "default"
    private = Ed25519PrivateKey.generate()
    raw_pub = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = f"{ED25519_PREFIX}{hashlib.sha256(raw_pub).hexdigest()[:16]}"
    priv_path = _keystore_dir() / f"{key_id[len(ED25519_PREFIX) :]}.key"
    pub_path = _keystore_dir() / f"{key_id[len(ED25519_PREFIX) :]}.pub"
    priv_path.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_text(raw_pub.hex(), encoding="utf-8")
    import os

    os.chmod(priv_path, 0o600)
    _active_pointer().write_text(f"{key_id} # {clean}\n", encoding="utf-8")
    return key_id


def rotate_keys(label: str = "default") -> str:
    """Generate a successor key. Retired public keys stay for verification."""
    return init_key(label)


def list_keys() -> list[dict[str, str]]:
    """Public keys in the keystore with active/retired status. No private material."""
    active = active_key_id()
    keys: list[dict[str, str]] = []
    try:
        pubs = sorted(_keystore_dir().glob("*.pub"))
    except OSError:
        return keys
    for pub in pubs:
        key_id = f"{ED25519_PREFIX}{pub.stem}"
        try:
            fingerprint = pub.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        keys.append(
            {
                "key_id": key_id,
                "status": "active" if key_id == active else "retired",
                "public_key": fingerprint,
            }
        )
    if active == HMAC_KEY_ID:
        keys.append({"key_id": HMAC_KEY_ID, "status": "active", "public_key": "-"})
    return keys


def _key_file(suffix: str, ext: str):  # type: ignore[no-untyped-def]
    """Keystore path for a validated key suffix. Grammar first, containment second.

    Suffixes come from DB rows and the active-key pointer file, both
    attacker-writable: a crafted `ed25519:../../x` must never become a path.
    """
    from trace_core.core.fs import check_contained

    if not _KEY_SUFFIX_RE.match(suffix):
        raise ValueError(f"Refusing malformed signing key id suffix: {suffix!r}")
    root = _keystore_dir()
    return check_contained(root / f"{suffix}.{ext}", root, what="signing key")


def _load_private(key_id: str):  # type: ignore[no-untyped-def]
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv_path = _key_file(key_id[len(ED25519_PREFIX) :], "key")
    return Ed25519PrivateKey.from_private_bytes(priv_path.read_bytes())


def _verify_ed25519(key_id: str, data: bytes, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        raw_pub = bytes.fromhex(_key_file(key_id[len(ED25519_PREFIX) :], "pub").read_text(encoding="utf-8").strip())
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(bytes.fromhex(signature), data)
    except (OSError, ValueError, InvalidSignature):
        return False
    return True


def sign_bytes(data: bytes) -> tuple[str, str]:
    """Envelope over canonical payload bytes. Ed25519 when selected, else HMAC-SHA256.

    HMAC rows verify against the *current* TRACE_SECRET_KEY, so that secret must
    never be rotated while HMAC-signed rows exist — rotation reads as tampering.
    Rotate Ed25519 keys (retired pubs keep verifying) instead.
    """
    key_id = active_key_id()
    if key_id.startswith(ED25519_PREFIX):
        try:
            return key_id, _load_private(key_id).sign(data).hex()
        except (OSError, ValueError) as e:
            raise ApplicationError(_KEYSTORE_UNAVAILABLE_MESSAGE.format(key_id=key_id)) from e
    secret = _secret()
    if secret.decode("utf-8", "replace") == _DEV_KEY_SENTINEL:
        _warn_default_key()
    return HMAC_KEY_ID, hmac.new(secret, data, hashlib.sha256).hexdigest()
