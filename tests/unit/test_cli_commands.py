import pytest
from typer.testing import CliRunner

from trace_core.adapters.db.session import DatabaseSessionManager
from trace_core.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch) -> None:
    session_mgr = DatabaseSessionManager("sqlite:///:memory:")
    session_mgr.init_schema()
    monkeypatch.setattr("trace_core.cli.commands.case.db_manager", session_mgr)


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "Trace v0.1.0" in result.stdout


def test_cli_case_crud_flow() -> None:
    # 1. Create case
    res = runner.invoke(
        app,
        [
            "case",
            "create",
            "--number",
            "2026-CLI-0001",
            "--title",
            "CLI Flow Test",
            "--examiner",
            "Investigator CLI",
            "--desc",
            "Created from automated test",
            "--tags",
            "test,cli",
        ],
    )
    assert res.exit_code == 0
    assert "Case '2026-CLI-0001' created successfully!" in res.stdout

    # 2. List cases
    res_list = runner.invoke(app, ["case", "list"])
    assert res_list.exit_code == 0
    assert "2026-CLI-0001" in res_list.stdout

    # 3. Show case
    res_show = runner.invoke(app, ["case", "show", "2026-CLI-0001"])
    assert res_show.exit_code == 0
    assert "CLI Flow Test" in res_show.stdout

    # 4. Show case in JSON
    res_json = runner.invoke(app, ["case", "show", "2026-CLI-0001", "--output", "json"])
    assert res_json.exit_code == 0
    assert '"number": "2026-CLI-0001"' in res_json.stdout

    # 5. Edit case
    res_edit = runner.invoke(app, ["case", "edit", "2026-CLI-0001", "--notes", "Automated edit note"])
    assert res_edit.exit_code == 0
    assert "updated successfully" in res_edit.stdout

    # 6. Close case
    res_close = runner.invoke(app, ["case", "close", "2026-CLI-0001", "--yes"])
    assert res_close.exit_code == 0
    assert "CLOSED" in res_close.stdout

    # 7. Delete case
    res_del = runner.invoke(app, ["case", "delete", "2026-CLI-0001", "--purge", "--yes"])
    assert res_del.exit_code == 0
    assert "PERMANENTLY PURGEd" in res_del.stdout
