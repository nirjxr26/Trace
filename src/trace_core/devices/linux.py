"""Linux OS adapter: `lsblk` + sysfs + BLKROGET [D20], [D21], [D22], [D23].

Discovery performs no evidentiary content read: `lsblk` and sysfs are discovery.
Fingerprinting is two-phase - native always, `smartctl` enrichment only inside
`inspect`, never inside `list`. The gate probe never shells out. Every degradation
names its own `UnknownCause` and is recorded as a warning, never a failure.

`fcntl` and `/sys` are Linux-only, so both are reached through indirection: this
module imports and runs on any platform, which is what lets the tribunal test it
off-device with injected helpers.
"""

import ctypes
import errno
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from trace_core.core.clock import now_utc
from trace_core.devices._subprocess import (
    EACCES_DETAIL,
    SMARTCTL_TYPES,
    HelperFailure,
    clean_text,
    decode_json,
    deep_text,
    lsblk_json,
    non_negative_int,
    read_sysfs_ro,
    run_capped,
    smartctl_readiness,
    smartctl_succeeded,
)
from trace_core.devices.domain import (
    RESULT_FALSE,
    RESULT_TRUE,
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
    verdict_for,
)
from trace_core.devices.synthetic import absent_serial

ADAPTER_VERSION: Final[str] = "linux-v1"
DEV_ROOT: Final[str] = "/dev"
SYSFS_BLOCK: Final[str] = "/sys/block"
BLKROGET: Final[int] = 0x0000125E

CHECK_EXISTENCE: Final[str] = "exists"
CHECK_OPEN_EXCLUSIVE: Final[str] = "open_exclusive"
CHECK_SYSFS_RO: Final[str] = "sysfs_ro"
CHECK_BLKROGET: Final[str] = "blkroget"

TRANSPORTS: Final[dict[str, DeviceInterface]] = {
    "usb": DeviceInterface.USB,
    "sata": DeviceInterface.SATA,
    "nvme": DeviceInterface.NVME,
    "scsi": DeviceInterface.SCSI,
    "virtio": DeviceInterface.VIRTUAL,
}


@dataclass(frozen=True, slots=True)
class _Native:
    serial: str
    model: str
    interface: DeviceInterface
    wwn: str | None = None


class LinuxDevice:
    """Enumerate, inspect and gate Linux block devices. One object serves all three ports."""

    adapter_version = ADAPTER_VERSION

    def __init__(self, dev_root: str = DEV_ROOT) -> None:
        self._dev_root = dev_root
        self._rows: dict[str, dict[str, Any]] = {}

    def list_block_devices(self) -> list[DeviceInfo]:
        # Cleared first so a failed enumeration cannot leave a previous run's rows behind
        # for `inspect` to read as current evidence.
        self._rows = {}
        document = lsblk_json()
        self._rows = rows = _rows_by_name(document)
        return [info for info in (self._info(row) for _, row in sorted(rows.items())) if info is not None]

    def change_token(self) -> tuple[str, ...]:
        """Kernel block-device names. A readdir, not a subprocess: cheap enough to poll."""
        try:
            return tuple(sorted(os.listdir(SYSFS_BLOCK)))
        except OSError:
            return ()

    def inspect(self, device: DeviceInfo) -> DeviceInspection:
        name = Path(device.node).name
        if not self._exists(name):
            raise DeviceGoneError(device.node)
        entry = self._entry(name)
        native = self._native(device, name, entry)
        cause, firmware, enriched_wwn = self._enrich(name, native.interface)
        fingerprint = DeviceFingerprint(
            serial=ObservedSerial(value=native.serial),
            model=native.model,
            capacity_bytes=non_negative_int(entry.get("size")) or device.size_bytes or 0,
            firmware=firmware,
            interface=native.interface,
            wwn=native.wwn or enriched_wwn,
            source="smartctl" if cause is None and (firmware or enriched_wwn) else "os",
        )
        return DeviceInspection(device=device, fingerprint=fingerprint, inspected_at=now_utc())

    def verify(self, device: DeviceInfo) -> GateCheck:
        checks, cause = self._probe(Path(device.node).name)
        verdict, cause = verdict_for(
            checks,
            read_only_check=CHECK_SYSFS_RO,
            read_only_result=RESULT_TRUE,
            writable_result=RESULT_FALSE,
            cause=cause,
        )
        evidence = ProtectionEvidence(
            platform="linux",
            checks=checks,
            adapter_version=self.adapter_version,
            checked_at=now_utc(),
            unknown_cause=cause,
        )
        return GateCheck(verdict=verdict, evidence=evidence, checked_at=now_utc())

    def _exists(self, name: str) -> bool:
        return (Path(self._dev_root) / name).exists()

    def _entry(self, name: str) -> dict[str, Any]:
        """The `lsblk` row for one device, from the row set enumeration already captured.

        `inspect` is evidence capture and may re-read the device, but re-running `lsblk`
        would re-walk the whole block tree for a single row. The cache is keyed by name,
        refreshed whenever the caller enumerates, and every lookup misses to sysfs rather
        than to a stale row, so a device absent from it is reported as unknown.
        """
        cached = self._rows.get(name)
        if cached is not None:
            return cached
        try:
            document = lsblk_json()
        except HelperFailure:
            return {}
        self._rows = rows = _rows_by_name(document)
        return rows.get(name, {})

    def _info(self, entry: dict[str, Any]) -> DeviceInfo | None:
        name = clean_text(entry.get("name"))
        if name is None:
            return None
        return DeviceInfo(
            node=f"{self._dev_root}/{name}",
            kind=DeviceKind.OS,
            requires_real_hardware_opt_in=True,
            size_bytes=non_negative_int(entry.get("size")),
            model_hint=clean_text(entry.get("model")),
        )

    def _native(self, device: DeviceInfo, name: str, entry: dict[str, Any]) -> _Native:
        """Identity for one device, from lsblk first and sysfs second.

        The serial fallback was the node path, so two different disks that both report no
        serial produced the SAME fingerprint: unplug A from /dev/sdb, plug a different
        physical B that also reports no serial, and any later comparison keyed on serial
        concludes "same device". `absent_serial` exists precisely to mark an absent
        identity and marks it deterministically from the node alone, so the two states
        cannot collide. The caller reports the result as `synthetic`, never as observed.
        """
        return _Native(
            serial=clean_text(entry.get("serial"))
            or _sysfs_value(name, "serial")
            or absent_serial(f"{self._dev_root}/{name}"),
            model=clean_text(entry.get("model")) or device.model_hint or name,
            interface=_interface(clean_text(entry.get("tran")) or _sysfs_value(name, "transport")),
            wwn=clean_text(entry.get("wwn")),
        )

    def _enrich(self, name: str, interface: DeviceInterface) -> tuple[UnknownCause | None, str | None, str | None]:
        device_type = SMARTCTL_TYPES.get(interface)
        if device_type is None:
            return None, None, None
        node = f"{self._dev_root}/{name}"
        try:
            if (cause := smartctl_readiness()) is not None:
                return cause, None, None
            raw = run_capped(["smartctl", "-d", device_type, "-j", "-i", node])
            document = decode_json(raw, tool="smartctl")
        except HelperFailure as failure:
            return failure.cause, None, None
        if not isinstance(document, dict) or not smartctl_succeeded(document):
            return UnknownCause.SMARTCTL_MALFORMED, None, None
        return None, deep_text(document, "firmware_version"), deep_text(document, "wwn")

    def _probe(self, name: str) -> tuple[tuple[ProtectionCheck, ...], UnknownCause | None]:
        present = self._exists(name)
        checks = [ProtectionCheck(name=CHECK_EXISTENCE, result=str(present))]
        if not present:
            return tuple(checks), UnknownCause.DEVICE_DISAPPEARED
        exclusive = self._exclusive_open(Path(self._dev_root) / name)
        checks.append(_exclusive_check(exclusive))
        sysfs_ro = read_sysfs_ro(name)
        checks.append(ProtectionCheck(name=CHECK_SYSFS_RO, result=_tri_state(sysfs_ro)))
        ioctl = self._blkroget(Path(self._dev_root) / name)
        checks.append(_ioctl_check(ioctl))
        return tuple(checks), _probe_cause(sysfs_ro, ioctl, exclusive)

    def _exclusive_open(self, path: Path) -> bool | OSError:
        """Whether an exclusive open was refused, and why not when it was.

        `O_EXCL` on a block device does NOT measure write protection. open(2): with
        O_EXCL on a block device, open fails EBUSY when the device "is in use by the
        system (e.g., it is mounted)". It has no relationship to bdev_is_read_only(), so a
        read-only-but-mounted disk fails while a writable-but-unmounted one succeeds.

        The refusal is therefore corroborating evidence that the device is claimed or
        mounted, and is recorded as such - never as the write-protection answer. That
        answer comes from `sysfs_ro`, with BLKROGET as the second opinion. Treating this
        refusal as a protection signal is what made a mounted read-only disk look
        writable and forced an unnecessary override on the examiner's own disks.
        """
        if sys.platform != "linux":
            return OSError(errno.ENOSYS, "exclusive open is Linux-only")
        try:
            os.close(os.open(path, os.O_RDONLY | os.O_EXCL))
        except PermissionError:
            return True
        except OSError as exc:
            return exc
        return False

    def _blkroget(self, path: Path) -> bool | OSError | None:
        """The kernel's own write-protection answer, via BLKROGET.

        The previous call was `fcntl.ioctl(fd, BLKROGET, 1)`. BLKROGET is `_IO(0x12, 94)`
        and its handler is `put_user(bdev_is_read_only(bdev), (int __user *)arg)` - a
        4-byte WRITE to a user pointer. ctypes passes an integer argument through as the
        pointer value, so this issued `ioctl(fd, code, 1)`, and put_user to address 1
        returned EFAULT. It then returned None on every call, for every device, so the
        second opinion never existed and SYSFS_DISAGREEMENT was unreachable.

        An output buffer is allocated and passed instead, so the value actually lands in
        memory this process owns.
        """
        if sys.platform != "linux":
            return None
        try:
            import fcntl
        except ImportError:
            return None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_EXCL)
        except OSError as exc:
            return exc
        try:
            buffer = bytearray(ctypes.c_int())
            fcntl.ioctl(fd, BLKROGET, buffer, True)
        except OSError:
            return None
        finally:
            os.close(fd)
        return ctypes.c_int.from_buffer(buffer).value == 1


def _error_cause(ioctl: bool | OSError | None, exclusive: bool | OSError) -> UnknownCause | None:
    """First errno that names a specific cause, else a generic IOCTL_FAILURE."""
    for outcome in (ioctl, exclusive):
        if isinstance(outcome, OSError) and outcome.errno == errno.EACCES:
            return UnknownCause.EACCES
    for outcome in (ioctl, exclusive):
        # A device yanked between the existence check and the open arrives as ENOENT.
        # Folding that into IOCTL_FAILURE recorded "we could not tell" for a device that
        # was gone, and the two need different operator responses: re-attach, or escalate.
        if isinstance(outcome, OSError) and outcome.errno == errno.ENOENT:
            return UnknownCause.DEVICE_DISAPPEARED
    for outcome in (ioctl, exclusive):
        if isinstance(outcome, OSError) and outcome.errno != errno.ENOSYS:
            return UnknownCause.IOCTL_FAILURE
    return None


def _probe_cause(sysfs_ro: bool | None, ioctl: bool | OSError | None, exclusive: bool | OSError) -> UnknownCause | None:
    cause = _error_cause(ioctl, exclusive)
    if cause is not None:
        return cause
    if sysfs_ro is None:
        return UnknownCause.SYSFS_DISAGREEMENT
    if ioctl is None:
        return UnknownCause.IOCTL_FAILURE
    if isinstance(ioctl, bool) and ioctl is not sysfs_ro:
        return UnknownCause.SYSFS_DISAGREEMENT
    return None


def _exclusive_check(exclusive: bool | OSError) -> ProtectionCheck:
    if isinstance(exclusive, bool):
        return ProtectionCheck(name=CHECK_OPEN_EXCLUSIVE, result="denied" if exclusive else "opened")
    # PermissionError is an OSError with errno EACCES, and `_exclusive_open` converts it
    # to True before it can be returned, so the isinstance branch below was unreachable.
    if exclusive.errno == errno.EACCES:
        return ProtectionCheck(
            name=CHECK_OPEN_EXCLUSIVE,
            result=UnknownCause.EACCES.value,
            detail=EACCES_DETAIL,
        )
    if exclusive.errno == errno.ENOENT:
        return ProtectionCheck(
            name=CHECK_OPEN_EXCLUSIVE,
            result=UnknownCause.DEVICE_DISAPPEARED.value,
            detail="device disappeared between enumeration and the probe",
        )
    if exclusive.errno == errno.ENOSYS:
        return ProtectionCheck(name=CHECK_OPEN_EXCLUSIVE, result="unsupported")
    return ProtectionCheck(
        name=CHECK_OPEN_EXCLUSIVE, result=UnknownCause.IOCTL_FAILURE.value, detail=exclusive.strerror
    )


def _ioctl_check(ioctl: bool | OSError | None) -> ProtectionCheck:
    if isinstance(ioctl, bool):
        return ProtectionCheck(name=CHECK_BLKROGET, result=str(ioctl))
    if isinstance(ioctl, PermissionError):
        return ProtectionCheck(
            name=CHECK_BLKROGET,
            result=UnknownCause.EACCES.value,
            detail=EACCES_DETAIL,
        )
    if isinstance(ioctl, OSError):
        return ProtectionCheck(name=CHECK_BLKROGET, result=UnknownCause.IOCTL_FAILURE.value, detail=ioctl.strerror)
    return ProtectionCheck(name=CHECK_BLKROGET, result="unsupported")


def _tri_state(value: bool | None) -> str:
    return "unknown" if value is None else str(value)


def _rows_by_name(document: Any) -> dict[str, dict[str, Any]]:
    """Name-indexed `lsblk` rows. One builder for enumeration and lookup, so they cannot disagree."""
    rows: dict[str, dict[str, Any]] = {}
    for entry in _entries(document):
        name = clean_text(entry.get("name"))
        if name is not None:
            rows[name] = entry
    return rows


def _entries(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    blockdevices = document.get("blockdevices")
    if not isinstance(blockdevices, list):
        return []
    return [entry for entry in _flatten(blockdevices) if isinstance(entry, dict)]


def _flatten(entries: list[Any]) -> list[Any]:
    """`lsblk` nests partitions and holders inside their parent as `children`."""
    out: list[Any] = []
    for entry in entries:
        out.append(entry)
        if isinstance(entry, dict) and isinstance(entry.get("children"), list):
            out.extend(_flatten(entry["children"]))
    return out


def _sysfs_value(name: str, key: str) -> str | None:
    """Kernel attribute for a block device. Absent attribute is None, never a guess."""
    return clean_text(_read(f"{SYSFS_BLOCK}/{name}/{key}"))


def _read(path: str) -> str | None:
    """A sysfs attribute as text, or None when it cannot be read.

    `UnicodeDecodeError` is a ValueError, not an OSError, so a device declaring a
    non-UTF-8 serial - which a USB stick or SD reader is free to do, since these bytes
    come from the hardware and not the kernel - escaped `inspect()` as an unexpected
    exception. That broke the contract that every degradation names its own cause: no
    inspection was built, nothing was ledgered, and the operator saw a generic failure.
    Undecodable bytes are replaced rather than raised; the value is untrusted hardware
    text either way, and `ObservedSerial` bounds and strips it.
    """
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _interface(transport: str | None) -> DeviceInterface:
    if transport is None:
        return DeviceInterface.UNKNOWN
    return TRANSPORTS.get(transport.strip().lower(), DeviceInterface.UNKNOWN)
