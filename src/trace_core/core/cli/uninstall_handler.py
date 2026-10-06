from trace_core.core.cli.shell_base import BaseShellHandler


class UninstallShellCommandHandler(BaseShellHandler):
    resource = "Uninstall"

    @property
    def command_name(self) -> str:
        return "uninstall"

    def execute(self, action: str, args: list[str], ctx: object) -> bool:  # noqa: ARG002
        from trace_core.core.cli.error_handler import capture_cli_errors
        from trace_core.core.ui.renderers import console

        act = (action or "").lower()
        if act in ("", "help"):
            for usage, _, desc in self.get_help_entries():
                console.print(f"[dim]{usage}[/dim] — {desc}")
            return True
        if act not in ("--purge-data", "--yes"):
            return self.unknown_action(action, f"Action '{action}' not valid for uninstall. Try `help`.")
        with capture_cli_errors("Uninstall", exit_on_error=False):
            console.print("[yellow]Run standalone: trace uninstall [--purge-data] [--yes][/yellow]")
        return True

    @property
    def _typer_app(self) -> object:
        from trace_core.cli.main import app

        return app

    def get_completions(self, text: str, ctx: object) -> list[str]:
        _ = ctx
        if not self.owns_text(text):
            return []
        flags = ["--purge-data", "--yes"]
        curr = "" if text.endswith(" ") else text.split()[-1]
        return [f for f in flags if f.startswith(curr)]

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        return [
            ("uninstall", "", "Remove Trace (standalone CLI: trace uninstall)"),
            ("uninstall --purge-data", "", "Remove Trace AND all data (storage, trust keys, DB)"),
        ]
