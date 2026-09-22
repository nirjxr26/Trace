import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.ui.renderers import console, render_minimalist_table
from trace_core.updates.dto import UpdateHistoryDto
from trace_core.updates.policy import security_label
from trace_core.updates.service import UpdateService

update_app = typer.Typer(name="update", help="Check, stage, and record updates.")
MANIFEST_PATH_HELP = "Manifest URL or path (default: configured TRACE_UPDATE_MANIFEST)"
ARTIFACT_PATH_HELP = "Artifact file (default: auto-download from manifest)"
RESTART_REQUIRED_MESSAGE = "Trace will restart to complete this update."
HISTORY_COLUMNS: list[tuple[str, dict[str, object]]] = [
    ("From", {}),
    ("To", {}),
    ("Channel", {}),
    ("Result", {}),
    ("Rollback", {}),
]


def history_table_rows(rows: list[UpdateHistoryDto]) -> list[list[str]]:
    """Single source for history table rows. Shared by CLI and REPL shell."""
    return [[r.from_version, r.to_version, r.channel, r.result, str(r.rollback)] for r in rows]


@update_app.command("check")
def update_check(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    channel: str | None = typer.Option(None, "--channel", help="stable|beta"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    with capture_cli_errors("Update Check"):
        from trace_core.updates.checker import cached_check, resolve_channel, resolve_manifest_target

        channel = resolve_channel(channel)
        target = resolve_manifest_target(manifest, channel)
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
            HISTORY_COLUMNS,
            history_table_rows(rows),
            empty_message="No updates recorded." if offset == 0 else f"No updates at offset {offset}.",
        )


@update_app.command("show")
def update_show(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str | None = typer.Option(None, "--artifact", help=ARTIFACT_PATH_HELP),
    channel: str | None = typer.Option(None, "--channel", help="stable|beta"),
) -> None:
    with capture_cli_errors("Update Show"):
        from trace_core.updates.checker import ensure_artifact_path, load_manifest_auto, resolve_channel

        channel = resolve_channel(channel)
        m, target = load_manifest_auto(manifest, channel)
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
            from trace_core.updates.checker import ensure_artifact_path
            from trace_core.updates.verifier import verify_manifest

            verify_manifest(m, ensure_artifact_path(m, artifact, target))
            console.print("[green]Artifact verification passed.[/green]")


@update_app.command("verify")
def update_verify(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str | None = typer.Option(None, "--artifact", help=ARTIFACT_PATH_HELP),
    channel: str | None = typer.Option(None, "--channel", help="stable|beta"),
) -> None:
    with capture_cli_errors("Update Verify"):
        from trace_core.updates.checker import ensure_artifact_path, load_manifest_auto, resolve_channel
        from trace_core.updates.verifier import verify_manifest

        channel = resolve_channel(channel)
        m, target = load_manifest_auto(manifest, channel)
        verify_manifest(m, ensure_artifact_path(m, artifact, target))
        console.print("[green]Verification passed.[/green]")


@update_app.command("install")
def update_install(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str | None = typer.Option(None, "--artifact", help=ARTIFACT_PATH_HELP),
    channel: str | None = typer.Option(None, "--channel", help="stable|beta"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    bypass_minimum: bool = typer.Option(
        False, "--bypass-minimum", help="Override minimum-supported-version with audit"
    ),
) -> None:
    with capture_cli_errors("Update Install"):
        import sys
        import uuid

        from rich.prompt import Confirm

        from trace_core.updates.checker import ensure_artifact_path, load_manifest_auto, resolve_channel
        from trace_core.updates.errors import UpdateError, UpdateNotAvailableError
        from trace_core.updates.lifecycle import UpdateLifecycle
        from trace_core.updates.policy import is_update_available
        from trace_core.updates.verifier import resolve_artifact, verify_manifest

        channel = resolve_channel(channel)
        m, target = load_manifest_auto(manifest, channel)
        from trace_core.updates.checker import get_installed_version

        current = get_installed_version()
        if not is_update_available(current, m):
            raise UpdateNotAvailableError(f"no update available (current {current})")
        artifact_path = ensure_artifact_path(m, artifact, target)
        artifact_entry = resolve_artifact(m, artifact_path)
        verify_manifest(m, artifact_path)
        bypass_note = ""
        if bypass_minimum:
            from trace_core.updates.policy import minimum_bypass_note

            bypass_note = minimum_bypass_note(current, m) or ""
        console.print(f"[bold]{m.product} {m.version}[/bold] ({m.channel})")
        console.print(f"Current version: {current}")
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
        dto = UpdateLifecycle(str(uuid.uuid4())).run(
            m,
            artifact_path,
            channel=channel,
            allow_minimum_bypass=bypass_minimum,
            preverified_sha256=artifact_entry.sha256,
        )
        console.print(f"[green]Update {dto.result}: {dto.from_version} -> {dto.to_version}[/green]")
