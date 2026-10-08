"""Windows OS adapter: ctypes + StorageQueryProperty + IOCTL_DISK_IS_WRITABLE.

Same two-phase rule as Linux: native always, `smartctl` enrichment only inside
`inspect`, never inside `list`. The probe never shells out. Outcomes are recorded
as `ProtectionCheck` rows in the schema the fake and Linux probes emit [D33].

`ctypes.windll` is Windows-only, so every call goes through a seam that the
tribunal replaces on other platforms. That is what lets this module import and be
tested anywhere.

Subpart 3 records wrong-drive protection as a Subpart 4 requirement [D28]: mapping
a `PhysicalDriveN` node to volume letters and refusing a boot device is an
acquisition control. The three ingredients here are resolve-against-enumerated-set, the
real-hardware opt-in flag, and serial echo. Drive mapping is deliberately absent.
"""

import json
import sys
from dataclasses import dataclass
from typing import Any, Final

from trace_core.core.clock import now_utc
from trace_core.devices._subprocess import (
    EACCES_DETAIL,
    SMARTCTL_TYPES,
    HelperFailure,
    clean_text,
    decode_json,
    deep_text,
    non_negative_int,
    run_capped,
    smartctl_readiness,
    smartctl_succeeded,
)
from trace_core.devices.domain import (
    RESULT_FALSE,
    RESULT_TRUE,
    DeviceAccessDeniedError,
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

ADAPTER_VERSION: Final[str] = "win32-v1"
PHYSICAL_DRIVE: Final[str] = r"\\.\PhysicalDrive"

CHECK_EXISTENCE: Final[str] = "exists"
CHECK_IS_WRITABLE: Final[str] = "ioctl_is_writable"

GENERIC_READ: Final[int] = 0x80000000
# A read-only handle still has to share with writers. Requesting only FILE_SHARE_READ made
# CreateFileW fail with ERROR_SHARING_VIOLATION whenever another process held the drive for
# write or delete - an imaging tool, AV, the volume stack of a mounted reader - and that
# failure was reported as DEVICE_DISAPPEARED, so a present, readable evidence drive looked
# unplugged and vanished from enumeration too. Sharing is about the handle's own access
# mode, not about permitting writes through ours.
FILE_SHARE_READ: Final[int] = 0x00000001
FILE_SHARE_WRITE: Final[int] = 0x00000002
FILE_SHARE_DELETE: Final[int] = 0x00000004
SHARE_MODE: Final[int] = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
OPEN_EXISTING: Final[int] = 3
INVALID_HANDLE_VALUE: Final[int] = -1
ERROR_ACCESS_DENIED: Final[int] = 5
ERROR_INSUFFICIENT_BUFFER: Final[int] = 122
ERROR_MORE_DATA: Final[int] = 234

DOS_DEVICE_BUFFER: Final[int] = 4096
MAX_DOS_DEVICE_BUFFER: Final[int] = 1 << 20

IOCTL_STORAGE_QUERY_PROPERTY: Final[int] = 0x2D1400
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX: Final[int] = 0x000700A0
IOCTL_DISK_IS_WRITABLE: Final[int] = 0x00070024

STORAGE_PROPERTY_QUERY: Final[int] = 0
StorageDeviceProperty: Final[int] = 0
PROPERTY_QUERY_SIZE: Final[int] = 64
QUERY_BUFFER_SIZE: Final[int] = 1024
QUERY_INPUT_SIZE: Final[int] = 12
DESCRIPTOR_HEADER: Final[int] = 36

MAX_DRIVES: Final[int] = 64


@dataclass(frozen=True, slots=True)
class _Drive:
    index: int
    size_bytes: int | None
    serial: str | None
    model: str | None
    firmware: str | None
    interface: DeviceInterface


class Win32Device:
    """Enumerate, inspect and gate Windows physical drives. One object serves all three ports."""

    adapter_version = ADAPTER_VERSION

    def list_block_devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                node=self._node(drive.index),
                kind=DeviceKind.OS,
                requires_real_hardware_opt_in=True,
                size_bytes=drive.size_bytes,
                model_hint=drive.model,
            )
            for drive in self._drives()
        ]

    def inspect(self, device: DeviceInfo) -> DeviceInspection:
        index = _index_of(device.node)
        if index is None:
            raise DeviceGoneError(device.node)
        node = self._node(index)
        drive = self._drive(index)
        if drive is None:
            raise DeviceGoneError(device.node)
        cause, wwn = self._enrich(index, drive.interface)
        fingerprint = DeviceFingerprint(
            serial=ObservedSerial(value=drive.serial or absent_serial(node)),
            model=drive.model or f"PhysicalDrive{index}",
            capacity_bytes=drive.size_bytes or 0,
            firmware=drive.firmware,
            interface=drive.interface,
            wwn=wwn,
            source="smartctl" if cause is None and wwn else "os",
        )
        return DeviceInspection(device=device, fingerprint=fingerprint, inspected_at=now_utc())

    def verify(self, device: DeviceInfo) -> GateCheck:
        index = _index_of(device.node)
        checks, cause = self._probe(index)
        verdict, cause = verdict_for(
            checks,
            read_only_check=CHECK_IS_WRITABLE,
            read_only_result=RESULT_FALSE,
            writable_result=RESULT_TRUE,
            cause=cause,
        )
        evidence = ProtectionEvidence(
            platform="windows",
            checks=checks,
            adapter_version=self.adapter_version,
            checked_at=now_utc(),
            unknown_cause=cause,
        )
        return GateCheck(verdict=verdict, evidence=evidence, checked_at=now_utc())

    def _node(self, index: int) -> str:
        return f"{PHYSICAL_DRIVE}{index}"

    def _drives(self) -> list[_Drive]:
        """Every openable drive. CIM is fetched only when a handle is refused.

        The CIM query spawns PowerShell and costs a few hundred milliseconds; it exists
        solely to describe drives this process cannot open, so paying for it on the normal
        elevated path made enumeration dominated by a subprocess it never used.
        """
        wmi: dict[int, dict[str, Any]] | None = None
        found: list[_Drive] = []
        for index in range(MAX_DRIVES):
            try:
                drive = self._drive(index)
            except DeviceAccessDeniedError:
                if wmi is None:
                    wmi = self._wmi()
                drive = _denied_drive(index, wmi.get(index, {}))
            if drive is not None:
                found.append(drive)
        return found

    def _wmi(self) -> dict[int, dict[str, Any]]:
        """Model/serial/size per drive index without opening any handle."""
        if sys.platform != "win32":
            return {}
        try:
            raw = run_capped(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_DiskDrive | Select-Object DeviceID,Model,SerialNumber,Size | ConvertTo-Json -Compress",
                ],
                timeout=15,
            )
        except HelperFailure:
            return {}
        try:
            document = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            return {}
        rows = document if isinstance(document, list) else [document]
        enriched: dict[int, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = _index_of(str(row.get("DeviceID") or ""))
            if index is not None:
                enriched[index] = row
        return enriched

    def change_token(self) -> tuple[str, ...]:
        """DOS device names. One query, no handles: cheap enough to poll."""
        return tuple(sorted(_query_dos_devices()))

    def _drive(self, index: int) -> _Drive | None:
        handle, error = _try_open(self._node(index))
        if handle is None:
            if error == ERROR_ACCESS_DENIED:
                raise DeviceAccessDeniedError(
                    f"access denied for {self._node(index)}; re-run from an elevated Administrator shell"
                )
            return None
        try:
            return _Drive(
                index=index,
                size_bytes=_geometry_size(handle),
                serial=_query_text(handle, "serial"),
                model=_query_text(handle, "model"),
                firmware=_query_text(handle, "firmware"),
                interface=_interface(handle),
            )
        finally:
            _close(handle)

    def _enrich(self, index: int, interface: DeviceInterface) -> tuple[UnknownCause | None, str | None]:
        device_type = SMARTCTL_TYPES.get(interface)
        if device_type is None:
            return None, None
        try:
            if (cause := smartctl_readiness()) is not None:
                return cause, None
            raw = run_capped(["smartctl", "-d", device_type, "-j", "-i", self._node(index)])
            document = decode_json(raw, tool="smartctl")
        except HelperFailure as failure:
            return failure.cause, None
        if not isinstance(document, dict) or not smartctl_succeeded(document):
            return UnknownCause.SMARTCTL_MALFORMED, None
        return None, deep_text(document, "wwn")

    def _probe(self, index: int | None) -> tuple[tuple[ProtectionCheck, ...], UnknownCause | None]:
        if index is None:
            return (ProtectionCheck(name=CHECK_EXISTENCE, result="False"),), UnknownCause.DEVICE_DISAPPEARED
        handle, error = _try_open(self._node(index))
        if handle is None:
            if error == ERROR_ACCESS_DENIED:
                return (
                    ProtectionCheck(name=CHECK_EXISTENCE, result="True"),
                    ProtectionCheck(name=CHECK_IS_WRITABLE, result=UnknownCause.EACCES.value, detail=EACCES_DETAIL),
                ), UnknownCause.EACCES
            return (ProtectionCheck(name=CHECK_EXISTENCE, result="False"),), UnknownCause.DEVICE_DISAPPEARED
        try:
            checks, cause = _writable_checks(handle)
        finally:
            _close(handle)
        return (ProtectionCheck(name=CHECK_EXISTENCE, result="True"), *checks), cause


def _denied_drive(index: int, row: dict[str, Any]) -> _Drive:
    """A drive the shell may see but not open. Real identity when CIM knows it, blanks when not."""
    return _Drive(
        index=index,
        size_bytes=non_negative_int(row.get("Size")),
        serial=clean_text(row.get("SerialNumber")),
        model=clean_text(row.get("Model")),
        firmware=None,
        interface=DeviceInterface.UNKNOWN,
    )


def _writable_checks(handle: int) -> tuple[tuple[ProtectionCheck, ...], UnknownCause | None]:
    outcome = _is_writable(handle)
    if isinstance(outcome, bool):
        return (ProtectionCheck(name=CHECK_IS_WRITABLE, result=str(outcome)),), None
    if outcome is None:
        return (ProtectionCheck(name=CHECK_IS_WRITABLE, result="unsupported"),), UnknownCause.IOCTL_FAILURE
    if outcome == ERROR_ACCESS_DENIED:
        return (
            ProtectionCheck(name=CHECK_IS_WRITABLE, result=UnknownCause.EACCES.value, detail=EACCES_DETAIL),
        ), UnknownCause.EACCES
    return (
        ProtectionCheck(name=CHECK_IS_WRITABLE, result=UnknownCause.IOCTL_FAILURE.value),
    ), UnknownCause.IOCTL_FAILURE


def _index_of(node: str) -> int | None:
    name = str(node).replace("/", "\\").rsplit("\\", 1)[-1]
    if not name.lower().startswith("physicaldrive"):
        return None
    digits = name[len("physicaldrive") :]
    if not digits.isdigit():
        return None
    index = int(digits)
    return index if 0 <= index < MAX_DRIVES else None


def _windll():  # type: ignore[no-untyped-def]
    import ctypes

    return ctypes.windll.kernel32 if sys.platform == "win32" else None


def _query_dos_devices() -> set[str]:
    """All DOS device names. Empty off-platform."""
    kernel = _windll()
    if kernel is None:
        return set()
    import ctypes

    size = DOS_DEVICE_BUFFER
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        needed = kernel.QueryDosDeviceW(None, buffer, size)
        if needed:
            return set("".join(buffer[:needed]).split("\x00")) - {""}
        if kernel.GetLastError() not in (ERROR_INSUFFICIENT_BUFFER, ERROR_MORE_DATA) or size >= MAX_DOS_DEVICE_BUFFER:
            return set()
        size *= 2


def _try_open(node: str) -> tuple[int | None, int]:
    """Read-only handle that still shares with writers, plus the Win32 error on failure.

    The handle asks only for GENERIC_READ, so sharing write and delete permits nothing
    through this handle; it only stops another process's open from failing because of us.
    """
    kernel = _windll()
    if kernel is None:
        return None, 0
    import ctypes
    import ctypes.wintypes as wintypes

    create_file = kernel.CreateFileW
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        ctypes.c_wchar_p(node),
        GENERIC_READ,
        SHARE_MODE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None, int(kernel.GetLastError())
    return int(handle), 0


def _close(handle: int) -> None:
    """Close a handle, reporting a failure rather than leaking it silently.

    `_drives` opens and closes up to MAX_DRIVES handles per enumeration and this runs on
    every poll cycle, so a close that failed would accumulate without anything to show
    for it. The return value is checked and recorded in the log; the caller cannot do
    anything about it, but it is no longer invisible.
    """
    kernel = _windll()
    if kernel is None:
        return
    import ctypes.wintypes as wintypes

    if not kernel.CloseHandle(wintypes.HANDLE(handle)):
        import structlog

        structlog.get_logger().warning("CloseHandle failed", handle=handle, win32_error=int(kernel.GetLastError()))


def _device_ioctl(handle: int, code: int, in_buffer: int, in_size: int, out_size: int) -> tuple[Any, int] | None:
    kernel = _windll()
    if kernel is None:
        return None
    import ctypes

    buffer = ctypes.create_string_buffer(out_size)
    returned = ctypes.c_ulong(0)
    ok = kernel.DeviceIoControl(
        ctypes.c_void_p(handle),
        ctypes.c_ulong(code),
        ctypes.c_void_p(in_buffer),
        ctypes.c_ulong(in_size),
        ctypes.byref(buffer),
        ctypes.c_ulong(out_size),
        ctypes.byref(returned),
        None,
    )
    return (buffer, returned.value) if ok else None


def _geometry_size(handle: int) -> int | None:
    result = _device_ioctl(handle, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, 0, 0, 512)
    if result is None:
        return None
    buffer, _ = result
    return int.from_bytes(buffer[24:32], "little", signed=True) or None


def _query_text(handle: int, key: str) -> str | None:
    import ctypes

    query = _property_query()
    if query is None:
        return None
    result = _device_ioctl(
        handle, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.addressof(query), QUERY_INPUT_SIZE, QUERY_BUFFER_SIZE
    )
    if result is None:
        return None
    buffer, returned = result
    if returned < DESCRIPTOR_HEADER:
        return None
    return _decode(bytes(buffer[:returned]), key)


def _property_query():  # type: ignore[no-untyped-def]
    """Query buffer for StorageDeviceProperty. The buffer object itself, not its address.

    The address of a temporary is only valid while something holds it; the old code
    returned `addressof()` of a local, so the device received a dangling pointer and
    every property query failed while the open succeeded.
    """
    if _windll() is None:
        return None
    import ctypes

    query = ctypes.create_string_buffer(PROPERTY_QUERY_SIZE)
    ctypes.memmove(query, bytes([0, STORAGE_PROPERTY_QUERY, StorageDeviceProperty, 0, 0, 0, 0, 0]), 8)
    return query


OFF_PRODUCT_ID = 16
OFF_PRODUCT_REVISION = 20
OFF_SERIAL_NUMBER = 24
OFF_BUS_TYPE = 28

DESCRIPTOR_TEXT_OFFSETS = {
    "serial": OFF_SERIAL_NUMBER,
    "model": OFF_PRODUCT_ID,
    "firmware": OFF_PRODUCT_REVISION,
}

# STORAGE_BUS_TYPE (_STORAGE_BUS_TYPE, ntddstor.h): 0x0C=BusTypeSd, 0x0D=BusTypeMmc,
# 0x0E=BusTypeVirtual, 0x13=BusTypeMax. 0x14 was listed here and does not exist, while the
# three real values were missing, so every SD card, MMC device and hypervisor-attached
# disk - the commonest lab targets - resolved to UNKNOWN and skipped smartctl entirely.
INTERFACE_BUS_TYPES = {
    0x01: DeviceInterface.SCSI,
    0x03: DeviceInterface.SATA,
    0x07: DeviceInterface.USB,
    0x08: DeviceInterface.SCSI,
    0x09: DeviceInterface.SCSI,
    0x0A: DeviceInterface.SCSI,
    0x0B: DeviceInterface.SATA,
    0x0C: DeviceInterface.SCSI,
    0x0D: DeviceInterface.SCSI,
    0x0E: DeviceInterface.VIRTUAL,
    0x0F: DeviceInterface.VIRTUAL,
    0x11: DeviceInterface.NVME,
}


def _decode(raw: bytes, key: str) -> str | None:
    """Device text from a STORAGE_DEVICE_DESCRIPTOR. Offsets are byte positions from its start."""
    offset_at = DESCRIPTOR_TEXT_OFFSETS.get(key)
    if offset_at is None or len(raw) < offset_at + 4:
        return None
    start = int.from_bytes(raw[offset_at : offset_at + 4], "little")
    if start <= 0 or start >= len(raw):
        return None
    return raw[start:].split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip() or None


def _interface(handle: int) -> DeviceInterface:
    import ctypes

    query = _property_query()
    if query is None:
        return DeviceInterface.UNKNOWN
    result = _device_ioctl(
        handle, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.addressof(query), QUERY_INPUT_SIZE, QUERY_BUFFER_SIZE
    )
    if result is None:
        return DeviceInterface.UNKNOWN
    buffer, returned = result
    if returned < OFF_BUS_TYPE + 1:
        return DeviceInterface.UNKNOWN
    return INTERFACE_BUS_TYPES.get(bytes(buffer[:returned])[OFF_BUS_TYPE], DeviceInterface.UNKNOWN)


def _is_writable(handle: int) -> bool | int | None:
    """True writable, False read-only, a Win32 error code on failure, None when unsupported."""
    if _windll() is None:
        return None
    result = _device_ioctl(handle, IOCTL_DISK_IS_WRITABLE, 0, 0, 16)
    if result is None:
        kernel = _windll()
        return int(kernel.GetLastError()) if kernel is not None else None
    return True
