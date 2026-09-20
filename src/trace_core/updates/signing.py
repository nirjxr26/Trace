from trace_core.core.canonical import canonical_json
from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.trust import revoked_path, trust_key_path

KEY_PREFIX = "ed25519:"


def key_id_for_pubkey(raw_pub: bytes) -> str:
    import hashlib

    return f"{KEY_PREFIX}{hashlib.sha256(raw_pub).hexdigest()[:16]}"


def canonical_manifest_bytes(manifest: ReleaseManifest) -> bytes:
    data = manifest.model_dump(by_alias=True, mode="json", exclude={"manifest_signature", "signing_key_id"})
    return canonical_json(data)


def _strict_hex_key(text: str, key_id: str) -> bytes:
    parts = text.strip().split()
    if len(parts) != 1:
        raise UpdateVerificationError(f"malformed release key {key_id!r}")
    try:
        return bytes.fromhex(parts[0])
    except ValueError as e:
        raise UpdateVerificationError(f"malformed release key {key_id!r}") from e


def load_release_pubkey(key_id: str) -> bytes:
    if not key_id.startswith(KEY_PREFIX):
        raise UpdateVerificationError(f"unsupported release key algorithm {key_id!r}")
    if revoked_path(key_id).exists():
        raise UpdateVerificationError(f"revoked release key {key_id!r}")
    path = trust_key_path(key_id)
    if not path.exists():
        raise UpdateVerificationError(f"unknown release key {key_id!r}")
    try:
        return _strict_hex_key(path.read_text(encoding="utf-8"), key_id)
    except OSError as e:
        raise UpdateVerificationError(f"unreadable release key {key_id!r}") from e


def verify_manifest_signature(manifest: ReleaseManifest) -> None:
    if not manifest.signing_key_id:
        raise UpdateVerificationError("missing manifest signing key")
    if not manifest.manifest_signature:
        raise UpdateVerificationError("missing manifest signature")
    raw_pub = load_release_pubkey(manifest.signing_key_id)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        sig = bytes.fromhex(manifest.manifest_signature)
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(sig, canonical_manifest_bytes(manifest))
    except (ValueError, InvalidSignature) as e:
        raise UpdateVerificationError("invalid manifest signature") from e


def verify_artifact_signature(data: bytes, signature: str | None, key_id: str | None) -> None:
    if not key_id:
        raise UpdateVerificationError("missing artifact signing key")
    if not signature:
        raise UpdateVerificationError("missing artifact signature")
    raw_pub = load_release_pubkey(key_id)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        sig = bytes.fromhex(signature)
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(sig, data)
    except (ValueError, InvalidSignature) as e:
        raise UpdateVerificationError("invalid artifact signature") from e


def import_release_pubkey(raw_pub_hex: str) -> str:
    raw_pub = bytes.fromhex(raw_pub_hex.strip().split()[0])
    if len(raw_pub) != 32:
        raise UpdateVerificationError("invalid ed25519 public key length")
    key_id = key_id_for_pubkey(raw_pub)
    path = trust_key_path(key_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw_pub.hex(), encoding="utf-8")
    import os

    os.chmod(path, 0o600)
    return key_id


def revoke_release_key(key_id: str) -> None:
    path = revoked_path(key_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("revoked", encoding="utf-8")
