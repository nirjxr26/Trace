import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.ui.renderers import console, render_minimalist_table
from trace_core.updates.policy import security_label
from trace_core.updates.service import UpdateService

update_app = typer.Typer(name="update", help="Check, stage, and record updates.")
MANIFEST_PATH_HELP = "Path to release manifest JSON"
ARTIFACT_PATH_HELP = "Path to artifact file"
RESTART_REQUIRED_MESSAGE = "Trace will restart to complete this update."


@update_app.command("check")
def update_check(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    channel: str = typer.Option("stable", "--channel", help="stable|beta"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    with capture_cli_errors("Update Check"):
        from trace_core.core.settings import settings
        from trace_core.updates.checker import cached_check
        from trace_core.updates.errors import UpdateError

        target = manifest or settings.update_manifest
        if not target:
            raise UpdateError("no update manifest configured (pass --manifest or set TRACE_UPDATE_MANIFEST)")
        payload = cached_check(target, channel)
        if output.lower() == "json":
            from trace_core.core.ui.renderers import render_json

            render_json(payload)
            return
        if not payload["available"]:
            console.print(f"[dim]Up to date ({payload['current']}, {channel}).[/dim]")
            return
        if payload["security_update"]:
            console.print("[bold]Security update[/bold]")
        if payload["minimum_supported_version"]:
            console.print(f"Minimum supported version: {payload['minimum_supported_version']}")
        if payload["restart_required"]:
            console.print(RESTART_REQUIRED_MESSAGE)
        if not payload["installable"]:
            console.print(
                f"[yellow]Update {payload['target']} available but deferred: {payload['block_reason']}[/yellow]"
            )
            return
        console.print(f"[green]Update {payload['target']} available[/green] — current {payload['current']} ({channel})")


@update_app.command("history")
def update_history(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    limit: int = typer.Option(50, "--limit", min=1, max=500, help="Max rows"),
    offset: int = typer.Option(0, "--offset", min=0, help="Rows to skip"),
) -> None:
    with capture_cli_errors("Update History"):
        svc = UpdateService()
        rows = svc.list_history(limit=limit, offset=offset)
        if output.lower() == "json":
            from trace_core.core.ui.renderers import render_json

            render_json([r.model_dump(mode="json") for r in rows])
            return
        render_minimalist_table(
            "Update History",
            [("From", {}), ("To", {}), ("Channel", {}), ("Result", {}), ("Rollback", {})],
            [[r.from_version, r.to_version, r.channel, r.result, str(r.rollback)] for r in rows],
            empty_message="No updates recorded.",
        )


@update_app.command("show")
def update_show(
    manifest: str = typer.Option(..., "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str = typer.Option(None, "--artifact", help=ARTIFACT_PATH_HELP),
) -> None:
    with capture_cli_errors("Update Show"):
        from pathlib import Path

        from trace_core.updates.manifest import load_manifest

        m = load_manifest(manifest)
        console.print(f"[bold]{m.product} {m.version}[/bold] ({m.channel})")
        if not artifact:
            console.print("[dim]Unverified manifest content — shown before verification.[/dim]")
        if m.notes:
            console.print(m.notes)
        if m.security_update:
            console.print(security_label(m) or "Security update")
        if m.restart_required:
            console.print(RESTART_REQUIRED_MESSAGE)
        if artifact:
            from trace_core.updates.verifier import verify_manifest

            verify_manifest(m, Path(artifact))
            console.print("[green]Artifact verification passed.[/green]")


@update_app.command("verify")
def update_verify(
    manifest: str = typer.Option(..., "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str = typer.Option(..., "--artifact", help=ARTIFACT_PATH_HELP),
) -> None:
    with capture_cli_errors("Update Verify"):
        from pathlib import Path

        from trace_core.updates.manifest import load_manifest
        from trace_core.updates.verifier import verify_manifest

        m = load_manifest(manifest)
        verify_manifest(m, Path(artifact))
        console.print("[green]Verification passed.[/green]")


@update_app.command("install")
def update_install(
    manifest: str = typer.Option(..., "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str = typer.Option(..., "--artifact", help=ARTIFACT_PATH_HELP),
    channel: str = typer.Option("stable", "--channel", help="stable|beta"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    bypass_minimum: bool = typer.Option(
        False, "--bypass-minimum", help="Override minimum-supported-version with audit"
    ),
) -> None:
    with capture_cli_errors("Update Install"):
        import sys
        import uuid
        from pathlib import Path

        from rich.prompt import Confirm

        from trace_core.core.settings import settings
        from trace_core.updates.errors import UpdateError, UpdateNotAvailableError
        from trace_core.updates.lifecycle import UpdateLifecycle
        from trace_core.updates.manifest import load_manifest
        from trace_core.updates.policy import is_update_available, select_artifact
        from trace_core.updates.verifier import verify_manifest

        m = load_manifest(manifest)
        if not is_update_available(settings.version, m):
            raise UpdateNotAvailableError(f"no update available (current {settings.version})")
        artifact_entry = select_artifact(m)
        verify_manifest(m, Path(artifact))
        bypass_note = ""
        if bypass_minimum:
            from trace_core.updates.policy import minimum_bypass_note

            bypass_note = minimum_bypass_note(settings.version, m) or "minimum check passed; flag recorded"
        console.print(f"[bold]{m.product} {m.version}[/bold] ({m.channel})")
        console.print(f"Current version: {settings.version}")
        console.print(f"Target version: {m.version}")
        console.print("Release signature: VERIFIED")
        console.print(f"Artifact integrity: VERIFIED ({artifact_entry.sha256[:16]}…) ")
        console.print(f"Signing identity: TRUSTED ({m.signing_key_id})")
        if m.security_update:
            console.print("Security update")
        if m.restart_required:
            console.print(RESTART_REQUIRED_MESSAGE)
        if m.schema_target is not None:
            console.print(f"Migration: schema -> {m.schema_target}")
        if bypass_note:
            console.print(f"[yellow]Override: {bypass_note}[/yellow]")
        if not yes:
            if not sys.stdin.isatty():
                raise UpdateError("refusing interactive install without --yes in non-interactive mode")
            if not Confirm.ask("Install update?"):
                console.print("[dim]Install cancelled.[/dim]")
                raise typer.Exit(0)
        dto = UpdateLifecycle(str(uuid.uuid4())).run(m, Path(artifact), channel, allow_minimum_bypass=bypass_minimum)
        console.print(f"[green]Update {dto.result}: {dto.from_version} -> {dto.to_version}[/green]")
