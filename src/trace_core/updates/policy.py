import platform as _platform
import sys

from trace_core.updates.domain import UpdateChannel
from trace_core.updates.manifest import ManifestArtifact, ReleaseManifest


def _parse_version(v: str):  # type: ignore[no-untyped-def]
    from packaging.version import InvalidVersion, Version

    try:
        return Version(v)
    except InvalidVersion as e:
        raise ValueError(f"invalid version {v!r}") from e


def is_update_available(current: str, manifest: ReleaseManifest) -> bool:
    return _parse_version(manifest.version) > _parse_version(current)


def is_installable(
    current: str,
    manifest: ReleaseManifest,
    channel: str = "stable",
    forensic_active: bool = False,
    allow_minimum_bypass: bool = False,
) -> tuple[bool, str | None]:
    if forensic_active:
        return False, "forensic operation active"
    if manifest.channel != channel and channel == UpdateChannel.STABLE:
        if manifest.channel == "beta":
            return False, "beta channel not enabled"
    if manifest.minimum_supported_version:
        if _parse_version(current) < _parse_version(manifest.minimum_supported_version):
            if allow_minimum_bypass:
                return True, None
            return False, f"minimum supported version {manifest.minimum_supported_version} not met"
    return True, None


def minimum_bypass_note(current: str, manifest: ReleaseManifest) -> str | None:
    if manifest.minimum_supported_version and _parse_version(current) < _parse_version(
        manifest.minimum_supported_version
    ):
        return f"minimum-supported-version bypassed ({manifest.minimum_supported_version})"
    return None


def security_label(manifest: ReleaseManifest) -> str | None:
    if not manifest.security_update:
        return None
    if manifest.minimum_supported_version:
        return f"Security update — minimum supported version: {manifest.minimum_supported_version}"
    return "Security update"


def _current_platform() -> tuple[str, str]:
    machine = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(_platform.machine().lower(), "unknown")
    system = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform, "unknown")
    return system, machine


def select_artifact(manifest: ReleaseManifest) -> ManifestArtifact:
    from trace_core.updates.errors import UpdateVerificationError

    if not manifest.artifacts:
        raise UpdateVerificationError("manifest has no artifacts")
    if len(manifest.artifacts) == 1:
        return next(iter(manifest.artifacts.values()))
    system, machine = _current_platform()
    matches = [a for a in manifest.artifacts.values() if a.platform == system and a.arch == machine]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        universal = [a for a in manifest.artifacts.values() if a.platform is None and a.arch is None]
        if len(universal) == 1:
            return universal[0]
    raise UpdateVerificationError(f"no unambiguous artifact for {system}-{machine}")
