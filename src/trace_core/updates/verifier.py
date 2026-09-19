from pathlib import Path

from trace_core.core.fs import sha256_file
from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.signing import verify_artifact_signature, verify_manifest_signature


def verify_artifact(path: Path, artifact) -> None:
    if path.name != artifact.filename:
        raise UpdateVerificationError(f"filename mismatch: {path.name} != {artifact.filename}")
    if "/" in artifact.filename or "\\" in artifact.filename or ".." in artifact.filename:
        raise UpdateVerificationError("unsafe artifact filename")
    size = path.stat().st_size
    if size != artifact.size:
        raise UpdateVerificationError(f"size mismatch: {size} != {artifact.size}")
    digest = sha256_file(path)
    if digest != artifact.sha256:
        raise UpdateVerificationError(f"sha256 mismatch: {digest} != {artifact.sha256}")
    verify_artifact_signature(path.read_bytes(), artifact.signature, artifact.signing_key_id)


def verify_manifest(manifest: ReleaseManifest, artifact_path: Path, platform_key: str | None = None) -> None:
    from trace_core.updates.policy import select_artifact

    verify_manifest_signature(manifest)
    if platform_key is not None:
        artifact = manifest.artifacts.get(platform_key)
        if artifact is None:
            raise UpdateVerificationError(f"manifest has no artifact {platform_key!r}")
    else:
        artifact = select_artifact(manifest)
    verify_artifact(artifact_path, artifact)
