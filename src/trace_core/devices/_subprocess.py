"""Bounded subprocess and sysfs helpers for the OS adapters [D21].

Every helper here is semantic (`lsblk_json`, `run_capped`, never a generic
`run_command`) and every one takes an argv list, `shell=False`, a timeout and a
hard stdout byte cap. A hung or flood-emitting helper degrades to UNKNOWN rather
than hanging or exhausting memory. The gate probe never calls these.
"""

import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Final

from trace_core.devices.domain import DeviceInterface, UnknownCause

STDOUT_CAP: Final[int] = 1 << 20
TIMEOUT_SECONDS: Final[int] = 15
READ_CHUNK: Final[int] = 1 << 16
TERMINATE_GRACE: Final[int] = 5
VERSION_TIMEOUT: Final[int] = 5
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


def _start(argv: list[str]) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise HelperFailure(UnknownCause.TOOL_MISSING, f"{argv[0]} could not be executed") from exc


def run_capped(argv: list[str], *, timeout: int = TIMEOUT_SECONDS, cap: int = STDOUT_CAP) -> bytes:
    """Run a fixed argv list and return stdout, refusing anything over `cap` bytes.

    The cap is enforced *while reading*, not after: `subprocess.run` buffers the whole
    stream before the caller sees it, so a post-hoc length check rejects the result only
    after the memory has already been spent. A tool that floods stdout would exhaust the
    machine mid-acquisition. Reading incrementally and abandoning at `cap` bounds what is
    ever held.

    stderr is discarded rather than buffered: a hostile tool can flood it, and the caller
    has no use for it once a non-zero exit has already become a named cause. stdin is
    closed so a tool that reads it cannot block until the timeout.
    """
    proc = _start(argv)

    chunks: list[bytes] = []
    held = 0
    overflow = False
    timed_out = threading.Event()

    def _on_timeout() -> None:
        timed_out.set()
        _terminate(proc)

    # A read on a pipe blocks until data or EOF, so a child that stalls mid-stream would
    # hang here indefinitely - the exact failure the timeout exists to prevent. Killing
    # the child is what unblocks the read; the flag records why it ended.
    stream = proc.stdout
    if stream is None:
        _terminate(proc)
        raise HelperFailure(UnknownCause.TOOL_MISSING, f"{argv[0]} produced no readable output")

    timer = threading.Timer(timeout, _on_timeout)
    timer.daemon = True
    timer.start()
    try:
        while True:
            chunk = stream.read(READ_CHUNK)
            if not chunk:
                break
            held += len(chunk)
            if held > cap:
                overflow = True
                break
            chunks.append(chunk)
    except (OSError, ValueError) as exc:
        _terminate(proc)
        raise HelperFailure(UnknownCause.TOOL_MISSING, f"{argv[0]} could not be read") from exc
    finally:
        timer.cancel()
        stream.close()

    if timed_out.is_set():
        raise HelperFailure(UnknownCause.SMARTCTL_TIMEOUT, f"{argv[0]} timed out after {timeout}s")
    if overflow:
        _terminate(proc)
        raise HelperFailure(UnknownCause.SMARTCTL_MALFORMED, f"{argv[0]} stdout exceeded {cap} bytes and was discarded")

    proc.wait(timeout=TERMINATE_GRACE)
    if proc.returncode != 0:
        raise HelperFailure(UnknownCause.SMARTCTL_MALFORMED, f"{argv[0]} exited {proc.returncode}")
    return b"".join(chunks)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Kill and reap, so an abandoned flood leaves no child behind holding a pipe."""
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=TERMINATE_GRACE)
    except subprocess.TimeoutExpired:
        pass


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
    """One `lsblk -J` call. Stdout is capped before parse [D21].

    The cause names the tool that actually failed. `decode_json` reports
    SMARTCTL_MALFORMED for any unparseable JSON, so an lsblk problem was recorded in the
    ledger as a SMART problem - `UnknownCause` has no lsblk member, and the wrong tool
    named to an examiner is worse than none.
    """
    raw = run_capped(
        ["lsblk", "-J", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN,ROTA,RO,WWN", "--bytes"],
        cap=cap,
    )
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise HelperFailure(UnknownCause.LSBLK_MALFORMED, "lsblk emitted unparseable JSON") from exc


def parse_version(raw: bytes) -> tuple[int, ...] | None:
    """The dotted version from `smartctl --version` output, or None if there is none.

    Distinguishes "printed nothing parseable" from "printed a version": returning None
    for both is what let `smartctl_readiness` report TOOL_MISSING for a tool that is
    installed and whose version simply could not be read - telling an examiner to install
    software they already have.
    """
    first = raw.decode("utf-8", errors="replace").splitlines()[:1]
    if not first or not first[0].strip():
        return None
    numbers = first[0].replace(",", ".").split()
    version = next((part for part in numbers if part[:1].isdigit()), "")
    return tuple(int(part) for part in version.split(".") if part.isdigit()) or None


_READINESS_CACHE: dict[str, tuple[Any, UnknownCause | None]] = {}


def _readiness_key() -> str:
    """Cache key for a readiness probe: the resolved executable path."""
    return shutil.which("smartctl") or "smartctl"


def smartctl_readiness() -> UnknownCause | None:
    """None when `smartctl -j` is usable, else the cause to record.

    Single source for the [D22] floor so both OS adapters degrade identically: absent is
    TOOL_MISSING, present-but-too-old is TOOL_TOO_OLD, and present-but-unreadable is
    TOOL_VERSION_UNREADABLE rather than a false TOOL_MISSING. `-j` needs >= 5.16.

    Memoised per resolved executable path. It was called on every inspection, so each
    device cost an extra `smartctl --version` spawn, and on a hung tool up to the timeout
    again per device - the previous claim that the version is read once was not true.

    The entry holds the runner it was produced with and only answers for that same
    object. Keying on `id(run_capped)` instead was unsound: an address is reused once its
    function is collected, so a later probe could be served a stranger's answer.
    """
    key = _readiness_key()
    cached = _READINESS_CACHE.get(key)
    if cached is None or cached[0] is not run_capped:
        _READINESS_CACHE[key] = (run_capped, _readiness_now())
    return _READINESS_CACHE[key][1]


def _readiness_now() -> UnknownCause | None:
    try:
        raw = run_capped(["smartctl", "--version"], timeout=VERSION_TIMEOUT)
    except HelperFailure as failure:
        return failure.cause if failure.cause is UnknownCause.SMARTCTL_TIMEOUT else UnknownCause.TOOL_MISSING
    parsed = parse_version(raw)
    if parsed is None:
        return UnknownCause.TOOL_VERSION_UNREADABLE
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
