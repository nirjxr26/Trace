from pathlib import Path

from trace_core.core.canonical import canonical_json
from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.trust import KEY_PREFIX, revoked_path, trust_key_path


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


def _verify_signature(key_id: str | None, signature: str | None, data: bytes, subject: str) -> None:
    """Guarded Ed25519 check for one signed message. Single source for manifest + artifact."""
    if not key_id:
        raise UpdateVerificationError(f"missing {subject} signing key")
    if not signature:
        raise UpdateVerificationError(f"missing {subject} signature")
    raw_pub = load_release_pubkey(key_id)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(bytes.fromhex(signature), data)
    except (ValueError, InvalidSignature) as e:
        raise UpdateVerificationError(f"invalid {subject} signature") from e


def verify_manifest_signature(manifest: ReleaseManifest) -> None:
    _verify_signature(
        manifest.signing_key_id,
        manifest.manifest_signature,
        canonical_manifest_bytes(manifest),
        "manifest",
    )


def verify_artifact_signature(data: bytes, signature: str | None, key_id: str | None) -> None:
    _verify_signature(key_id, signature, data, "artifact")


def verify_artifact_signature_file(path: Path, signature: str | None, key_id: str | None) -> None:
    """Single source for file-backed artifact verification.

    Ed25519 signs whole messages, so the message must be in memory: the size cap IS the
    memory bound, not a streaming window. The previous cap of 10 GiB meant the happy path
    could be OOM-killed, while a docstring two files over claimed it "never holds full
    bytes in RAM". A release artifact is a wheel plus an sdist, so the cap is set to a
    size no legitimate release approaches.
    """
    from trace_core.updates.manifest import MAX_ARTIFACT_BYTES

    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise UpdateVerificationError("artifact too large to verify")
    verify_artifact_signature(path.read_bytes(), signature, key_id)


def import_release_pubkey(raw_pub_hex: str) -> str:
    parts = raw_pub_hex.strip().split()
    if len(parts) != 1:
        raise UpdateVerificationError("malformed release key import")
    try:
        raw_pub = bytes.fromhex(parts[0])
    except ValueError as e:
        raise UpdateVerificationError("malformed release key import") from e
    if len(raw_pub) != 32:
        raise UpdateVerificationError("invalid ed25519 public key length")
    key_id = key_id_for_pubkey(raw_pub)
    from trace_core.core.fs import atomic_write_lines

    path = trust_key_path(key_id)
    atomic_write_lines(path, [raw_pub.hex()], mode=0o600)
    return key_id


def revoke_release_key(key_id: str) -> None:
    """Revoke takes precedence over the .pub file; both may exist, revoked wins on load."""
    from trace_core.core.fs import atomic_write_lines

    path = revoked_path(key_id)
    atomic_write_lines(path, ["revoked"], mode=0o600)
