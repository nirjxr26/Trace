from collections.abc import Callable
from pathlib import Path

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.ui.renderers import console, render_minimalist_table
from trace_core.updates.dto import UpdateHistoryDto
from trace_core.updates.manifest import ManifestArtifact, ReleaseManifest
from trace_core.updates.service import UpdateService

update_app = typer.Typer(name="update", help="Check, stage, and record updates.")
MANIFEST_PATH_HELP = "Manifest URL or path (default: configured TRACE_UPDATE_MANIFEST)"
ARTIFACT_PATH_HELP = "Artifact file (default: auto-download from manifest)"
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


def load_update(manifest: str | None, artifact: str | None) -> tuple[ReleaseManifest, str, str, ManifestArtifact]:
    from trace_core.updates.checker import get_installed_version, load_manifest_auto, resolve_channel
    from trace_core.updates.errors import UpdateNotAvailableError
    from trace_core.updates.policy import is_update_available, select_artifact
    from trace_core.updates.verifier import resolve_artifact

    channel = resolve_channel(None)
    m, target = load_manifest_auto(manifest, channel)
    current = get_installed_version()
    if not is_update_available(current, m):
        raise UpdateNotAvailableError(f"no update available (current {current})")
    if artifact:
        entry = resolve_artifact(m, Path(artifact))
    else:
        entry = select_artifact(m)
    return m, target, current, entry


def prepare_install(
    manifest: str | None, artifact: str | None, on_bytes: Callable[[int], None] | None = None
) -> tuple[ReleaseManifest, str, str, Path, ManifestArtifact, str]:
    from trace_core.updates.checker import ensure_artifact_path, resolve_channel
    from trace_core.updates.verifier import verify_manifest

    m, target, current, entry = load_update(manifest, artifact)
    channel = resolve_channel(None)
    artifact_path = ensure_artifact_path(m, artifact, target, on_bytes=on_bytes)
    verify_manifest(m, artifact_path)
    return m, target, current, artifact_path, entry, channel


@update_app.command("check")
def update_check(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    with capture_cli_errors("Update Check"):
        from trace_core.updates.checker import cached_check, resolve_channel, resolve_manifest_target
        from trace_core.updates.renderers import render_check_card

        channel = resolve_channel(None)
        target = resolve_manifest_target(None, channel)
        payload = cached_check(target, channel)
        if output.lower() == "json":
            from trace_core.core.ui.renderers import render_json

            render_json(payload)
            return
        render_check_card(payload, channel)


@update_app.command("history")
def update_history(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    limit: int = typer.Option(50, "--limit", min=1, max=500, help="Max rows"),
) -> None:
    with capture_cli_errors("Update History"):
        svc = UpdateService()
        rows = svc.list_history(limit=limit, offset=0)
        if output.lower() == "json":
            from trace_core.core.ui.renderers import render_json

            render_json([r.model_dump(mode="json") for r in rows])
            return
        render_minimalist_table(
            "Update History",
            HISTORY_COLUMNS,
            history_table_rows(rows),
            empty_message="No updates recorded.",
        )


@update_app.command("install")
def update_install(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str | None = typer.Option(None, "--artifact", help=ARTIFACT_PATH_HELP),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    bypass_minimum: bool = typer.Option(
        False, "--bypass-minimum", help="Override minimum-supported-version with audit"
    ),
) -> None:
    with capture_cli_errors("Update Install"):
        import sys
        import uuid

        from rich.prompt import Confirm

        from trace_core.updates.checker import ensure_artifact_path, resolve_channel
        from trace_core.updates.errors import UpdateError
        from trace_core.updates.lifecycle import UpdateLifecycle
        from trace_core.updates.renderers import UpdateProgressDisplay, render_install_summary
        from trace_core.updates.stages import Stage, StageStatus
        from trace_core.updates.verifier import verify_manifest

        channel = resolve_channel(None)
        m, target, current, entry = load_update(manifest, artifact)
        display = UpdateProgressDisplay(current=current, target=m.version, product=m.product)
        display.begin_update()
        bypass_note = ""
        if bypass_minimum:
            from trace_core.updates.policy import minimum_bypass_note

            bypass_note = minimum_bypass_note(current, m) or ""
        render_install_summary(m, current, bypass_note)
        if not yes:
            if not sys.stdin.isatty():
                raise UpdateError("refusing interactive install without --yes in non-interactive mode")
            if not Confirm.ask("Install update?"):
                console.print("[dim]Install cancelled.[/dim]")
                raise typer.Exit(0)
        try:
            display.begin_download(entry.size)
            artifact_path = ensure_artifact_path(
                m, artifact, target, on_bytes=lambda n: display.on_bytes(n, entry.size)
            )
            display.on_stage(Stage.DOWNLOAD, StageStatus.DONE)
            display.on_stage(Stage.VERIFY, StageStatus.ACTIVE)
            verify_manifest(m, artifact_path)
            display.on_stage(Stage.VERIFY, StageStatus.DONE)
            dto = UpdateLifecycle(str(uuid.uuid4())).run(
                m,
                artifact_path,
                channel=channel,
                allow_minimum_bypass=bypass_minimum,
                preverified_sha256=entry.sha256,
            )
            display.finish(dto, current)
        finally:
            display.close()
