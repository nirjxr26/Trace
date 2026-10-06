"""Tribunal tests for STEP 13 surfaces: DTOs, helpers, renderers, and adapter selection."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ValidationError
from trace_core.devices import helpers, renderers, synthetic
from trace_core.devices.dto import DeviceInfoDto, InspectionDto, WpCheckDto
from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT, DeviceService, default_adapter

pytestmark = pytest.mark.unit


def test_no_adapter_never_enumerates_the_working_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Path.cwd()` as a device root presents an ordinary directory as block devices."""
    import trace_core.devices.service as service_module

    monkeypatch.delenv(ENV_DEVICE_ROOT, raising=False)
    monkeypatch.setattr(service_module, "os_adapter", lambda: None)
    with pytest.raises(ValidationError, match=ENV_DEVICE_ROOT):
        default_adapter()


def test_an_explicit_root_is_the_only_file_adapter_root(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch, device_box: Path
) -> None:
    import trace_core.devices.service as service_module

    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.setenv(ENV_DEVICE_ROOT, str(device_box))
    monkeypatch.setattr(service_module, "os_adapter", lambda: None)
    nodes = [device.node for device in DeviceService(session_manager).list_devices()]
    assert nodes == [str(device_box / "disk-a.dd"), str(device_box / "disk-b.dd")]


def test_a_directory_outside_the_root_is_never_enumerated(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import trace_core.devices.service as service_module

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    synthetic.write_disk(outside / "secret.dd", size=256)
    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.setenv(ENV_DEVICE_ROOT, str(root))
    monkeypatch.setattr(service_module, "os_adapter", lambda: None)
    assert DeviceService(session_manager).list_devices() == []


def test_the_os_adapter_takes_precedence_over_an_explicit_root(
    session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch, device_box: Path
) -> None:
    import trace_core.devices.service as service_module
    from trace_core.devices.linux import LinuxDevice

    monkeypatch.setenv(ENV_DEVICE_ROOT, str(device_box))
    monkeypatch.setattr(service_module, "os_adapter", lambda: LinuxDevice())
    adapter = default_adapter()
    assert isinstance(adapter, LinuxDevice)


def test_inspection_dto_carries_no_fabricated_identity(
    session_manager: DatabaseSessionManager, device_file_env: Path
) -> None:
    """An id that matches no persisted row is worse than no id."""
    inspection = helpers.do_inspect(session_manager, str(device_file_env / "disk-a.dd"))
    assert set(inspection.model_dump(mode="json")) == {"device", "fingerprint", "inspected_at"}
    with session_manager.session() as session:
        persisted = session.execute(text("SELECT id FROM device_fingerprints")).scalar()
    assert str(persisted) not in json.dumps(inspection.model_dump(mode="json"))


def test_device_and_fingerprints_survive_a_json_round_trip(
    session_manager: DatabaseSessionManager, device_file_env: Path
) -> None:
    inspection = helpers.do_inspect(session_manager, str(device_file_env / "disk-a.dd"))
    restored = InspectionDto.model_validate(json.loads(inspection.model_dump_json()))
    assert restored == inspection


def test_the_dto_forbids_an_unknown_field(session_manager: DatabaseSessionManager) -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError, match="surprise"):
        DeviceInfoDto(
            **{
                "node": "/dev/sda",
                "kind": "FILE",
                "requires_real_hardware_opt_in": False,
                "surprise": 1,
            }
        )


def test_do_list_rejects_a_bad_kind(session_manager: DatabaseSessionManager, device_file_env: Path) -> None:
    with pytest.raises(ValidationError, match="unknown device kind"):
        helpers.do_list(session_manager, "floppy")


def test_do_list_accepts_all_case_and_padding(session_manager: DatabaseSessionManager, device_file_env: Path) -> None:
    assert len(helpers.do_list(session_manager, "ALL")) == 2
    assert len(helpers.do_list(session_manager, " file ")) == 2


def test_do_check_returns_the_verdict_and_evidence(
    session_manager: DatabaseSessionManager, device_file_env: Path
) -> None:
    check = helpers.do_check(session_manager, str(device_file_env / "disk-a.dd"))
    assert check.verdict.value == "READ_ONLY"
    assert check.platform == "fake"
    assert [c.name for c in check.checks] == ["exists", "open_exclusive", "parent_writable"]


def test_do_check_raises_with_the_writable_verdict(session_manager: DatabaseSessionManager, device_box: Path) -> None:
    from trace_core.devices.domain import WriteProtectionError
    from trace_core.devices.file_device import WRITABLE, FileDevice

    adapter = FileDevice(device_box, behaviour=WRITABLE)
    service = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError) as caught:
        service.check_device(str(device_box / "disk-a.dd"))
    assert caught.value.verdict.value == "WRITABLE"


def test_unknown_verdict_carries_its_cause_into_the_dto(
    session_manager: DatabaseSessionManager, device_box: Path
) -> None:
    from trace_core.devices.file_device import UNKNOWN_PROTECTION, FileDevice
    from trace_core.devices.service import DeviceService as DS

    adapter = FileDevice(device_box, behaviour=UNKNOWN_PROTECTION)
    gate = DS(session_manager, adapter, adapter, adapter).check_device(
        str(device_box / "disk-a.dd"), acknowledge_unverified_source=True
    )
    check = WpCheckDto.from_domain(gate)
    assert check.verdict.value == "UNKNOWN"
    assert check.unknown_cause == "IOCTL_FAILURE"


def test_writable_verdict_style_is_not_the_same_as_read_only() -> None:
    read_only = renderers.verdict_style("READ_ONLY")
    writable = renderers.verdict_style("WRITABLE")
    unknown = renderers.verdict_style("UNKNOWN")
    assert len({read_only[1], writable[1], unknown[1]}) == 3
    assert writable[1] == renderers.VERDICT_STYLES["WRITABLE"][1]


def test_an_unmapped_verdict_is_labelled_not_guessed() -> None:
    label, _ = renderers.verdict_style("SOMETHING_NEW")
    assert label == "SOMETHING NEW"


def test_byte_formatting_covers_zero_and_absent() -> None:
    assert renderers.format_bytes(None) == "-"
    assert renderers.format_bytes(0) == "0 B"
    assert renderers.format_bytes(2048) == "2.0 KB"
    assert renderers.format_bytes(500_107_862_016).endswith(" GB")


def test_renderers_emit_valid_json_for_both_shapes(
    session_manager: DatabaseSessionManager, device_file_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    renderers.render_devices(helpers.do_list(session_manager), output="json")
    listed = json.loads(capsys.readouterr().out)
    assert [d["node"] for d in listed] == [str(device_file_env / "disk-a.dd"), str(device_file_env / "disk-b.dd")]

    renderers.render_inspection(helpers.do_inspect(session_manager, str(device_file_env / "disk-a.dd")), output="json")
    single = json.loads(capsys.readouterr().out)
    assert single["fingerprint"]["serial"].startswith("SYNTH-")

    renderers.render_gate(helpers.do_check(session_manager, str(device_file_env / "disk-a.dd")), output="json")
    gate = json.loads(capsys.readouterr().out)
    assert gate["verdict"] == "READ_ONLY"


def test_renderers_escape_hostile_hardware_strings(
    session_manager: DatabaseSessionManager, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """[D21] a crafted MODEL string must not be interpreted as console markup."""
    root = tmp_path / "root"
    root.mkdir()
    hostile = "[bold red]owned[/]"
    (root / "evil.dd").write_bytes(hostile.encode())
    import os

    os.environ[ENV_ADAPTER] = "file"
    os.environ[ENV_DEVICE_ROOT] = str(root)
    try:
        renderers.render_devices(helpers.do_list(session_manager))
    finally:
        os.environ.pop(ENV_ADAPTER, None)
        os.environ.pop(ENV_DEVICE_ROOT, None)
    assert "[bold red]" not in capsys.readouterr().out
