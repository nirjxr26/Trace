import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch) -> None:
    session_mgr = DatabaseSessionManager("sqlite:///:memory:")
    session_mgr.init_schema()
    monkeypatch.setattr("trace_core.cases.commands.db_manager", session_mgr)


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

    # 7. Soft delete (archive) case
    res_archive = runner.invoke(app, ["case", "delete", "2026-CLI-0001", "--yes"])
    assert res_archive.exit_code == 0
    assert "archive/soft-deleted" in res_archive.stdout

    # 8. Permanent purge of archived case
    res_del = runner.invoke(app, ["case", "delete", "2026-CLI-0001", "--purge", "--yes"])
    assert res_del.exit_code == 0
    assert "PERMANENTLY PURGEd" in res_del.stdout

    # 9. Querying non-existent case exits with NOT_FOUND
    res_missing = runner.invoke(app, ["case", "show", "NON-EXISTENT-CASE"])
    assert res_missing.exit_code != 0
    assert "Case Not Found" in res_missing.stdout


def test_capture_cli_errors_shell_mode() -> None:
    from trace_core.core.cli.error_handler import capture_cli_errors
    from trace_core.core.errors import NotFoundError

    # In shell mode (exit_on_error=False), should NOT raise typer.Exit
    with capture_cli_errors("Test Op", exit_on_error=False):
        raise NotFoundError("Evidence", "EVID-001")
