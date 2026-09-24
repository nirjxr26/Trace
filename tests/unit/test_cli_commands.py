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
    from trace_core.core.settings import settings

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"Trace v{settings.version}" in result.stdout


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
    res_close = runner.invoke(app, ["case", "close", "2026-CLI-0001", "--reason", "CLI flow done", "--yes"])
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


def test_db_status_offline_renders_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline status must render styled text, never literal markup brackets."""
    # Unparsable URL fails inside create_engine: instant, no network involved.
    bad = DatabaseSessionManager("not-a-database-url")
    monkeypatch.setattr("trace_core.core.cli.db_commands.db_manager", bad)
    result = runner.invoke(app, ["db", "status"])
    assert result.exit_code == 1
    assert "Offline" in result.stdout
    assert "[red]" not in result.stdout
    assert "[/red]" not in result.stdout


def test_help_syntax_fits_shared_grid() -> None:
    """Every help syntax must fit the shared grid or descriptions misalign."""
    from trace_core.cli.shell import CONSOLE_HELP_ENTRIES, HELP_GRID_SYNTAX_WIDTH
    from trace_core.core.cli.catalog import default_handlers

    entries = list(CONSOLE_HELP_ENTRIES)
    for handler in default_handlers():
        entries.extend(handler.get_help_entries())
    assert entries
    for syntax, _alias, _desc in entries:
        assert len(syntax) <= HELP_GRID_SYNTAX_WIDTH, f"help syntax overflows the grid: {syntax!r}"
