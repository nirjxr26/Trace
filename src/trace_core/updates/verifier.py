from pathlib import Path

from trace_core.core.fs import sha256_file
from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.signing import verify_artifact_signature_streaming, verify_manifest_signature


def is_safe_filename(name: str) -> bool:
    """Single source for artifact filename safety. Shared by verifier/updater/release tooling."""
    return bool(name) and "/" not in name and "\\" not in name and ".." not in name


def assert_safe_filename(name: str) -> str:
    if not is_safe_filename(name):
        raise UpdateVerificationError("unsafe artifact filename")
    return name


def verify_artifact(path: Path, artifact) -> None:
    assert_safe_filename(artifact.filename)
    if path.name != artifact.filename:
        raise UpdateVerificationError(f"filename mismatch: {path.name} != {artifact.filename}")
    size = path.stat().st_size
    if size != artifact.size:
        raise UpdateVerificationError(f"size mismatch: {size} != {artifact.size}")
    digest = sha256_file(path)
    if digest != artifact.sha256:
        raise UpdateVerificationError(f"sha256 mismatch: {digest} != {artifact.sha256}")
    verify_artifact_signature_streaming(path, artifact.signature, artifact.signing_key_id)


def resolve_artifact(manifest: ReleaseManifest, artifact_path: Path, platform_key: str | None = None):  # type: ignore[no-untyped-def]
    from trace_core.updates.policy import select_artifact

    if platform_key is not None:
        artifact = manifest.artifacts.get(platform_key)
        if artifact is None:
            raise UpdateVerificationError(f"manifest has no artifact {platform_key!r}")
        return artifact
    # Explicit file wins over auto-select: a multi-artifact manifest (e.g. wheel
    # + sdist, both untagged) is ambiguous for select_artifact by design, but the
    # operator already named the file. Wrong file still fails filename/size/hash.
    matches = [a for a in manifest.artifacts.values() if a.filename == artifact_path.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise UpdateVerificationError(f"duplicate filename {artifact_path.name!r} in manifest")
    return select_artifact(manifest)


def verify_manifest(manifest: ReleaseManifest, artifact_path: Path, platform_key: str | None = None) -> None:
    verify_manifest_signature(manifest)
    verify_artifact(artifact_path, resolve_artifact(manifest, artifact_path, platform_key))
