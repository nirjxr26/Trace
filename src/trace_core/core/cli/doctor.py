"""Preflight diagnostics: runtime, database, migrations, storage.

Single diagnostic command for users and installers. Exits 0 only when every
check passes, so `trace doctor` doubles as the installer's proof gate.
"""

import sys

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.exit_codes import EXIT_ERROR
from trace_core.core.database.health import fetch_db_snapshot
from trace_core.core.database.session import db_manager
from trace_core.core.ui.renderers import console, render_minimalist_table

MIN_PYTHON = (3, 12)


def _python_check() -> tuple[str, str, bool]:
    """Runtime version gate. Returns (name, detail, passed)."""
    current = sys.version_info[:3]
    detail = ".".join(str(p) for p in current)
    passed = (current[0], current[1]) >= MIN_PYTHON
    if not passed:
        detail += " (requires Python 3.12+)"
    return ("Python runtime", detail, passed)


def _storage_check() -> tuple[str, str, bool]:
    """Storage root exists and accepts writes. Returns (name, detail, passed)."""
    from pathlib import Path

    from trace_core.core.settings import settings

    root = Path(settings.storage_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".trace-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return ("Storage", str(root), True)
    except OSError as exc:
        return ("Storage", f"{root} ({exc})", False)


def run_doctor() -> None:
    """Run all preflight checks, render results, exit non-zero on any failure."""
    from rich.text import Text

    from trace_core.core.settings import settings

    with capture_cli_errors("System Diagnostics Failed"):
        rows: list[list] = []
        failed: list[str] = []

        def record(name: str, detail: str, passed: bool) -> None:
            status = Text("PASS", style="green") if passed else Text("FAIL", style="red")
            rows.append([name, status, detail])
            if not passed:
                failed.append(name)

        record(*_python_check())

        try:
            db_manager.ensure_ready()
        except Exception as exc:
            record("Database", f"Offline ({exc})", False)
            rows.append(["Migrations", Text("SKIP", style="dim"), "no connection"])
        else:
            snap = fetch_db_snapshot(db_manager)
            if snap.healthy:
                record("Database", f"Online ({snap.message})", True)
                if snap.pending:
                    record(
                        "Migrations",
                        f"{len(snap.pending)} pending — run `trace db migrate`",
                        False,
                    )
                else:
                    record("Migrations", f"up to date ({len(snap.applied)} applied)", True)
            else:
                record("Database", f"Offline ({snap.message})", False)
                rows.append(["Migrations", Text("SKIP", style="dim"), "no connection"])
        record(*_storage_check())

        console.print("")
        console.print(f"[bold cyan]Trace Doctor v{settings.version}[/bold cyan]")
        render_minimalist_table(
            "Preflight Diagnostics",
            [
                ("Check", {"style": "bold", "no_wrap": True}),
                ("Status", {"no_wrap": True, "max_width": 8}),
                ("Detail", {"overflow": "ellipsis"}),
            ],
            rows,
            empty_message="No diagnostic checks ran.",
            show_count=False,
        )

        if failed:
            from trace_core.core.ui.renderers import render_error_card

            render_error_card(
                "System Diagnostics Failed",
                f"Failing checks: {', '.join(failed)}.",
                "Fix the rows above, then re-run `trace doctor`.",
            )
            raise typer.Exit(code=EXIT_ERROR)
        return
