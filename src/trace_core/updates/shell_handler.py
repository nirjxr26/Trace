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
        from trace_core.updates.checker import cached_check, resolve_channel, resolve_manifest_target
        from trace_core.updates.renderers import render_check_card

        _ = args
        with capture_cli_errors("Update Check", exit_on_error=False):
            channel = resolve_channel(None)
            target = resolve_manifest_target(None)
            render_check_card(cached_check(target, channel), channel)
        return True

    @property
    def _typer_app(self) -> object:
        return self._app

    def get_completions(self, text: str, ctx: object) -> list[str]:  # type: ignore[override]
        """Flag completions shared with case handler pattern. No new completer framework."""
        _ = ctx
        if not self.owns_text(text):
            return []
        actions = [("check", "Check for updates"), ("install", "Install update")]
        flags = {
            "check": ["--output", "-o", "--manifest"],
            "install": ["--yes", "-y", "--bypass-minimum", "--manifest", "--artifact"],
        }
        parts = text.split()
        curr = parts[-1] if parts and not text.endswith(" ") else ""
        if len(parts) == 1 and text.endswith(" "):
            return [a for a, _ in actions]
        if len(parts) >= 2 and parts[0] == "update":
            action = parts[1]
            if len(parts) == 2 and not text.endswith(" "):
                return [a for a, _ in actions if a.startswith(action)]
            if action in flags:
                return [f for f in flags[action] if f.startswith(curr)]
            return []
        return []

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        # Syntaxes must fit the shared 36-col help grid (see _print_help_row);
        # remaining flags stay discoverable via tab-completion and --help.
        return [
            ("update check", "", "Check for available update"),
            ("update install (via CLI only)", "", "Install requires standalone CLI with --yes"),
        ]
