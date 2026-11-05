"""CLI smoke for audit commands."""

import pytest
from typer.testing import CliRunner

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.main import app
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_audit_db(monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)


def test_audit_cli_show_verify_export(tmp_path, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="CLI-A", lead_examiner="Ex"))
    # show
    res = runner.invoke(app, ["audit", "show"])
    assert res.exit_code == 0
    assert "CASE_CREATED" in res.stdout
    assert "2026-CR-0001" in res.stdout
    # list shows Seq/Action/Case/Time only; Actor/Command live in the detail view
    assert "Command" not in res.stdout
    # verify
    res_v = runner.invoke(app, ["audit", "verify"])
    assert res_v.exit_code == 0
    assert "VALID" in res_v.stdout
    # export
    out = tmp_path / "bundle.jsonl"
    res_e = runner.invoke(app, ["audit", "export", "--out", str(out)])
    assert res_e.exit_code == 0
    assert out.exists()
    # show json
    res_j = runner.invoke(app, ["audit", "show", "--output", "json"])
    assert res_j.exit_code == 0
    assert "seq" in res_j.stdout


def test_bundle_names_say_whether_the_file_is_sealed() -> None:
    from trace_core.audit.helpers import default_export_path, plain_destination, sealed_destination

    assert sealed_destination("bundle.jsonl").name == "bundle.jsonl.sealed"
    assert sealed_destination("bundle.jsonl.sealed").name == "bundle.jsonl.sealed"
    assert plain_destination("bundle.jsonl.sealed").name == "bundle.jsonl"
    assert plain_destination("bundle.bin").name == "bundle.bin.jsonl"
    assert default_export_path(sealed=True).name.endswith(".jsonl.sealed")
    assert not default_export_path().name.endswith(".sealed")


def test_encrypted_export_prints_a_receipt_and_decrypts_without_an_out_flag(
    tmp_path, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TRACE_EXPORT_PASSPHRASE", "pw-test")
    CaseService(session_manager).create_case(CaseCreateDto(title="Sealed CLI", lead_examiner="Ex"))
    out = tmp_path / "bundle.jsonl"

    res = runner.invoke(app, ["audit", "export", "--out", str(out), "--encrypt"])
    assert res.exit_code == 0, res.stdout
    sealed = tmp_path / "bundle.jsonl.sealed"
    assert sealed.exists()
    assert not out.exists()
    for label in ("File", "Size", "Events", "SHA-256", "Sealed", "Next"):
        assert label in res.stdout

    res_d = runner.invoke(app, ["audit", "decrypt", "--in", str(sealed)])
    assert res_d.exit_code == 0, res_d.stdout
    assert out.exists()
    assert "Events" in res_d.stdout


def test_devices_addressed_by_serial_are_filterable_from_the_cli(session_manager: DatabaseSessionManager) -> None:
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.repository import SqlAlchemyAuditRepository

    with session_manager.session() as session:
        repo = SqlAlchemyAuditRepository(session)
        repo.append(
            AuditAction.DEVICE_INSPECTED, "Ex", None, None, {}, subject_type="device", subject_device_serial="SYNTH-9"
        )
        repo.append(
            AuditAction.DEVICE_INSPECTED, "Ex", None, None, {}, subject_type="device", subject_device_serial="SYNTH-1"
        )
        session.commit()
    res = runner.invoke(app, ["audit", "show", "--device", "SYNTH-9", "--output", "json"])
    assert res.exit_code == 0
    assert "SYNTH-9" in res.stdout
    assert "SYNTH-1" not in res.stdout


def test_device_event_detail_names_the_device_and_its_case(
    session_manager: DatabaseSessionManager, capsys: pytest.CaptureFixture[str]
) -> None:
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.helpers import show_seq_view
    from trace_core.audit.repository import SqlAlchemyAuditRepository
    from trace_core.audit.service import AuditService
    from trace_core.devices.helpers import do_link

    case = CaseService(session_manager).create_case(
        CaseCreateDto(number="2026-SH-0301", title="Gate checked", lead_examiner="Ex")
    )
    node = r"\\.\PhysicalDrive9"
    do_link(session_manager, node, case.number, label="Bag 9")
    with session_manager.session() as session:
        event = SqlAlchemyAuditRepository(session).append(
            AuditAction.DEVICE_GATE_CHECKED,
            "Ex",
            None,
            None,
            {"node": node, "verdict": "UNKNOWN"},
            subject_type="device",
            subject_device_serial="SN-9",
        )
        session.commit()

    assert show_seq_view(AuditService(session_manager), event.seq, "table") is True
    out = capsys.readouterr().out
    assert "Bag 9" in out
    assert case.number in out
    assert "SELF-CHECK\n\n" not in out


def test_case_timeline_names_the_device_each_entry_acted_on(
    session_manager: DatabaseSessionManager, capsys: pytest.CaptureFixture[str]
) -> None:
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.helpers import render_case_timeline_view
    from trace_core.audit.service import AuditService
    from trace_core.devices.helpers import do_link

    case = CaseService(session_manager).create_case(
        CaseCreateDto(number="2026-SH-0302", title="Timeline device", lead_examiner="Ex")
    )
    do_link(session_manager, r"\\.\PhysicalDrive10", case.number, label="Bag 10")
    audit = AuditService(session_manager)
    events = audit.list_events(AuditFilterDto(case_number=case.number))

    assert render_case_timeline_view(audit, case.number, events, "table") is True
    out = capsys.readouterr().out
    assert "Device  Bag 10" in out
    assert "CASE ACTIVITY\n\n" not in out


def test_anchor_write_verify_roundtrip(
    tmp_path, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Verify anchor single-source: write on close, verify against it, catch tampering."""
    from trace_core.audit.anchor import read_anchor, verify_against_anchor
    from trace_core.audit.service import AuditService
    from trace_core.core.errors import AuditTamperError
    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    svc = CaseService(session_manager)
    created = svc.create_case(CaseCreateDto(title="Anchor", lead_examiner="Ex"))
    closed = svc.close_case(created.number, reason="done", closed_by="Ex")

    anchors = list((tmp_path / "anchors").glob("*.json"))
    assert len(anchors) == 1
    data = read_anchor(anchors[0])
    assert data["case"] == closed.number

    from trace_core.audit.anchor import latest_anchor_for

    assert latest_anchor_for(closed.number) == anchors[0]

    audit_svc = AuditService(session_manager)
    res = audit_svc.verify()
    assert res.is_valid
    verify_against_anchor(audit_svc, res, str(anchors[0]))

    # tampered anchor must convict
    import json

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**data, "last_seq": 999}), encoding="utf-8")
    with pytest.raises(AuditTamperError):
        verify_against_anchor(audit_svc, res, str(bad))
