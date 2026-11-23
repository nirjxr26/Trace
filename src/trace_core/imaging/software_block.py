import platform
from pathlib import Path

from trace_core.imaging.domain import (
    ImagingSourceUnavailableError,
    ImagingSourceUnsupportedError,
    SoftwareWriteBlock,
)

_UDEV_DIRS = (Path("/etc/udev/rules.d"), Path("/run/udev/rules.d"), Path("/usr/lib/udev/rules.d"))
_SETRO_MARKERS = ("blockdev --setro", "wrtblk", "blkroset")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _fstab_auto_enabled(fstab: str) -> bool:
    for raw in fstab.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4:
            return True
        options = fields[3].split(",")
        if "x-systemd.automount" in options:
            return True
        if "noauto" in options:
            continue
        return True
    return False


def _systemd_automount_state() -> str:
    for directory in (
        Path("/etc/systemd/system"),
        Path("/usr/lib/systemd/system"),
        Path("/run/systemd/generator"),
    ):
        try:
            automount_units = tuple(directory.glob("*.automount"))
            mount_units = tuple(directory.glob("*.mount"))
        except OSError:
            return "UNKNOWN"
        if automount_units:
            return "ENABLED"
        for unit in mount_units:
            body = _read_text(unit)
            if body is None:
                return "UNKNOWN"
            if "x-systemd.automount" in body:
                return "ENABLED"
    return "DISABLED"


def _automount_state() -> str:
    fstab = _read_text(Path("/etc/fstab"))
    if fstab is None:
        return "UNKNOWN"
    if _fstab_auto_enabled(fstab):
        return "ENABLED"
    mounts = _read_text(Path("/proc/self/mounts"))
    if mounts is None:
        return "UNKNOWN"
    for raw in mounts.splitlines():
        fields = raw.split()
        if len(fields) > 2 and fields[2] == "autofs":
            return "ENABLED"
    return _systemd_automount_state()


def _mdadm_auto_state(text: str) -> str:
    disabled = False
    for raw in text.splitlines():
        fields = raw.strip().split("#", 1)[0].split()
        if fields and fields[0].upper() == "AUTO":
            if [value.lower() for value in fields[1:]] != ["none"]:
                return "ENABLED"
            disabled = True
    return "DISABLED" if disabled else "UNKNOWN"


def _lvm_auto_state(text: str) -> str:
    found = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("auto_activation_volume_list"):
            continue
        found = True
        if "[]" not in line:
            return "ENABLED"
    return "DISABLED" if found else "ENABLED"


def _live_raid_state() -> str:
    mdstat = _read_text(Path("/proc/mdstat"))
    if mdstat is None:
        return "UNKNOWN"
    for raw in mdstat.splitlines():
        if raw.lstrip().startswith("md") and "[" in raw:
            return "ENABLED"
    try:
        if any(entry.name != "control" for entry in Path("/dev/mapper").iterdir()):
            return "ENABLED"
    except OSError:
        return "UNKNOWN"
    return "DISABLED"


def _raid_lvm_state() -> str:
    mdadm = _read_text(Path("/etc/mdadm/mdadm.conf"))
    lvm = _read_text(Path("/etc/lvm/lvm.conf"))
    if mdadm is None or lvm is None:
        return "UNKNOWN"
    md_state = _mdadm_auto_state(mdadm)
    if md_state != "DISABLED":
        return md_state
    lvm_state = _lvm_auto_state(lvm)
    if lvm_state != "DISABLED":
        return lvm_state
    return _live_raid_state()


def _write_block_rule(body: str) -> bool:
    logical = ""
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#") and not logical:
            continue
        if line.endswith("\\"):
            logical += line[:-1] + " "
            continue
        logical += line
        if 'ACTION=="add"' in logical and "RUN+" in logical and any(m in logical.lower() for m in _SETRO_MARKERS):
            return True
        logical = ""
    return False


def _udev_rules() -> tuple[str, ...]:
    rules: list[str] = []
    for directory in _UDEV_DIRS:
        try:
            entries = tuple(directory.glob("*.rules"))
        except OSError:
            continue
        for entry in entries:
            body = _read_text(entry)
            if body is not None and _write_block_rule(body):
                rules.append(str(entry))
    return tuple(sorted(rules))


def _device_name(node: str) -> str:
    return Path(node).name


def _parent_name(name: str) -> str:
    sys_path = Path("/sys/class/block") / name
    if not sys_path.exists():
        return name
    if (sys_path / "partition").exists():
        try:
            return sys_path.resolve().parent.name
        except OSError:
            return name
    return name


def _device_numbers(name: str) -> tuple[int, int] | None:
    raw = _read_text(Path("/sys/class/block") / name / "dev")
    if raw is None:
        return None
    major, separator, minor = raw.strip().partition(":")
    if not separator:
        return None
    try:
        return int(major), int(minor)
    except ValueError:
        return None


def _mounted(node: str) -> bool | None:
    parent = _parent_name(_device_name(node))
    sys_parent = Path("/sys/block") / parent
    candidates = {_device_name(node), parent}
    try:
        candidates.update(entry.name for entry in sys_parent.glob(f"{parent}[0-9]*"))
        candidates.update(entry.name for entry in sys_parent.glob(f"{parent}p[0-9]*"))
        holders = sys_parent / "holders"
        if holders.exists():
            candidates.update(entry.name for entry in holders.iterdir())
    except OSError:
        return None
    wanted = set()
    for name in candidates:
        numbers = _device_numbers(name)
        if numbers is not None:
            wanted.add(numbers)
    if not wanted:
        return None
    mounts = _read_text(Path("/proc/self/mountinfo"))
    if mounts is None:
        return None
    for raw in mounts.splitlines():
        fields = raw.split()
        if len(fields) < 4:
            return None
        major, _, minor = fields[2].partition(":")
        try:
            if (int(major), int(minor)) in wanted:
                return True
        except ValueError:
            return None
    return False


def _block_device_read_only(node: str) -> bool | None:
    parent = _parent_name(_device_name(node))
    ro = _read_text(Path("/sys/block") / parent / "ro")
    if ro is None or ro.strip() not in {"0", "1"}:
        return None
    return ro.strip() == "1"


def preflight_software_write_block(node: str) -> SoftwareWriteBlock:
    if platform.system() != "Linux":
        raise ImagingSourceUnsupportedError("Software write blocking is available only on Linux.")
    kernel = platform.release().strip()
    if not kernel:
        raise ImagingSourceUnavailableError("The Linux kernel version could not be determined.")
    automount = _automount_state()
    raid_lvm = _raid_lvm_state()
    udev = _udev_rules()
    mounted = _mounted(node)
    read_only = _block_device_read_only(node)
    if automount != "DISABLED":
        raise ImagingSourceUnavailableError(
            "Automount preflight is unknown or enabled; software write blocking refused."
        )
    if raid_lvm != "DISABLED":
        raise ImagingSourceUnavailableError(
            "RAID/LVM auto-activation preflight is unknown or enabled; software write blocking refused."
        )
    if not udev:
        raise ImagingSourceUnavailableError(
            "No kernel write-block udev rule was found; software write blocking refused."
        )
    if mounted is None or mounted:
        raise ImagingSourceUnavailableError(
            "The source mount state could not be cleared; software write blocking refused."
        )
    if read_only is not True:
        raise ImagingSourceUnavailableError(
            "The whole block device is not kernel read-only; software write blocking refused."
        )
    return SoftwareWriteBlock(
        kernel_version=kernel,
        automount=automount,
        raid_lvm=raid_lvm,
        udev_rules=udev,
        source_mounted=mounted,
        block_device_read_only=read_only,
        io_path="O_RDONLY source read path; no SG_IO or SMART commands during acquisition",
        validation="OPERATOR_VALIDATION_REQUIRED",
    )
