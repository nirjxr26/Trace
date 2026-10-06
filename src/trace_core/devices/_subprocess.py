"""Bounded subprocess and sysfs helpers for the OS adapters [D21].

Every helper here is semantic (`lsblk_json`, `run_capped`, never a generic
`run_command`) and every one takes an argv list, `shell=False`, a timeout and a
hard stdout byte cap. A hung or flood-emitting helper degrades to UNKNOWN rather
than hanging or exhausting memory. The gate probe never calls these.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Final

from trace_core.devices.domain import DeviceInterface, UnknownCause

STDOUT_CAP: Final[int] = 1 << 20
TIMEOUT_SECONDS: Final[int] = 15
SYSFS_RO_PATH: Final[str] = "/sys/block"
MIN_SMARTCTL: Final[tuple[int, ...]] = (5, 16)
EACCES_DETAIL: Final[str] = "EACCES: access denied; retry from an elevated shell"

SMARTCTL_TYPES: Final[dict[DeviceInterface, str]] = {
    DeviceInterface.USB: "usb",
    DeviceInterface.SATA: "sat",
    DeviceInterface.NVME: "nvme",
    DeviceInterface.SCSI: "scsi",
}


class HelperFailure(Exception):
    """A helper could not produce usable output; carries the cause to record as evidence."""

    def __init__(self, cause: UnknownCause, detail: str) -> None:
        super().__init__(detail)
        self.cause = cause
        self.detail = detail


def run_capped(argv: list[str], *, timeout: int = TIMEOUT_SECONDS, cap: int = STDOUT_CAP) -> bytes:
    """Run a fixed argv list and return stdout, refusing anything over `cap` bytes.

    stderr is discarded rather than buffered: a hostile tool can flood it, and the
    caller has no use for it once a non-zero exit has already become a named cause.
    """
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HelperFailure(UnknownCause.SMARTCTL_TIMEOUT, f"{argv[0]} timed out after {timeout}s") from exc
    except OSError as exc:
        raise HelperFailure(UnknownCause.TOOL_MISSING, f"{argv[0]} could not be executed") from exc
    if len(proc.stdout) > cap:
        raise HelperFailure(UnknownCause.SMARTCTL_MALFORMED, f"{argv[0]} stdout exceeded {cap} bytes and was discarded")
    return proc.stdout


def decode_json(raw: bytes, *, tool: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise HelperFailure(UnknownCause.SMARTCTL_MALFORMED, f"{tool} emitted unparseable JSON") from exc


def read_sysfs_ro(device_name: str) -> bool | None:
    """`/sys/block/<dev>/ro` as 0/1, or None when sysfs cannot answer."""
    path = Path(SYSFS_RO_PATH) / device_name / "ro"
    try:
        return path.read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return None


def lsblk_json(*, cap: int = STDOUT_CAP) -> Any:
    """One `lsblk -J` call. Stdout is capped before parse [D21]."""
    raw = run_capped(
        ["lsblk", "-J", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN,ROTA,RO,WWN", "--bytes"],
        cap=cap,
    )
    return decode_json(raw, tool="lsblk")


def smartctl_version() -> tuple[int, ...] | None:
    """Parsed smartctl version, or None when the tool is absent."""
    try:
        raw = run_capped(["smartctl", "--version"], timeout=5)
    except HelperFailure:
        return None
    first = raw.decode("utf-8", errors="replace").splitlines()[:1]
    if not first:
        return None
    numbers = first[0].replace(",", ".").split()
    version = next((part for part in numbers if part[:1].isdigit()), "")
    parsed = tuple(int(part) for part in version.split(".") if part.isdigit())
    return parsed or None


def smartctl_readiness() -> UnknownCause | None:
    """None when `smartctl -j` is usable, else the cause to record.

    Single source for the [D22] floor so both OS adapters degrade identically:
    absent is TOOL_MISSING, present-but-old is TOOL_TOO_OLD. The version is read
    once; `-j` needs smartctl >= 5.16.
    """
    parsed = smartctl_version()
    if parsed is None:
        return UnknownCause.TOOL_MISSING
    if parsed[: len(MIN_SMARTCTL)] < MIN_SMARTCTL:
        return UnknownCause.TOOL_TOO_OLD
    return None


def smartctl_succeeded(document: dict[str, Any]) -> bool:
    status = document.get("smartctl", {})
    return not isinstance(status, dict) or status.get("exit_status") in (0, None)


def clean_text(raw: Any) -> str | None:
    """Stripped text, or None when absent or blank. Single source for hostile hardware strings."""
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def non_negative_int(raw: Any) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def deep_text(document: Any, key: str) -> str | None:
    """First non-blank string under `key`, anywhere in a nested smartctl document."""
    if isinstance(document, dict):
        found = document.get(key)
        if isinstance(found, str) and found.strip():
            return found.strip()
        for nested in document.values():
            deeper = deep_text(nested, key)
            if deeper is not None:
                return deeper
    elif isinstance(document, list):
        for item in document:
            deeper = deep_text(item, key)
            if deeper is not None:
                return deeper
    return None
