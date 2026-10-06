"""File-backed device adapter: the default, and the evidence contract [D33].

Zero privileges, zero risk, deterministic. Every probe here emits the same
`ProtectionEvidence` shape the OS adapters must match, so this file is the
tribunal rather than a simplified stand-in. `enumerate` performs no evidentiary
read [D23]: size comes from `stat` alone. The adapter reports; the domain decides.
"""

from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Literal

from trace_core.core.clock import now_utc
from trace_core.core.fs import check_contained, check_device_contained, sha256_file
from trace_core.devices._subprocess import EACCES_DETAIL
from trace_core.devices.domain import (
    DeviceFingerprint,
    DeviceGoneError,
    DeviceInfo,
    DeviceInspection,
    DeviceInterface,
    DeviceKind,
    GateCheck,
    ObservedSerial,
    ProtectionCheck,
    ProtectionEvidence,
    UnknownCause,
    WpVerdict,
)
from trace_core.devices.synthetic import absent_serial, synthetic_serial

ADAPTER_NAME = "file"
PLATFORM: Literal["fake"] = "fake"

PROTECTED = "protected"
WRITABLE = "writable"
UNKNOWN_PROTECTION = "unknown_protection"
PERMISSION_DENIED = "permission_denied"
PARENT_DISAGREEMENT = "parent_disagreement"
MISSING = "disappeared"

_CHECK_OPEN = "open_exclusive"
_CHECK_PARENT = "parent_writable"
_CHECK_EXISTENCE = "exists"

_OPEN_OK = "ok"
_PARENT_WRITABLE = "True"
_PARENT_READ_ONLY = "False"
_VANISHED = "device vanished during the probe"


@dataclass(frozen=True, slots=True)
class _Profile:
    """One fault profile's entire observable outcome. Keyed by value, never by identity."""

    cause: UnknownCause | None
    open_result: str
    open_detail: str | None
    parent_writable: str
    parent_detail: str | None = None


_PROFILES: dict[str, _Profile] = {
    PROTECTED: _Profile(None, _OPEN_OK, None, _PARENT_READ_ONLY),
    WRITABLE: _Profile(None, _OPEN_OK, None, _PARENT_WRITABLE),
    UNKNOWN_PROTECTION: _Profile(
        UnknownCause.IOCTL_FAILURE, "IOCTL_FAILURE", "exclusive open returned no verdict", _PARENT_WRITABLE
    ),
    PERMISSION_DENIED: _Profile(UnknownCause.EACCES, "EACCES", EACCES_DETAIL, _PARENT_WRITABLE),
    PARENT_DISAGREEMENT: _Profile(
        None, _OPEN_OK, None, _PARENT_WRITABLE, "sysfs says read-only, directory says writable"
    ),
    MISSING: _Profile(UnknownCause.DEVICE_DISAPPEARED, "DEVICE_DISAPPEARED", _VANISHED, _PARENT_WRITABLE),
}

BEHAVIOURS: frozenset[str] = frozenset(_PROFILES)


class FileDevice:
    """Enumerate and inspect plain files as if they were block devices."""

    adapter_version = ADAPTER_NAME

    def __init__(self, root: str | Path, *, behaviour: str = PROTECTED) -> None:
        if behaviour not in _PROFILES:
            raise ValueError(f"unknown behaviour {behaviour!r}; expected one of {sorted(_PROFILES)}")
        self._root = Path(root)
        self.behaviour = behaviour
        self._profile = _PROFILES[behaviour]

    def list_block_devices(self) -> list[DeviceInfo]:
        if not self._root.is_dir():
            return []
        return [info for info in map(self._info, sorted(self._root.iterdir())) if info is not None]

    def change_token(self) -> tuple[str, ...]:
        """Entry names. A plugged or unplugged disk changes the set, so the view polls this."""
        if not self._root.is_dir():
            return ()
        return tuple(sorted(path.name for path in self._root.iterdir()))

    def inspect(self, device: DeviceInfo) -> DeviceInspection:
        path = self._path(device)
        present = path.exists()
        if not present and self._profile.cause is not UnknownCause.DEVICE_DISAPPEARED:
            raise DeviceGoneError(device.node)
        fingerprint = DeviceFingerprint(
            serial=ObservedSerial(value=synthetic_serial(sha256_file(path)) if present else absent_serial(device.node)),
            model=device.model_hint or "synthetic",
            capacity_bytes=device.size_bytes or 0,
            firmware=None,
            interface=DeviceInterface.UNKNOWN,
            wwn=None,
            source="synthetic",
        )
        return DeviceInspection(device=device, fingerprint=fingerprint, inspected_at=now_utc())

    def verify(self, device: DeviceInfo) -> GateCheck:
        evidence = self._evidence(device)
        return GateCheck(verdict=_verdict_for(evidence), evidence=evidence, checked_at=now_utc())

    def _path(self, device: DeviceInfo) -> Path:
        """Resolve a node inside the root, deferring to the shared device containment check.

        The strict helper refuses the root itself, the parent and anything a symlink
        points at outside the root. The non-strict one covers a node that has already
        vanished, which is the DEVICE_DISAPPEARED case the profile exists to report.
        """
        candidate = self._root / Path(device.node).name
        if candidate.exists():
            return check_device_contained(candidate, self._root, what="device node")
        return check_contained(candidate, self._root, what="device node")

    def _info(self, path: Path) -> DeviceInfo | None:
        try:
            found = path.stat()
        except OSError:
            return None
        if not S_ISREG(found.st_mode):
            return None
        return DeviceInfo(
            node=str(path),
            kind=DeviceKind.FILE,
            requires_real_hardware_opt_in=False,
            size_bytes=found.st_size,
            model_hint=path.name,
        )

    def _evidence(self, device: DeviceInfo) -> ProtectionEvidence:
        path = self._path(device)
        present = path.exists()
        cause = self._cause(present)
        profile = self._profile
        checks = (
            ProtectionCheck(name=_CHECK_EXISTENCE, result=str(present)),
            ProtectionCheck(
                name=_CHECK_OPEN,
                result=profile.open_result if cause is None else cause.value,
                detail=profile.open_detail,
            ),
            ProtectionCheck(
                name=_CHECK_PARENT,
                result=profile.parent_writable,
                detail=profile.parent_detail,
            ),
        )
        return ProtectionEvidence(
            platform=PLATFORM,
            checks=checks,
            adapter_version=self.adapter_version,
            checked_at=now_utc(),
            unknown_cause=cause,
        )

    def _cause(self, present: bool) -> UnknownCause | None:
        """A profile that names a fault owns the cause; otherwise absence explains it."""
        if self._profile.cause is not None:
            return self._profile.cause
        return None if present else UnknownCause.DEVICE_DISAPPEARED


def _verdict_for(evidence: ProtectionEvidence) -> WpVerdict:
    if evidence.unknown_cause is not None:
        return WpVerdict.UNKNOWN
    writable = any(c.result == _PARENT_WRITABLE for c in evidence.checks if c.name == _CHECK_PARENT)
    return WpVerdict.WRITABLE if writable else WpVerdict.READ_ONLY
