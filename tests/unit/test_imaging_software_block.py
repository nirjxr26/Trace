from pathlib import Path

import pytest

from trace_core.core.clock import now_utc
from trace_core.imaging import software_block
from trace_core.imaging.domain import (
    ImagingSource,
    ImagingSourceKind,
    ImagingSourceUnavailableError,
    ImagingSourceUnsupportedError,
    SoftwareWriteBlock,
)
from trace_core.imaging.service import ImagingService
from trace_core.tui.app import TraceApp
from trace_core.tui.screens.imaging import ImagingProgressModal

pytestmark = pytest.mark.unit


def _clean_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(software_block.platform, "system", lambda: "Linux")
    monkeypatch.setattr(software_block.platform, "release", lambda: "6.8.0-test")
    monkeypatch.setattr(software_block, "_automount_state", lambda: "DISABLED")
    monkeypatch.setattr(software_block, "_raid_lvm_state", lambda: "DISABLED")
    monkeypatch.setattr(software_block, "_udev_rules", lambda: ("/etc/udev/rules.d/10-wrtblk.rules",))
    monkeypatch.setattr(software_block, "_mounted", lambda node: False)
    monkeypatch.setattr(software_block, "_block_device_read_only", lambda node: True)


def test_software_write_block_is_linux_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(software_block.platform, "system", lambda: "Windows")
    with pytest.raises(ImagingSourceUnsupportedError):
        software_block.preflight_software_write_block("/dev/sdb")


def test_software_write_block_passes_clean_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_preflight(monkeypatch)
    result = software_block.preflight_software_write_block("/dev/sdb")
    assert result.label == "SOFTWARE-ONLY · NOT EVIDENTIARY"
    assert result.kernel_version == "6.8.0-test"
    assert result.automount == "DISABLED"
    assert result.raid_lvm == "DISABLED"
    assert result.source_mounted is False
    assert result.block_device_read_only is True
    assert "O_RDONLY" in result.io_path


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("_automount_state", "UNKNOWN"),
        ("_raid_lvm_state", "ENABLED"),
        ("_udev_rules", ()),
        ("_mounted", True),
        ("_block_device_read_only", False),
    ],
)
def test_software_write_block_fails_closed(monkeypatch: pytest.MonkeyPatch, field: str, value: object) -> None:
    _clean_preflight(monkeypatch)
    monkeypatch.setattr(software_block, field, lambda *args, **kwargs: value)
    with pytest.raises(ImagingSourceUnavailableError):
        software_block.preflight_software_write_block("/dev/sdb")


def test_generic_udev_rule_is_not_write_block_evidence() -> None:
    generic = 'SUBSYSTEM=="block", ACTION=="add|remove", RUN+="/usr/bin/logger disk"\n'
    specific = 'SUBSYSTEM=="block", ACTION=="add", RUN+="/usr/local/bin/wrtblk $env{DEVNAME}"\n'
    assert software_block._write_block_rule(generic) is False
    assert software_block._write_block_rule(specific) is True


def test_fstab_defaults_enables_automount() -> None:
    assert software_block._fstab_auto_enabled("/dev/sda1 / ext4 defaults 0 1\n") is True
    assert software_block._fstab_auto_enabled("/dev/sda1 / ext4 rw 0 1\n") is True
    assert software_block._fstab_auto_enabled("/dev/sda1 / ext4 noauto 0 1\n") is False


def test_mdadm_without_explicit_auto_none_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def read(path: Path) -> str | None:
        if "mdadm.conf" in str(path):
            return "# AUTO none\n"
        if "lvm.conf" in str(path):
            return "auto_activation_volume_list = []\n"
        return None

    monkeypatch.setattr(software_block, "_read_text", read)
    assert software_block._raid_lvm_state() == "UNKNOWN"


def test_systemd_automount_in_fstab_is_detected() -> None:
    entry = "/dev/sdb1 /mnt ext4 noauto,x-systemd.automount 0 0\n"
    assert software_block._fstab_auto_enabled(entry) is True


def test_lvm_auto_activation_undefined_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def read(path: Path) -> str | None:
        if "mdadm.conf" in str(path):
            return "AUTO none\n"
        if "lvm.conf" in str(path):
            return "# auto_activation_volume_list is unset\n"
        if "mdstat" in str(path):
            return "Personalities :\n"
        return None

    monkeypatch.setattr(software_block, "_read_text", read)
    monkeypatch.setattr(Path, "iterdir", lambda self: iter([]))
    assert software_block._raid_lvm_state() == "ENABLED"


def test_mapper_control_is_not_a_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    mdadm = "AUTO none\n"
    lvm = "auto_activation_volume_list = []\n"
    mdstat = "Personalities :\n"

    def read(path: Path) -> str | None:
        if "mdadm.conf" in str(path):
            return mdadm
        if "lvm.conf" in str(path):
            return lvm
        if "mdstat" in str(path):
            return mdstat
        return None

    monkeypatch.setattr(software_block, "_read_text", read)
    monkeypatch.setattr(Path, "iterdir", lambda self: iter([Path("/dev/mapper/control")]))
    assert software_block._raid_lvm_state() == "DISABLED"


def test_udev_signals_must_be_on_one_rule() -> None:
    split = 'ACTION=="add", SUBSYSTEM=="block"\nRUN+="/usr/local/bin/wrtblk %k"\n'
    joined = 'ACTION=="add", SUBSYSTEM=="block", \\\n  RUN+="/usr/local/bin/wrtblk %k"\n'
    assert software_block._write_block_rule(split) is False
    assert software_block._write_block_rule(joined) is True


def test_mounted_detects_nvme_partition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(software_block, "_parent_name", lambda name: "nvme0n1")
    monkeypatch.setattr(Path, "glob", lambda self, pattern: [Path("/dev/nvme0n1p1")] if "p[0-9]" in pattern else [])
    monkeypatch.setattr(software_block, "_device_numbers", lambda name: (259, 1) if name == "nvme0n1p1" else (259, 0))
    monkeypatch.setattr(
        software_block,
        "_read_text",
        lambda path: "36 24 259:1 / /mnt rw\n" if path.name == "mountinfo" else None,
    )
    assert software_block._mounted("/dev/nvme0n1") is True


def _software_source() -> ImagingSource:
    block = SoftwareWriteBlock(
        kernel_version="6.8.0-test",
        automount="DISABLED",
        raid_lvm="DISABLED",
        udev_rules=("/etc/udev/rules.d/10-wrtblk.rules",),
        source_mounted=False,
        block_device_read_only=True,
        io_path="O_RDONLY source read path; no SG_IO or SMART commands during acquisition",
        validation="OPERATOR_VALIDATION_REQUIRED",
    )
    return ImagingSource(
        node="/dev/sdb",
        kind=ImagingSourceKind.OS,
        serial="SERIAL",
        model="MODEL",
        size_bytes=1024,
        protection="READ_ONLY",
        adapter="linux",
        synthetic=False,
        inspected_at=now_utc(),
        software_write_block=block,
    )


def test_resume_with_mismatched_checkpoint_evidence_class_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "trace_core.imaging.service.read_checkpoint", lambda path: {"evidence_class": "HARDWARE_WRITE_BLOCK"}
    )
    source = _software_source()
    with pytest.raises(ImagingSourceUnavailableError):
        ImagingService._require_evidence_class_match(source, (None, None, Path("checkpoint")))


def test_evidence_class_requires_hardware_attestation() -> None:
    source = ImagingSource(
        node="/dev/sdb",
        kind=ImagingSourceKind.OS,
        serial="SERIAL",
        model="MODEL",
        size_bytes=1024,
        protection="READ_ONLY",
        adapter="linux",
        synthetic=False,
        inspected_at=now_utc(),
    )
    assert ImagingService._evidence_class(source) == "UNVERIFIED_WRITE_PROTECTION"
    attested = source.model_copy(update={"hardware_write_block": True})
    assert ImagingService._evidence_class(attested) == "HARDWARE_WRITE_BLOCK"


def test_start_details_carry_software_only_label() -> None:
    details = ImagingService._start_details(_software_source(), (), resumed=False)
    assert details["evidence_class"] == "SOFTWARE_ONLY"
    block = details["software_write_block"]
    assert isinstance(block, dict)
    assert block["label"] == "SOFTWARE-ONLY · NOT EVIDENTIARY"


@pytest.mark.anyio
async def test_progress_popup_shows_software_only_label() -> None:
    app = TraceApp()
    async with app.run_test(size=(90, 24)) as pilot:
        app.push_screen(ImagingProgressModal(preview=True, software_only=True))
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, ImagingProgressModal)
        label = str(modal.query_one("#progress-software").render())
        assert "SOFTWARE-ONLY · NOT EVIDENTIARY" in label
