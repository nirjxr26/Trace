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
    monkeypatch.setattr("trace_core.cases.commands.db_manager", session_manager)
    monkeypatch.setattr("trace_core.audit.commands.db_manager", session_manager)
    monkeypatch.setattr("trace_core.core.cli.db_commands.db_manager", session_manager)


def test_audit_cli_show_verify_export(tmp_path, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="CLI-A", lead_examiner="Ex"))
    # show
    res = runner.invoke(app, ["audit", "show"])
    assert res.exit_code == 0
    assert "CASE_" in res.stdout or "Created" in res.stdout or "Audit Ledger" in res.stdout
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
