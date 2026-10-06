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
    WpVerdict,
)

ADAPTER_VERSION: Final[str] = "win32-v1"
PHYSICAL_DRIVE: Final[str] = r"\\.\PhysicalDrive"

CHECK_EXISTENCE: Final[str] = "exists"
CHECK_IS_WRITABLE: Final[str] = "ioctl_is_writable"

GENERIC_READ: Final[int] = 0x80000000
FILE_SHARE_READ: Final[int] = 0x00000001
OPEN_EXISTING: Final[int] = 3
INVALID_HANDLE_VALUE: Final[int] = -1
ERROR_ACCESS_DENIED: Final[int] = 5

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
        drive = self._drive(index)
        if drive is None:
            raise DeviceGoneError(device.node)
        cause, wwn = self._enrich(index, drive.interface)
        fingerprint = DeviceFingerprint(
            serial=ObservedSerial(value=drive.serial or f"{PHYSICAL_DRIVE}{index}"),
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
        evidence = ProtectionEvidence(
            platform="windows",
            checks=checks,
            adapter_version=self.adapter_version,
            checked_at=now_utc(),
            unknown_cause=cause,
        )
        return GateCheck(verdict=_verdict_for(cause, checks), evidence=evidence, checked_at=now_utc())

    def _node(self, index: int) -> str:
        return f"{PHYSICAL_DRIVE}{index}"

    def _drives(self) -> list[_Drive]:
        wmi = self._wmi()
        found: list[_Drive] = []
        for index in range(MAX_DRIVES):
            try:
                drive = self._drive(index)
            except DeviceAccessDeniedError:
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


def _verdict_for(cause: UnknownCause | None, checks: tuple[ProtectionCheck, ...]) -> WpVerdict:
    if cause is not None:
        return WpVerdict.UNKNOWN
    return WpVerdict.WRITABLE if any(c.result == "True" for c in checks) else WpVerdict.READ_ONLY


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

    size = 4096
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        needed = kernel.QueryDosDeviceW(None, buffer, size)
        if needed:
            return set("".join(buffer[:needed]).split("\x00")) - {""}
        if kernel.GetLastError() != 234 or size >= 1 << 20:
            return set()
        size *= 2


def _try_open(node: str) -> tuple[int | None, int]:
    """Read-share handle plus the Win32 error when it fails."""
    kernel = _windll()
    if kernel is None:
        return None, 0
    import ctypes

    handle = kernel.CreateFileW(
        ctypes.c_wchar_p(node),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (0, INVALID_HANDLE_VALUE):
        return None, int(kernel.GetLastError())
    return int(handle), 0


def _close(handle: int) -> None:
    kernel = _windll()
    if kernel is not None:
        kernel.CloseHandle(handle)


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

INTERFACE_BUS_TYPES = {
    0x01: DeviceInterface.SCSI,
    0x03: DeviceInterface.SATA,
    0x07: DeviceInterface.USB,
    0x08: DeviceInterface.SCSI,
    0x09: DeviceInterface.SCSI,
    0x0A: DeviceInterface.SCSI,
    0x0B: DeviceInterface.SATA,
    0x0F: DeviceInterface.VIRTUAL,
    0x11: DeviceInterface.NVME,
    0x14: DeviceInterface.VIRTUAL,
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
