from collections.abc import Callable
from pathlib import Path

import typer

from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.output import SKIP_CONFIRM_HELP
from trace_core.core.ui.renderers import console, render_output
from trace_core.updates.manifest import ManifestArtifact, ReleaseManifest

update_app = typer.Typer(name="update", help="Check and install updates.")
MANIFEST_PATH_HELP = "Manifest URL or path (default: configured TRACE_UPDATE_MANIFEST)"
ARTIFACT_PATH_HELP = "Artifact file (default: auto-download from manifest)"


def load_update(manifest: str | None, artifact: str | None) -> tuple[ReleaseManifest, str, str, ManifestArtifact]:
    from trace_core.updates.checker import get_installed_version, load_manifest_auto, resolve_channel
    from trace_core.updates.policy import is_update_available, select_artifact
    from trace_core.updates.verifier import resolve_artifact

    channel = resolve_channel(None)
    m, target = load_manifest_auto(manifest, channel)
    current = get_installed_version()
    if not is_update_available(current, m):
        # Same wording as the check card: "install" with nothing new is not a failure.
        from trace_core.updates.renderers import render_up_to_date

        render_up_to_date(current, channel)
        raise typer.Exit(0)
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
        target = resolve_manifest_target(None)
        payload = cached_check(target, channel)
        render_output(output, payload, lambda: render_check_card(payload, channel))


@update_app.command("install")
def update_install(
    manifest: str | None = typer.Option(None, "--manifest", help=MANIFEST_PATH_HELP),
    artifact: str | None = typer.Option(None, "--artifact", help=ARTIFACT_PATH_HELP),
    yes: bool = typer.Option(False, "--yes", "-y", help=SKIP_CONFIRM_HELP),
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
            )
            display.finish(dto, current)
        finally:
            display.close()
