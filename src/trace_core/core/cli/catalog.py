"""Single source for feature registration shared by Typer main and REPL shell."""

from typing import Any


def feature_apps() -> list[tuple[str, Any]]:
    """Typer sub-apps in registration order. Same list for main.py."""
    from trace_core.audit.commands import audit_app
    from trace_core.cases.commands import case_app
    from trace_core.core.cli.db_commands import db_app
    from trace_core.devices.commands import device_app
    from trace_core.updates.commands import update_app

    return [
        ("case", case_app),
        ("device", device_app),
        ("audit", audit_app),
        ("db", db_app),
        ("update", update_app),
    ]


def default_handlers() -> list[Any]:
    """REPL handlers in registration order. Same set for shell.py.

    A failing import propagates. These modules have no optional runtime dependency, so
    swallowing it only removed a whole command group from the shell with no diagnostic,
    which is the one failure mode a forensic tool must not have.
    """
    from trace_core.audit.shell_handler import AuditShellCommandHandler
    from trace_core.cases.shell_handler import CaseShellCommandHandler
    from trace_core.core.cli.uninstall_handler import UninstallShellCommandHandler
    from trace_core.devices.shell_handler import DeviceShellCommandHandler
    from trace_core.updates.shell_handler import UpdateShellCommandHandler

    return [
        CaseShellCommandHandler(),
        DeviceShellCommandHandler(),
        AuditShellCommandHandler(),
        UpdateShellCommandHandler(),
        UninstallShellCommandHandler(),
    ]
