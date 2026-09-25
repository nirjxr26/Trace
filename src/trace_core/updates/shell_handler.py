from trace_core.core.cli.shell_base import BaseShellHandler
from trace_core.updates.commands import update_app


class UpdateShellCommandHandler(BaseShellHandler):
    resource = "Update"

    def __init__(self) -> None:
        self._app = update_app

    @property
    def command_name(self) -> str:
        return "update"

    def execute(self, action: str, args: list[str], ctx: object) -> bool:
        from trace_core.core.cli.error_handler import capture_cli_errors

        act = (action or "").lower()
        if act in ("", "help"):
            for usage, _, desc in self.get_help_entries():
                from trace_core.core.ui.renderers import console

                console.print(f"[dim]{usage}[/dim] — {desc}")
            return True
        if act == "check":
            return self._shell_check(args)
        if act == "history":
            return self._shell_history(args)
        if act == "install":
            from trace_core.core.ui.renderers import console

            with capture_cli_errors("Update Install", exit_on_error=False):
                console.print("[yellow]Use standalone CLI for installs: trace update install --yes[/yellow]")
            return True
        return self.unknown_action(
            act, f"Action '{act}' is not valid for update commands. Type 'help' for available actions."
        )

    def _shell_check(self, args: list[str]) -> bool:
        from trace_core.core.cli.error_handler import capture_cli_errors
        from trace_core.core.ui.renderers import console
        from trace_core.updates.checker import cached_check, resolve_channel, resolve_manifest_target
        from trace_core.updates.commands import render_check_blocked

        _ = args
        with capture_cli_errors("Update Check", exit_on_error=False):
            channel = resolve_channel(None)
            target = resolve_manifest_target(None, channel)
            payload = cached_check(target, channel)
            if not payload["available"]:
                console.print(f"[dim]Up to date ({payload['current']}, {channel}).[/dim]")
            elif not payload["installable"]:
                render_check_blocked(payload)
            else:
                console.print(
                    f"[green]Update {payload['target']} available[/green] — current {payload['current']} ({channel})"
                )
        return True

    def _shell_history(self, args: list[str]) -> bool:
        from trace_core.core.cli.args import extract_int_flag
        from trace_core.core.cli.error_handler import capture_cli_errors
        from trace_core.core.ui.renderers import render_minimalist_table
        from trace_core.updates.commands import HISTORY_COLUMNS, history_table_rows
        from trace_core.updates.service import UpdateService

        with capture_cli_errors("Update History", exit_on_error=False):
            svc = UpdateService()
            rows = svc.list_history(
                limit=extract_int_flag(args, 50, "--limit"),
                offset=0,
            )
            render_minimalist_table(
                "Update History",
                HISTORY_COLUMNS,
                history_table_rows(rows),
                empty_message="No updates recorded.",
            )
        return True

    @property
    def _typer_app(self) -> object:
        return self._app

    def get_completions(self, text: str, ctx: object) -> list[str]:
        """Flag completions shared with case handler pattern. No new completer framework."""
        _ = ctx
        flags = ["--limit"]
        curr = text.split()[-1] if text.split() else ""
        return [f for f in flags if f.startswith(curr)]

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        # Syntaxes must fit the shared 36-col help grid (see _print_help_row);
        # remaining flags stay discoverable via tab-completion and --help.
        return [
            ("update check", "", "Check for available update"),
            ("update history", "", "Show update history"),
            ("update install (via CLI only)", "", "Install requires standalone CLI with --yes"),
        ]
