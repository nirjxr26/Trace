"""Preflight diagnostics: runtime, database, migrations, storage.

Single diagnostic command for users and installers. Exits 0 only when every
check passes, so `trace doctor` doubles as the installer's proof gate.
"""

import sys

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.exit_codes import EXIT_ERROR
from trace_core.core.database.health import fetch_db_snapshot
from trace_core.core.database.session import DatabaseSessionManager, db_manager
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


def _storage_check(*, probe: bool = True) -> tuple[str, str, bool]:
    """Storage root exists and accepts writes. Returns (name, detail, passed).

    probe=False checks the directory only. The TUI render path calls it on every
    repaint, and writing into the evidence storage root on each one is both slow
    and a source of stray files if the process dies mid-probe.
    """
    from pathlib import Path

    from trace_core.core.settings import settings

    root = Path(settings.storage_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        if not probe:
            return ("Storage", str(root), True)
        probe_path = root / ".trace-write-probe"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        return ("Storage", str(root), True)
    except OSError as exc:
        return ("Storage", f"{root} ({exc})", False)


def _signing_key_check() -> tuple[str, str, bool]:
    """Signing key resolvable. False when the placeholder is active — records then
    cannot be verified, which is a worse outcome than a plain offline database because
    `audit verify` would otherwise report tampering."""
    from trace_core.audit.signing import is_default_key

    if is_default_key():
        return ("Signing key", "not set — your records can't be verified", False)
    return ("Signing key", "set", True)


def _ledger_check(manager: DatabaseSessionManager) -> tuple[str, str, bool]:
    """Chain integrity. Reports the row count rather than a bare verdict so an empty
    ledger is visibly empty rather than indistinguishable from a passing check."""
    from trace_core.audit.service import AuditService

    res = AuditService(manager).verify()
    if res.is_valid:
        if not res.events_verified:
            return ("Records", "no records yet", True)
        return ("Records", f"{res.events_verified} records, all linking correctly", True)
    return ("Records", f"problem at record {res.first_mismatch_seq} ({res.mismatch_type})", False)


def _protection_check(manager: DatabaseSessionManager) -> tuple[str, str, bool]:
    """Append-only protection present. A database that cannot refuse edits to the
    ledger is not a healthy forensic host.

    Read-only: the same verifier the migrations use confirms the trigger is there.
    A probe that tried an edit could conclude nothing on an empty ledger, and a
    health check must never be able to damage the evidence it is checking.
    """
    from trace_core.core.database.migrations import _verify_008_audit_protection

    with manager.engine.connect() as conn:
        if _verify_008_audit_protection(conn) is not True:
            return ("Records protected", "no — records can be edited", False)
    return ("Records protected", "yes — edits refused", True)


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
        record(*_signing_key_check())

        try:
            db_manager.ensure_ready()
        except Exception as exc:
            record("Database", f"Offline ({exc})", False)
            for name in ("Migrations", "Records", "Records protected"):
                rows.append([name, Text("SKIP", style="dim"), "no connection"])
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
            for check in (_ledger_check, _protection_check):
                try:
                    record(*check(db_manager))
                except Exception as exc:
                    record(check.__name__.replace("_check", "").title(), f"couldn't check ({exc})", False)
        record(*_storage_check())

        console.print("")
        from trace_core.updates.checker import pointer_version

        active, pointer_problem = pointer_version()
        # The package version was printed unconditionally, so a doctor run on a machine
        # whose install pointer could not be read claimed a version it had not checked.
        shown = active if active else settings.version
        console.print(f"[bold cyan]Trace Doctor v{shown}[/bold cyan]")
        if pointer_problem is not None:
            console.print(f"[yellow]Version pointer: {pointer_problem}[/yellow]")
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
