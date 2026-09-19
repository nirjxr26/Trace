from trace_core.core.cli.shell_base import BaseShellHandler
from trace_core.updates.commands import update_app


class UpdateShellCommandHandler(BaseShellHandler):
    resource = "Update"

    def __init__(self) -> None:
        self._app = update_app

    @property
    def command_name(self) -> str:
        return "update"

    def execute(self, action: str, args: list[str], ctx) -> bool:  # type: ignore[no-untyped-def]
        argv = [action, *args] if action else []
        from typer.testing import CliRunner

        res = CliRunner().invoke(self._app, argv)
        if res.output:
            from trace_core.core.ui.renderers import console

            console.print(res.output)
        return True

    @property
    def _typer_app(self):  # type: ignore[no-untyped-def]
        return self._app

    def get_help_entries(self):  # type: ignore[no-untyped-def]
        return [
            ("update check --manifest FILE", "", "Check for available update"),
            ("update history", "", "Show update history"),
            ("update verify", "", "Verify artifact against manifest"),
        ]
