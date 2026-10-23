import pathlib

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.core.cli.exit_codes import EXIT_ERROR
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch) -> None:
    session_mgr = DatabaseSessionManager("sqlite:///:memory:")
    session_mgr.init_schema()
    monkeypatch.setattr("trace_core.core.service.db_manager", session_mgr)


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
    assert "Case '2026-CLI-0001' created." in res.stdout

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
    assert "Case '2026-CLI-0001' updated." in res_edit.stdout

    # 6. Close case
    res_close = runner.invoke(app, ["case", "close", "2026-CLI-0001", "--reason", "CLI flow done", "--yes"])
    assert res_close.exit_code == 0
    assert "Case '2026-CLI-0001' closed permanently." in res_close.stdout

    # 7. Soft delete (archive) case
    res_archive = runner.invoke(app, ["case", "delete", "2026-CLI-0001", "--yes"])
    assert res_archive.exit_code == 0
    assert "Case '2026-CLI-0001' archived." in res_archive.stdout

    # 8. Permanent purge of archived case
    res_del = runner.invoke(app, ["case", "delete", "2026-CLI-0001", "--purge", "--yes"])
    assert res_del.exit_code == 0
    assert "Case '2026-CLI-0001' purged permanently." in res_del.stdout

    # 9. Querying non-existent case exits with NOT_FOUND
    res_missing = runner.invoke(app, ["case", "show", "NON-EXISTENT-CASE"])
    assert res_missing.exit_code != 0
    assert "Case Not Found" in res_missing.stdout


def test_cli_case_review_flow() -> None:
    res = runner.invoke(
        app, ["case", "create", "--number", "2026-CLI-0002", "--title", "Review", "--examiner", "Investigator CLI"]
    )
    assert res.exit_code == 0

    res_review = runner.invoke(app, ["case", "review", "2026-CLI-0002", "--reason", "Peer check"])
    assert res_review.exit_code == 0
    assert "moved under review" in res_review.stdout

    res_list = runner.invoke(app, ["case", "list", "--status", "UNDER_REVIEW"])
    assert "2026-CLI-0002" in res_list.stdout

    res_resume = runner.invoke(app, ["case", "review", "2026-CLI-0002", "--resume"])
    assert res_resume.exit_code == 0
    assert "returned to active work" in res_resume.stdout

    res_again = runner.invoke(app, ["case", "review", "2026-CLI-0002", "--resume"])
    assert res_again.exit_code == EXIT_ERROR
    assert "Illegal transition" in res_again.stdout


def test_show_case_lists_linked_and_historical_devices(device_file_env) -> None:  # type: ignore[no-untyped-def]
    number = "2026-LINK-0001"
    assert (
        runner.invoke(
            app, ["case", "create", "--number", number, "--title", "Link Parity", "--examiner", "Ex"]
        ).exit_code
        == 0
    )
    disk_a = str(device_file_env / "disk-a.dd")
    disk_b = str(device_file_env / "disk-b.dd")
    assert runner.invoke(app, ["device", "inspect", disk_a, "--output", "json"]).exit_code == 0
    assert runner.invoke(app, ["device", "link", disk_a, "--case", number, "--label", "bag-1"]).exit_code == 0
    assert runner.invoke(app, ["device", "link", disk_b, "--case", number]).exit_code == 0
    assert runner.invoke(app, ["device", "unlink", disk_b, "--case", number]).exit_code == 0
    res = runner.invoke(app, ["case", "show", number])
    assert res.exit_code == 0
    assert "LINKED DEVICE" in res.stdout
    assert "bag-1" in res.stdout
    shown = "".join(res.stdout.splitlines())
    assert "disk-a.dd" in shown
    assert "disk-b.dd" in shown
    res_json = runner.invoke(app, ["case", "show", number, "--output", "json"])
    assert res_json.exit_code == 0
    assert "LINKED DEVICE" not in res_json.stdout
    assert runner.invoke(app, ["device", "unlink", disk_a, "--case", number]).exit_code == 0


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
    assert result.exit_code == EXIT_ERROR
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


def test_help_does_not_load_the_repl() -> None:
    """prompt_toolkit and the shell stack cost ~0.5 s; only the bare REPL needs them."""
    import subprocess
    import sys

    code = "import sys, trace_core.cli.main; print('shell' if 'trace_core.cli.shell' in sys.modules else 'clean')"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parents[2],
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert proc.stdout.strip() == "clean", "importing the CLI pulled in the REPL stack"
