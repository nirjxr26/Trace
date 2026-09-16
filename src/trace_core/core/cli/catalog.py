"""Single source for feature registration shared by Typer main and REPL shell."""

from typing import Any


def feature_apps() -> list[tuple[str, Any]]:
    """Typer sub-apps in registration order. Same list for main.py."""
    from trace_core.audit.commands import audit_app
    from trace_core.cases.commands import case_app
    from trace_core.core.cli.db_commands import db_app

    return [("case", case_app), ("audit", audit_app), ("db", db_app)]


def default_handlers() -> list[Any]:
    """REPL handlers in registration order. Same set for shell.py (audit import guarded)."""
    from trace_core.cases.shell_handler import CaseShellCommandHandler

    handlers: list[Any] = [CaseShellCommandHandler()]
    try:
        from trace_core.audit.shell_handler import AuditShellCommandHandler

        handlers.append(AuditShellCommandHandler())
    except Exception:
        pass
    return handlers
