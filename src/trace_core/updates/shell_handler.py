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
        if act in ("show", "verify"):
            return self._shell_show_verify(act, args)
        if act == "install":
            from trace_core.core.ui.renderers import console

            with capture_cli_errors("Update Install", exit_on_error=False):
                console.print(
                    "[yellow]Use standalone CLI for installs: trace update install --manifest FILE --artifact FILE --yes[/yellow]"
                )
            return True
        return self.unknown_action(
            act, f"Action '{act}' is not valid for update commands. Type 'help' for available actions."
        )

    def _shell_check(self, args: list[str]) -> bool:
        from trace_core.core.cli.args import extract_flag_value
        from trace_core.core.cli.error_handler import capture_cli_errors
        from trace_core.core.ui.renderers import console
        from trace_core.updates.checker import cached_check
        from trace_core.updates.errors import UpdateError

        with capture_cli_errors("Update Check", exit_on_error=False):
            from trace_core.core.settings import settings

            manifest = extract_flag_value(args, "--manifest") or settings.update_manifest
            channel = extract_flag_value(args, "--channel") or settings.update_channel
            if not manifest:
                raise UpdateError("no update manifest configured (pass --manifest or set TRACE_UPDATE_MANIFEST)")
            payload = cached_check(manifest, channel)
            if not payload["available"]:
                console.print(f"[dim]Up to date ({payload['current']}, {channel}).[/dim]")
            elif not payload["installable"]:
                console.print(
                    f"[yellow]Update {payload['target']} available but deferred: {payload['block_reason']}[/yellow]"
                )
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
                offset=extract_int_flag(args, 0, "--offset"),
            )
            render_minimalist_table(
                "Update History",
                HISTORY_COLUMNS,
                history_table_rows(rows),
                empty_message="No updates recorded.",
            )
        return True

    def _shell_show_verify(self, act: str, args: list[str]) -> bool:
        from pathlib import Path

        from trace_core.core.cli.args import extract_flag_value
        from trace_core.core.cli.error_handler import capture_cli_errors
        from trace_core.core.ui.renderers import console
        from trace_core.updates.manifest import load_manifest

        with capture_cli_errors(f"Update {act.capitalize()}", exit_on_error=False):
            from trace_core.updates.errors import UpdateError

            manifest_path = extract_flag_value(args, "--manifest")
            if not manifest_path:
                raise UpdateError("pass --manifest FILE")
            m = load_manifest(manifest_path)
            console.print(f"[bold]{m.product} {m.version}[/bold] ({m.channel})")
            if act == "show":
                artifact = extract_flag_value(args, "--artifact")
                if not artifact:
                    console.print("[dim]Unverified manifest content — shown before verification.[/dim]")
                else:
                    from trace_core.updates.verifier import verify_manifest

                    verify_manifest(m, Path(artifact))
                    console.print("[green]Artifact verification passed.[/green]")
            else:
                artifact = extract_flag_value(args, "--artifact")
                if not artifact:
                    raise UpdateError("pass --artifact FILE")
                from trace_core.updates.verifier import verify_manifest

                verify_manifest(m, Path(artifact))
                console.print("[green]Verification passed.[/green]")
        return True

    @property
    def _typer_app(self):  # type: ignore[no-untyped-def]
        return self._app

    def get_help_entries(self):  # type: ignore[no-untyped-def]
        return [
            ("update check --manifest FILE", "", "Check for available update"),
            ("update history", "", "Show update history"),
            ("update show --manifest FILE [--artifact FILE]", "", "Show release manifest"),
            ("update verify --manifest FILE --artifact FILE", "", "Verify artifact against manifest"),
            ("update install (via CLI only)", "", "Install requires standalone CLI with --yes"),
        ]
