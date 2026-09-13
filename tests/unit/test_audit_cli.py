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
