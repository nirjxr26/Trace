"""Tribunal tests for device persistence and the service [D3], [D29], [D31]."""

import inspect
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, select, text

from trace_core.devices import file_device, synthetic
from trace_core.devices.domain import (
    MAX_DEVICE_STRING,
    MAX_NODE_LENGTH,
    DeviceNotFoundError,
    ObservedSerial,
    WpVerdict,
    WriteProtectionError,
)
from trace_core.devices.repository import SqlAlchemyDeviceRepository
from trace_core.devices.service import DeviceService

pytestmark = pytest.mark.unit


@pytest.fixture
def box(tmp_path: Path) -> Path:
    synthetic.write_disk(tmp_path / "disk-a.dd", size=2048)
    return tmp_path


@pytest.fixture
def svc(session_manager, box: Path):  # type: ignore[no-untyped-def]
    adapter = file_device.FileDevice(box)
    return DeviceService(session_manager, adapter, adapter, adapter)


def test_observation_is_appended_and_reads_latest(session_manager, svc, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    node = str(box / "disk-a.dd")
    first = svc.inspect_device(node)
    second = svc.inspect_device(node)
    assert first.fingerprint.serial == second.fingerprint.serial

    with session_manager.session() as session:
        repo = SqlAlchemyDeviceRepository(session)
        rows = repo.history_for(first.fingerprint.serial.value, limit=10)
        latest = repo.latest_for(first.fingerprint.serial.value)
    assert len(rows) == 2, "a re-inspection appends; it never upserts"
    assert latest is not None
    assert latest.serial == first.fingerprint.serial


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_history_for_never_widens_the_query_on_a_hostile_limit(session_manager, svc, box: Path, limit: int) -> None:
    """A negative LIMIT is an error on PostgreSQL, not an unbounded read."""
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    node = str(box / "disk-a.dd")
    svc.inspect_device(node)
    serial = svc.inspect_device(node).fingerprint.serial.value
    with session_manager.session() as session:
        rows = SqlAlchemyDeviceRepository(session).history_for(serial, limit=limit)
    assert rows == [], "a non-positive limit must yield no rows, never an unbounded read"


def test_update_paths_are_refused(session_manager) -> None:
    from trace_core.devices.models import DeviceFingerprintModel

    with session_manager.session() as session:
        repo = SqlAlchemyDeviceRepository(session)
        model = DeviceFingerprintModel()
        with pytest.raises(NotImplementedError, match="append-only"):
            repo._update_model(model, None)  # type: ignore[arg-type]


def test_the_repository_implementation_matches_its_protocol() -> None:
    from trace_core.devices.repository import DeviceRepository

    for name in ("save_observation", "latest_for", "history_for"):
        assert inspect.signature(getattr(SqlAlchemyDeviceRepository, name)) == inspect.signature(
            getattr(DeviceRepository, name)
        ), f"{name} drifted from the DeviceRepository contract"


def test_observation_survives_with_its_actor(session_manager, svc, box: Path) -> None:
    from trace_core.core.operators import process_session_id
    from trace_core.devices.models import DeviceFingerprintModel

    _ = process_session_id()
    svc.inspect_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        rows = session.scalars(select(DeviceFingerprintModel)).all()
    assert rows
    assert all(r.inspected_by for r in rows)


def test_unknown_node_is_refused_before_any_capture(svc, tmp_path: Path) -> None:
    with pytest.raises(DeviceNotFoundError):
        svc.inspect_device(str(tmp_path / "not-enumerated.dd"))


def test_traversal_string_cannot_resolve(svc, box: Path) -> None:
    with pytest.raises(DeviceNotFoundError):
        svc.inspect_device("../../../etc/passwd")


def _actions(session_manager) -> list[str]:
    with session_manager.session() as session:
        return [row[0] for row in session.execute(text("SELECT action FROM audit_events ORDER BY seq")).fetchall()]


def _fingerprints(session_manager) -> int:
    with session_manager.session() as session:
        return session.execute(text("SELECT count(*) FROM device_fingerprints")).scalar()


def test_inspect_writes_a_device_ledger_row(session_manager, svc, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    svc.inspect_device(str(box / "disk-a.dd"))
    assert _actions(session_manager) == ["DEVICE_INSPECTED"]


def test_inspect_and_check_write_two_rows_for_two_operations(session_manager, svc, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    node = str(box / "disk-a.dd")
    svc.inspect_device(node)
    svc.check_device(node)
    assert _actions(session_manager) == ["DEVICE_INSPECTED", "DEVICE_GATE_CHECKED"]


def test_every_device_row_has_the_device_subject(session_manager, svc, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    node = str(box / "disk-a.dd")
    svc.inspect_device(node)
    svc.check_device(node)
    with session_manager.session() as session:
        subjects = {
            row[0] for row in session.execute(text("SELECT DISTINCT subject_type FROM audit_events")).fetchall()
        }
    assert subjects == {"device"}


def test_device_rows_address_the_device_by_its_observed_serial(session_manager, svc, box: Path) -> None:
    from trace_core.audit.models import AuditEventModel
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    node = str(box / "disk-a.dd")
    serial = svc.inspect_device(node).fingerprint.serial.value
    svc.check_device(node)
    with session_manager.session() as session:
        rows = session.scalars(select(AuditEventModel).order_by(AuditEventModel.seq)).all()
    assert [r.subject_type for r in rows] == ["device", "device"]
    assert [r.subject_device_serial for r in rows] == [serial, serial]


def test_an_acknowledged_override_addresses_the_device_by_its_serial(session_manager, box: Path) -> None:
    from trace_core.audit.models import AuditEventModel
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    node = str(box / "disk-a.dd")
    serial = svc.inspect_device(node).fingerprint.serial.value
    svc.check_device(node, acknowledge_unverified_source=True)
    with session_manager.session() as session:
        rows = session.scalars(select(AuditEventModel).order_by(AuditEventModel.seq)).all()
    assert [r.action for r in rows] == ["DEVICE_INSPECTED", "DEVICE_GATE_CHECKED", "DEVICE_OVERRIDE"]
    assert [r.subject_device_serial for r in rows] == [serial, serial, serial]


def test_a_simulated_gate_is_marked_in_the_ledger_payload(session_manager, svc, box: Path) -> None:
    import json

    from trace_core.audit.models import AuditEventModel
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    svc.check_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        row = session.scalars(select(AuditEventModel).where(AuditEventModel.action == "DEVICE_GATE_CHECKED")).first()
    assert row is not None
    assert json.loads(row.payload_json)["details"]["simulated"] is True


def test_a_case_link_row_stays_a_case_subject(session_manager, svc, box: Path) -> None:
    from trace_core.audit.models import AuditEventModel
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    case = CaseService(session_manager).create_case(CaseCreateDto(title="Link", lead_examiner="Ex"))
    svc.link_device(str(box / "disk-a.dd"), case.number, label="bag-1")
    with session_manager.session() as session:
        row = session.scalars(select(AuditEventModel).order_by(AuditEventModel.seq)).all()[-1]
    assert row.action == "DEVICE_LINKED"
    assert row.subject_type == "case"
    assert row.subject_case_number == case.number
    assert row.subject_device_serial is None


def test_an_explicit_list_records_one_recognition_row(session_manager, svc, box: Path) -> None:
    import json

    from trace_core.audit.models import AuditEventModel

    found = svc.list_devices("all", audit_recognition=True)
    assert len(found) == 1
    with session_manager.session() as session:
        rows = session.scalars(select(AuditEventModel).order_by(AuditEventModel.seq)).all()
    assert [r.action for r in rows] == ["DEVICE_RECOGNIZED"]
    assert rows[0].subject_type == "system"
    assert rows[0].subject_case_number is None
    assert rows[0].subject_device_serial is None
    details = json.loads(rows[0].payload_json)["details"]
    assert details["kind"] == "all"
    assert details["count"] == 1
    assert [(d["node"], d["kind"], d["serial"]) for d in details["devices"]] == [(str(box / "disk-a.dd"), "FILE", None)]


def test_a_plain_list_writes_no_ledger_row(session_manager, svc, box: Path, monkeypatch) -> None:
    from trace_core.audit.models import AuditEventModel
    from trace_core.devices import helpers as device_helpers
    from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT

    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.setenv(ENV_DEVICE_ROOT, str(box))
    assert len(svc.list_devices("all")) == 1
    assert len(device_helpers.do_list(session_manager, "all")) == 1
    with session_manager.session() as session:
        assert session.scalars(select(AuditEventModel)).all() == []


def test_inspect_row_carries_the_observed_identity(session_manager, svc, box: Path) -> None:
    from trace_core.audit.events import parse_details
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    svc.inspect_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        payload = session.execute(text("SELECT payload_json FROM audit_events WHERE seq = 1")).scalar()
    details = parse_details(payload)
    assert details is not None
    assert details["serial"].startswith("SYNTH-")
    assert details["interface"] == "UNKNOWN"
    assert details["source"] == "synthetic"
    assert details["capacity_bytes"] == 2048


def test_the_stored_verdict_is_readable_again(session_manager, box: Path) -> None:
    """`save_observation` writes the verdict, cause and evidence; nothing read them back.

    `_to_domain` returns a `DeviceFingerprint`, which has no field for any of them, so the
    gate outcome - the fact that decides whether acquisition may proceed - was write-only.
    """
    from trace_core.devices.repository import SqlAlchemyDeviceRepository

    node = str(box / "disk-a.dd")
    gate = DeviceService(session_manager, *(lambda a: (a, a, a))(file_device.FileDevice(box))).check_device(node)
    serial = gate.evidence.checks and _serial_for(box)

    with session_manager.session() as session:
        repo = SqlAlchemyDeviceRepository(session)
        stored = repo.latest_observation(str(serial))
    assert stored is not None
    assert stored.verdict is WpVerdict.READ_ONLY
    assert stored.unknown_cause is None
    assert stored.evidence is not None
    assert {c.name for c in stored.evidence.checks} >= {"exists", "parent_writable"}
    assert stored.node == node
    assert stored.inspected_by


def _serial_for(box: Path) -> str:
    from trace_core.core.fs import sha256_file
    from trace_core.devices import synthetic

    return synthetic.synthetic_serial(sha256_file(box / "disk-a.dd"))


def test_observation_history_keeps_each_verdict(session_manager, box: Path) -> None:
    from trace_core.devices.repository import SqlAlchemyDeviceRepository

    adapter = file_device.FileDevice(box)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    node = str(box / "disk-a.dd")
    svc.check_device(node)

    # A refused writable source persists no observation by design, so drive the second row
    # through the repository directly rather than expecting a refused gate to store one.
    writable_adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    writable_device = writable_adapter.list_block_devices()[0]
    writable_inspection = writable_adapter.inspect(writable_device)
    with session_manager.session() as session:
        SqlAlchemyDeviceRepository(session).save_observation(
            writable_inspection, "tester", writable_adapter.verify(writable_device)
        )
        session.commit()

    serial = _serial_for(box)
    with session_manager.session() as session:
        rows = SqlAlchemyDeviceRepository(session).observation_history(serial)
    assert len(rows) == 2
    assert {r.verdict for r in rows} == {WpVerdict.WRITABLE, WpVerdict.READ_ONLY}


def test_a_widened_synthetic_identity_still_reads_the_legacy_width(session_manager, box: Path) -> None:
    adapter = file_device.FileDevice(box)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    node = str(box / "disk-a.dd")
    svc.check_device(node)

    widened = _serial_for(box)
    legacy = f"SYNTH-{widened.removeprefix('SYNTH-')[:16]}"
    inspection = adapter.inspect(adapter.list_block_devices()[0])
    forged = inspection.model_copy(
        update={"fingerprint": inspection.fingerprint.model_copy(update={"serial": ObservedSerial(value=legacy)})}
    )
    with session_manager.session() as session:
        SqlAlchemyDeviceRepository(session).save_observation(forged, "tester")
        session.commit()

    with session_manager.session() as session:
        repo = SqlAlchemyDeviceRepository(session)
        assert {row.fingerprint.serial.value for row in repo.observation_history(widened)} == {widened, legacy}
        assert [row.fingerprint.serial.value for row in repo.observation_history(legacy)] == [legacy]


def test_gate_row_carries_the_verdict_and_its_evidence(session_manager, svc, box: Path) -> None:
    from trace_core.audit.events import parse_details
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    svc.check_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        payload = session.execute(text("SELECT payload_json FROM audit_events ORDER BY seq DESC LIMIT 1")).scalar()
    details = parse_details(payload)
    assert details is not None
    assert details["verdict"] == "READ_ONLY"
    assert details["unknown_cause"] is None
    assert any(c["name"] == "open_exclusive" for c in details["evidence"]["checks"])


def test_an_acknowledged_unknown_records_the_override(session_manager, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True)
    assert _actions(session_manager) == ["DEVICE_GATE_CHECKED", "DEVICE_OVERRIDE"]


def test_a_refused_writable_source_is_still_ledgered(session_manager, box: Path) -> None:
    """[D2] an unrecorded attempt to image a writable source is the gap the check exists to close."""
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError):
        svc.check_device(str(box / "disk-a.dd"))
    assert _actions(session_manager) == ["DEVICE_GATE_CHECKED"]


def test_acknowledgement_cannot_buy_a_writable_source(session_manager, box: Path) -> None:
    """[§12.2] WRITABLE is not overridable; the acknowledgement only ever clears UNKNOWN."""
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError):
        svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True, override_reason="because")
    assert _actions(session_manager) == ["DEVICE_GATE_CHECKED"]
    assert _fingerprints(session_manager) == 0


def test_a_boot_disk_is_refused_even_with_the_acknowledgement(session_manager, box: Path) -> None:
    from trace_core.core.clock import now_utc
    from trace_core.core.operators import process_session_id
    from trace_core.devices.domain import (
        CHECK_BOOT_DISK,
        BootDiskRefusalError,
        GateCheck,
        ProtectionCheck,
        ProtectionEvidence,
    )

    _ = process_session_id()
    adapter = file_device.FileDevice(box)

    class _BootProbe:
        def verify(self, device):  # type: ignore[no-untyped-def]
            return GateCheck(
                verdict=WpVerdict.READ_ONLY,
                evidence=ProtectionEvidence(
                    platform="fake",
                    checks=(
                        ProtectionCheck(name="exists", result="True"),
                        ProtectionCheck(name=CHECK_BOOT_DISK, result="True", detail="hosts C:"),
                        ProtectionCheck(name="sysfs_ro", result="True"),
                    ),
                    adapter_version="stub",
                    checked_at=now_utc(),
                ),
                checked_at=now_utc(),
            )

    svc = DeviceService(session_manager, adapter, adapter, _BootProbe())
    with pytest.raises(BootDiskRefusalError):
        svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True, override_reason="because")
    assert _actions(session_manager) == ["DEVICE_GATE_CHECKED"]
    assert _fingerprints(session_manager) == 0


def test_the_boot_refusal_is_taken_before_a_writable_verdict() -> None:
    from trace_core.core.clock import now_utc
    from trace_core.devices.domain import (
        CHECK_BOOT_DISK,
        BootDiskRefusalError,
        GateCheck,
        ProtectionCheck,
        ProtectionEvidence,
    )
    from trace_core.devices.service import _refusal_for

    evidence = ProtectionEvidence(
        platform="windows",
        checks=(
            ProtectionCheck(name="exists", result="True"),
            ProtectionCheck(name=CHECK_BOOT_DISK, result="True", detail="hosts C:"),
            ProtectionCheck(name="ioctl_is_writable", result="True"),
        ),
        adapter_version="stub",
        checked_at=now_utc(),
    )
    gate = GateCheck(verdict=WpVerdict.WRITABLE, evidence=evidence, checked_at=now_utc())
    refusal = _refusal_for(gate, True, r"\\.\PhysicalDrive0")
    assert isinstance(refusal, BootDiskRefusalError)
    assert "boot disk" in str(refusal)


def test_the_override_event_preserves_the_pre_override_verdict_and_cause(session_manager, box: Path) -> None:
    """[D19], [§12.2] the ledger records what was overridden, not what it became."""
    from trace_core.audit.events import parse_details
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True, override_reason="custody handoff")
    with session_manager.session() as session:
        rows = session.execute(
            text("SELECT action, payload_json FROM audit_events WHERE action = 'DEVICE_OVERRIDE'")
        ).all()
    assert len(rows) == 1
    details = parse_details(rows[0][1])
    assert details is not None
    assert details["original_verdict"] == "UNKNOWN"
    assert details["original_unknown_cause"] == "IOCTL_FAILURE"
    assert details["reason"] == "custody handoff"
    assert details["authorized_by"]
    assert details["node"]


def test_an_override_without_a_stated_reason_still_records_one(session_manager, box: Path) -> None:
    """The key is mandatory: an override with a blank reason is still an accountable event."""
    from trace_core.audit.events import parse_details
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True, override_reason="   ")
    with session_manager.session() as session:
        payload = session.execute(
            text("SELECT payload_json FROM audit_events WHERE action = 'DEVICE_OVERRIDE'")
        ).scalar()
    details = parse_details(payload)
    assert details is not None
    assert details["reason"].strip()


def test_every_device_ledger_row_is_written_through_a_before_commit_hook(
    session_manager, box: Path, monkeypatch
) -> None:
    """[§14.5] mandatory forensic rows go in via `UnitOfWork.before_commit`, not ad hoc."""
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True)
    svc.inspect_device(str(box / "disk-a.dd"))

    registered: list[int] = []
    original = DeviceService._ledger_hook

    def _counting(self, build, actor):  # type: ignore[no-untyped-def]
        registered.append(1)
        return original(self, build, actor)

    monkeypatch.setattr(DeviceService, "_ledger_hook", _counting)
    svc.inspect_device(str(box / "disk-a.dd"))
    svc.check_device(str(box / "disk-a.dd"), acknowledge_unverified_source=True)
    assert len(registered) == 3, "inspect writes one row; the acknowledged check writes gate + override"


def test_a_refused_check_persists_no_observation(session_manager, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError):
        svc.check_device(str(box / "disk-a.dd"))
    assert _fingerprints(session_manager) == 0


def test_an_unacknowledged_unknown_is_refused_and_ledgered(session_manager, box: Path) -> None:
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError):
        svc.check_device(str(box / "disk-a.dd"))
    assert _actions(session_manager) == ["DEVICE_GATE_CHECKED"]
    assert "DEVICE_OVERRIDE" not in _actions(session_manager)


def test_the_ledger_row_is_written_before_the_refusal_propagates(session_manager, box: Path) -> None:
    from trace_core.audit.events import parse_details
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError):
        svc.check_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        payload = session.execute(text("SELECT payload_json FROM audit_events")).scalar()
    details = parse_details(payload)
    assert details is not None
    assert details["verdict"] == "WRITABLE"


def test_a_failed_audit_rolls_the_observation_back(session_manager, svc, box: Path, monkeypatch) -> None:
    """[§14.5] an unledgered fingerprint must never exist."""
    from trace_core.core.errors import ApplicationError
    from trace_core.core.operators import process_session_id

    _ = process_session_id()

    def _refuse(*_args, **_kwargs):
        raise ApplicationError("ledger unavailable")

    monkeypatch.setattr("trace_core.audit.service.AuditService.record", _refuse)
    with pytest.raises(ApplicationError):
        svc.inspect_device(str(box / "disk-a.dd"))
    assert _fingerprints(session_manager) == 0


def test_device_rows_sit_in_the_signed_chain(session_manager, svc, box: Path) -> None:
    """[D14], [§14.7] a device event must verify in the same chain as a case event."""
    from sqlalchemy import select

    from trace_core.audit.models import AuditEventModel
    from trace_core.audit.verifier import verify_rows
    from trace_core.core.operators import process_session_id

    _ = process_session_id()
    node = str(box / "disk-a.dd")
    svc.inspect_device(node)
    svc.check_device(node)
    with session_manager.session() as session:
        rows = list(session.scalars(select(AuditEventModel).order_by(AuditEventModel.seq)))
    assert len(rows) == 2
    result = verify_rows(rows)
    assert result.is_valid is True, result.mismatch_type
    assert result.events_verified == 2
    assert {row.subject_type for row in rows} == {"device"}


def test_an_auditor_is_refused_before_any_device_is_opened(session_manager, box: Path, as_user) -> None:
    from trace_core.core.errors import AuthorizationError
    from trace_core.core.operators import ROLE_AUDITOR, get_or_provision_operator, process_session_id

    _ = process_session_id()
    with session_manager.session() as session:
        row = get_or_provision_operator(session, "viewer", "workstation")
        row.role = ROLE_AUDITOR
        session.commit()
    as_user("viewer")

    adapter = file_device.FileDevice(box)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    for call in (lambda: svc.inspect_device(str(box / "disk-a.dd")), lambda: svc.check_device(str(box / "disk-a.dd"))):
        with pytest.raises(AuthorizationError):
            call()


def test_an_auditor_is_refused_even_when_the_source_is_writable(session_manager, box: Path, as_user) -> None:
    """Authorization precedes the probe; a refusal must not leak that the source was writable."""
    from trace_core.core.errors import AuthorizationError
    from trace_core.core.operators import ROLE_AUDITOR, get_or_provision_operator, process_session_id

    _ = process_session_id()
    with session_manager.session() as session:
        row = get_or_provision_operator(session, "viewer", "workstation")
        row.role = ROLE_AUDITOR
        session.commit()
    as_user("viewer")

    adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(AuthorizationError):
        svc.check_device(str(box / "disk-a.dd"))
    assert _actions(session_manager) == []


def test_an_auditor_may_still_list_devices(session_manager, box: Path, as_user) -> None:
    from trace_core.core.operators import ROLE_AUDITOR, get_or_provision_operator, process_session_id

    _ = process_session_id()
    with session_manager.session() as session:
        row = get_or_provision_operator(session, "viewer", "workstation")
        row.role = ROLE_AUDITOR
        session.commit()
    as_user("viewer")
    adapter = file_device.FileDevice(box)
    assert len(DeviceService(session_manager, adapter, adapter, adapter).list_devices()) == 1


def test_writable_source_raises_with_its_evidence(session_manager, box: Path) -> None:
    adapter = file_device.FileDevice(box, behaviour=file_device.WRITABLE)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    with pytest.raises(WriteProtectionError) as caught:
        svc.check_device(str(box / "disk-a.dd"))
    assert caught.value.verdict.value == "WRITABLE"
    assert caught.value.evidence.platform == "fake"


def test_unknown_verdict_needs_explicit_acknowledgement(session_manager, box: Path) -> None:
    adapter = file_device.FileDevice(box, behaviour=file_device.UNKNOWN_PROTECTION)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    node = str(box / "disk-a.dd")
    with pytest.raises(WriteProtectionError):
        svc.check_device(node)
    gate = svc.check_device(node, acknowledge_unverified_source=True)
    assert gate.verdict.value == "UNKNOWN"


def test_list_persists_nothing_and_writes_no_events(session_manager, svc, box: Path) -> None:
    from sqlalchemy import func

    from trace_core.devices.models import DeviceFingerprintModel

    svc.list_devices()
    with session_manager.session() as session:
        count = session.scalar(select(func.count()).select_from(DeviceFingerprintModel))
    assert count == 0


_ADAPTER_MODULES = frozenset({"file_device", "linux", "win32", "synthetic", "_subprocess"})


def _module_level_imports(source: Path) -> set[str]:
    import ast

    found: set[str] = set()
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _adapters_among(imports: set[str]) -> set[str]:
    return {name for name in imports if _ADAPTER_MODULES & set(name.split("."))}


def test_service_module_level_imports_touch_no_adapter() -> None:
    from trace_core.devices import service as service_module

    offenders = _adapters_among(_module_level_imports(Path(service_module.__file__)))
    assert not offenders, f"module-level adapter import: {offenders}"
    for helper in ("default_adapter", "os_adapter", "_fill_ports"):
        assert helper in dir(service_module), f"composition root {helper} disappeared"


class _WindllMustNotLoad:
    """Stands in for `ctypes.windll` off Windows, where the attribute does not exist."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"adapter selection reached ctypes.windll.{name} off-platform")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ("auto", "LinuxDevice"),
        ("", "LinuxDevice"),
        ("linux", "LinuxDevice"),
        ("win32", "Win32Device"),
        ("nonsense", None),
    ],
)
def test_adapter_env_selects_but_never_unlocks_real_hardware(monkeypatch, env: str, expected: str | None) -> None:
    """[D27] the env var picks an adapter; the opt-in flag stays required."""
    import ctypes

    from trace_core.devices import service as service_module

    if env:
        monkeypatch.setenv(service_module.ENV_ADAPTER, env)
    else:
        monkeypatch.delenv(service_module.ENV_ADAPTER, raising=False)
    monkeypatch.setattr(service_module.sys, "platform", "linux" if expected != "Win32Device" else "win32")
    # Selecting the Windows adapter off-platform must not reach `ctypes.windll`, which
    # exists only on Windows. Asserting the class name is the whole contract here.
    monkeypatch.setattr(ctypes, "windll", _WindllMustNotLoad(), raising=False)
    adapter = service_module.os_adapter()
    assert (type(adapter).__name__ if adapter is not None else None) == expected


def test_os_adapter_is_absent_on_an_unsupported_platform(monkeypatch) -> None:
    from trace_core.devices import service as service_module

    monkeypatch.delenv(service_module.ENV_ADAPTER, raising=False)
    monkeypatch.setattr(service_module.sys, "platform", "freebsd")
    assert service_module.os_adapter() is None


def test_the_dotenv_adapter_reaches_os_adapter(monkeypatch) -> None:
    import ctypes

    from trace_core.core.settings import Settings, settings
    from trace_core.devices import service as service_module

    monkeypatch.delenv(service_module.ENV_ADAPTER, raising=False)
    assert Settings(TRACE_DEVICE_ADAPTER="auto").device_adapter == "auto"
    monkeypatch.setattr(settings, "device_adapter", "file")
    assert service_module.os_adapter() is None, (
        "TRACE_DEVICE_ADAPTER set in .env only ever reached Settings, which os_adapter() "
        "never read; asking for the synthetic file adapter silently selected the "
        "real-hardware adapter instead"
    )
    monkeypatch.setattr(ctypes, "windll", _WindllMustNotLoad(), raising=False)
    monkeypatch.setattr(settings, "device_adapter", "linux")
    assert type(service_module.os_adapter()).__name__ == "LinuxDevice"
    monkeypatch.setenv(service_module.ENV_ADAPTER, "win32")
    assert type(service_module.os_adapter()).__name__ == "Win32Device", (
        "a live environment variable must still win over the settings value"
    )


def test_os_adapter_satisfies_all_three_ports() -> None:
    from trace_core.devices import ports
    from trace_core.devices import service as service_module

    adapter = service_module.os_adapter()
    assert adapter is not None
    for protocol, method in (
        (ports.DeviceEnumerator, "list_block_devices"),
        (ports.DeviceInspector, "inspect"),
        (ports.WriteBlockerProbe, "verify"),
    ):
        assert inspect.signature(getattr(type(adapter), method)) == inspect.signature(getattr(protocol, method))


def test_the_d31_adapter_guard_can_actually_fail(tmp_path: Path) -> None:
    offender = tmp_path / "offender.py"
    offender.write_text("from trace_core.devices.file_device import FileDevice\n", encoding="utf-8")
    assert _adapters_among(_module_level_imports(offender)) == {"trace_core.devices.file_device"}

    innocent = tmp_path / "innocent.py"
    innocent.write_text("from trace_core.devices.domain import DeviceInfo\n", encoding="utf-8")
    assert _adapters_among(_module_level_imports(innocent)) == set()


def test_fingerprints_are_not_purged_with_a_case(session_manager, svc, box: Path) -> None:
    """[D29] observation history outlives the case it was captured during.

    The link to a case lives in its own `case_devices` table, so an observation carries no
    case reference at all and there is no foreign key for a purge to cascade along.
    """
    from trace_core.devices.models import DeviceFingerprintModel

    svc.inspect_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        rows = session.scalars(select(DeviceFingerprintModel)).all()
    assert rows
    assert all(row.case_number is None for row in rows), (
        "the link must be carried by case_devices, never by the observation row"
    )

    from sqlalchemy import inspect

    assert inspect(session_manager.engine).get_foreign_keys(DeviceFingerprintModel.__tablename__) == [], (
        "the case link must not be a foreign key; a cascade would delete forensic history with the case"
    )


def test_check_refuses_a_stale_inspection_of_another_device(session_manager, svc, box: Path) -> None:
    from trace_core.devices.domain import FingerprintMismatchError

    synthetic.write_disk(box / "disk-b.dd", seed=b"other", size=4096)
    other = str(box / "disk-a.dd")
    target = str(box / "disk-b.dd")
    inspection = svc.inspect_device(other)
    with pytest.raises(FingerprintMismatchError, match="disk-a"):
        svc.check_device(target, inspection=inspection)


def test_check_accepts_a_matching_inspection(session_manager, svc, box: Path) -> None:
    node = str(box / "disk-a.dd")
    inspection = svc.inspect_device(node)
    gate = svc.check_device(node, inspection=inspection)
    assert gate.verdict.value == "READ_ONLY"


def test_check_refuses_a_same_node_device_that_changed_size(session_manager, svc, box: Path) -> None:
    """The guard compared node NAMES only, never any device identity.

    A different disk answering the same node passed the check, so a stale fingerprint
    from one device could be carried into a gate on another. The exception is named
    FingerprintMismatchError while comparing no fingerprint at all.
    """
    from trace_core.devices.domain import FingerprintMismatchError

    node = str(box / "disk-a.dd")
    inspection = svc.inspect_device(node)
    before = inspection.device.size_bytes

    synthetic.write_disk(node, seed=b"a-much-longer-disk", size=before * 4)
    assert svc.enumerator.list_block_devices()[0].size_bytes == before * 4

    with pytest.raises(FingerprintMismatchError):
        svc.check_device(node, inspection=inspection)


@pytest.mark.parametrize("omitted", range(3))
def test_partial_injection_never_leaves_a_port_unset(session_manager, box: Path, omitted: int) -> None:
    """Every port was `Any` until the Ports were bound; a missing one became an AttributeError."""
    adapter = file_device.FileDevice(box)
    ports: list[file_device.FileDevice | None] = [adapter, adapter, adapter]
    ports[omitted] = None
    svc = DeviceService(session_manager, *ports)
    assert all(p is not None for p in (svc.enumerator, svc.inspector, svc.probe))


def test_no_default_adapter_is_built_when_all_three_are_injected(session_manager, box: Path, monkeypatch) -> None:
    import trace_core.devices.service as service_module

    def _forbidden() -> None:
        raise AssertionError("default adapter constructed despite a complete injection")

    monkeypatch.setattr(service_module, "default_adapter", _forbidden)
    adapter = file_device.FileDevice(box)
    DeviceService(session_manager, adapter, adapter, adapter)


def test_default_adapter_is_built_once_and_shared(session_manager, monkeypatch) -> None:
    built: list[object] = []

    def _spy():
        adapter = file_device.FileDevice(Path.cwd())
        built.append(adapter)
        return adapter

    monkeypatch.setattr("trace_core.devices.service.default_adapter", _spy)
    svc = DeviceService(session_manager)
    assert len(built) == 1
    assert svc.enumerator is svc.inspector is svc.probe


def test_actor_wider_than_its_column_is_bounded(session_manager, svc, box: Path, monkeypatch) -> None:
    from trace_core.core.operators import process_session_id
    from trace_core.devices.models import MAX_ACTOR, DeviceFingerprintModel

    _ = process_session_id()
    monkeypatch.setattr("trace_core.core.operators.getpass.getuser", lambda: "D" * 200, raising=False)
    monkeypatch.setattr("trace_core.core.operators.socket.gethostname", lambda: "H" * 200, raising=False)
    svc.inspect_device(str(box / "disk-a.dd"))
    with session_manager.session() as session:
        rows = session.scalars(select(DeviceFingerprintModel)).all()
    assert rows
    assert all(len(r.inspected_by) <= MAX_ACTOR for r in rows)


def test_capacity_column_is_not_int4() -> None:
    from trace_core.devices.models import DeviceFingerprintModel

    assert isinstance(DeviceFingerprintModel.__table__.c.capacity_bytes.type, BigInteger)


@pytest.mark.parametrize(
    ("column", "width"),
    [
        ("node", MAX_NODE_LENGTH),
        ("serial", MAX_DEVICE_STRING),
        ("model", MAX_DEVICE_STRING),
        ("firmware", MAX_DEVICE_STRING),
        ("wwn", MAX_DEVICE_STRING),
    ],
)
def test_string_columns_match_the_domain_bounds_they_store(column: str, width: int) -> None:
    from trace_core.devices.models import DeviceFingerprintModel

    stored = getattr(DeviceFingerprintModel.__table__.c, column).type.length
    assert stored == width, f"{column} column and domain bound have drifted apart"


def test_unknown_kind_is_a_validation_error(svc) -> None:
    from trace_core.core.errors import ValidationError

    with pytest.raises(ValidationError, match="unknown device kind"):
        svc.list_devices("floppy")


def test_kind_filter_selects_a_subset(svc, box: Path) -> None:
    synthetic.write_disk(box / "disk-c.dd", seed=b"c", size=512)
    assert len(svc.list_devices("file")) == 2
    assert svc.list_devices("os") == []


@pytest.mark.parametrize("spelling", ["all", "ALL", "All", " all "])
def test_the_all_filter_ignores_case_and_padding(svc, spelling: str) -> None:
    assert len(svc.list_devices(spelling)) == 1


def test_kind_filter_ignores_case_and_padding(svc) -> None:
    assert len(svc.list_devices(" file ")) == 1


def test_change_token_delegates_to_the_enumerator(session_manager, device_box: Path) -> None:
    from trace_core.devices import helpers as helpers_module

    adapter = file_device.FileDevice(device_box)
    svc = DeviceService(session_manager, adapter, adapter, adapter)
    assert svc.change_token() == ("disk-a.dd", "disk-b.dd")
    assert isinstance(helpers_module.do_change_token(session_manager), tuple)


class _StubEnumerator:
    def __init__(self, nodes: list[str]) -> None:
        self._nodes = nodes

    def list_block_devices(self):
        from trace_core.devices.domain import DeviceInfo, DeviceKind

        return [DeviceInfo(node=node, kind=DeviceKind.OS, requires_real_hardware_opt_in=False) for node in self._nodes]

    def change_token(self):
        return ()


def _resolving(*nodes: str) -> DeviceService:
    from trace_core.devices.service import DeviceService as DS

    return DS(None, _StubEnumerator(list(nodes)), None, None)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (r"\\.\PhysicalDrive0", r"\\.\PhysicalDrive0"),
        (r"\\.\PHYSICALDRIVE0", r"\\.\PhysicalDrive0"),
        ("PhysicalDrive0", r"\\.\PhysicalDrive0"),
        ("physicaldrive0", r"\\.\PhysicalDrive0"),
        ("pd0", r"\\.\PhysicalDrive0"),
        ("PD12", r"\\.\PhysicalDrive12"),
    ],
)
def test_short_ids_resolve_to_the_enumerated_device(given: str, expected: str) -> None:
    svc = _resolving(r"\\.\PhysicalDrive0", r"\\.\PhysicalDrive12", r"\\.\PhysicalDrive7")
    assert svc._resolve(given, True).node == expected


def test_a_bare_number_does_not_alias_a_physical_drive() -> None:
    """Only a `pd`/`PhysicalDrive` prefix may select a drive by number.

    The prefix was optional, so `12`, `pd12` and `PhysicalDrive12` all produced one key.
    With a single such node enumerated, `device check pd12` silently opened the wrong
    device, and `007` collapsed onto `pd7`.
    """
    from trace_core.devices.domain import DeviceNotFoundError
    from trace_core.devices.service import _pd_key

    assert _pd_key("12") is None
    assert _pd_key("007") is None
    assert _pd_key("pd12") == _pd_key("PhysicalDrive12")

    svc = _resolving(r"\\.\PhysicalDrive12")
    for bare in ("12", "007"):
        with pytest.raises(DeviceNotFoundError):
            svc._resolve(bare, True)


def test_basenames_still_resolve() -> None:
    svc = _resolving("/dev/sda", "/dev/sdb")
    assert svc._resolve("sda", True).node == "/dev/sda"
    assert svc._resolve("/dev/sdb", True).node == "/dev/sdb"


def test_an_ambiguous_name_is_refused_not_guessed() -> None:
    from trace_core.devices.domain import DeviceNotFoundError

    svc = _resolving("C:/a/disk.dd", "D:/b/disk.dd")
    with pytest.raises(DeviceNotFoundError, match="ambiguous"):
        svc._resolve("disk.dd", True)


def test_unknown_and_empty_nodes_are_refused() -> None:
    from trace_core.core.errors import ValidationError
    from trace_core.devices.domain import DeviceNotFoundError

    svc = _resolving(r"\\.\PhysicalDrive0")
    with pytest.raises(DeviceNotFoundError):
        svc._resolve("pd9", True)
    with pytest.raises(DeviceNotFoundError):
        svc._resolve("../../../etc/passwd", True)
    with pytest.raises(ValidationError):
        svc._resolve("   ", True)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (r"\\.\PhysicalDrive0", "pd0"),
        (r"\\.\PHYSICALDRIVE12", "pd12"),
        ("physicaldrive3", "pd3"),
        ("pd4", "pd4"),
        ("/dev/sda", "sda"),
        ("disk-a.dd", "disk-a.dd"),
    ],
)
def test_short_id_is_stable_and_human(node: str, expected: str) -> None:
    from trace_core.devices.service import short_id

    assert short_id(node) == expected


def test_node_names_never_go_through_pathlib() -> None:
    from trace_core.devices.service import _node_name

    assert _node_name(r"\\.\PhysicalDrive0") == "PhysicalDrive0"
    assert _node_name("/dev/sda") == "sda"
    assert _node_name("disk-a.dd") == "disk-a.dd"
    assert _node_name("C:/a/disk.dd") == "disk.dd"
