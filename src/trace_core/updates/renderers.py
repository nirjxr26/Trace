from rich.live import Live
from thothspinner.rich import ThothSpinner

from trace_core.core.ui.renderers import closing_block, console, safe_text, step_line
from trace_core.core.ui.theme import THEME_HEX
from trace_core.updates.domain import UpdateFailureStage
from trace_core.updates.dto import UpdateResultDto
from trace_core.updates.stages import (
    STAGE_ORDER,
    ProgressCallback,
    Stage,
    StageStatus,
    format_mb,
    stage_label,
)

DIM = THEME_HEX["muted"]
SHIMMER_HIGHLIGHT = THEME_HEX["title"]
SHIMMER_WIDTH = 7
SHIMMER_SPEED = 1.0
RESTART_REQUIRED_MESSAGE = "Trace will restart to complete this update."
UPDATE_INSTALLED_MESSAGE = "Update installed successfully. Restart to view changes."

_FAILED_STAGE = {
    "staging": Stage.VERIFY,
    "health": Stage.HEALTH,
    "migration": Stage.INSTALL,
    "recovery": Stage.HEALTH,
}


def render_check_blocked(payload: dict) -> None:
    # Manifest fields are untrusted until verified: safe_text sanitizes AND escapes
    # before Rich interprets the f-string (sanitize_terminal alone leaves [markup] live).
    console.print(
        f"[yellow]Update {safe_text(payload['target'])} available but deferred: {safe_text(payload['block_reason'])}[/yellow]"
    )
    if payload.get("notes"):
        console.print(safe_text(payload["notes"]))


def render_up_to_date(current: str, channel: str) -> None:
    """Single source for the 'nothing newer' line. Shared by check, install and the REPL."""
    console.print(f"[green]✓ You're up to date[/green] — Trace v{safe_text(current)} ({safe_text(channel)})")


def render_version_unknown(problem: str) -> None:
    """The pointer could not be read, so "up to date" cannot be claimed. Without this the
    fallback package version was reported as the installed one."""
    console.print(f"[yellow]Couldn't tell which version is installed[/yellow] — {safe_text(problem)}")
    console.print("[dim]Nothing was changed. Run `trace recovery` to put the version pointer back.[/dim]")


def render_check_card(payload: dict, channel: str) -> None:
    problem = payload.get("version_problem")
    if problem:
        render_version_unknown(str(problem))
        return
    if not payload["available"]:
        render_up_to_date(str(payload["current"]), channel)
        return
    if payload["security_update"]:
        console.print("[bold]Security update[/bold]")
    if payload["minimum_supported_version"]:
        console.print(f"Minimum supported version: {safe_text(payload['minimum_supported_version'])}")
    if payload["restart_required"]:
        console.print(RESTART_REQUIRED_MESSAGE)
    if not payload["installable"]:
        render_check_blocked(payload)
        return
    console.print(
        f"[green]Update {safe_text(payload['target'])} available[/green] — current {safe_text(payload['current'])} ({channel})"
    )
    console.print(
        "[dim]Run `trace update install` to download, verify the signature, install, and run a health check.[/dim]"
    )


def _active_version() -> str | None:
    """The release the pointer names right now, or None when it cannot be read. An
    unreadable pointer is not the same as the pre-update version."""
    from trace_updater import updater as updater_mod

    try:
        return updater_mod.read_active(updater_mod.install_root())
    except Exception:
        return None


def _needs_recovery(dto: UpdateResultDto) -> bool:
    """Whether `trace recovery` is the right next step for this failure.

    `failure_stage == RECOVERY` is never produced by any code path — both RECOVERY_REQUIRED
    exits record HEALTH or ACTIVATION — so gating on it meant the user who most needed to run
    recovery was never told.
    """
    stage = str(dto.failure_stage or "")
    return stage in {UpdateFailureStage.RECOVERY, UpdateFailureStage.ACTIVATION, UpdateFailureStage.HEALTH}


class UpdateProgressDisplay(ProgressCallback):
    def __init__(self, current: str, target: str, product: str = "Trace") -> None:
        self.current = current
        self.target = target
        self.product = product
        self.statuses = {stage: StageStatus.PENDING for stage in STAGE_ORDER}
        self.download_total = 0
        self.download_read = 0
        self.tty = console.is_terminal
        self._live: Live | None = None
        self._spinner: ThothSpinner | None = None

    def begin_update(self) -> None:
        console.print("")
        console.print("Updating Trace...")
        console.print("")
        if not self.tty:
            return
        self._spinner = ThothSpinner(
            spinner_style="npm_dots",
            message_text=f"Installing {safe_text(self.product)} v{safe_text(self.target)}",
            message_shimmer=True,
        )
        self._spinner.set_shimmer_direction(direction="left-to-right")
        # The hint advertises an esc-to-cancel this CLI does not implement.
        self._spinner.get_component("hint").visible = False
        self._spinner.get_component("timer").visible = False
        self._spinner.get_component("progress").visible = False
        # The widget ships an amber highlight that is not a colour this product uses. The line
        # reads dim with a brighter band travelling across it, both from the shared theme
        # so the CLI cannot drift away from the TUI.
        message = self._spinner.get_component("message")
        message.color = DIM
        message.shimmer_light_color = SHIMMER_HIGHLIGHT
        message.shimmer_width = SHIMMER_WIDTH
        message.shimmer_speed = SHIMMER_SPEED
        self._spinner.get_component("spinner").color = DIM
        # message_text only seeds a rotating list the component then cycles through on
        # its own, so the line has to be pinned or it drifts to unrelated text.
        self._spinner.set_message_pinned(text=f"Installing {safe_text(self.product)} v{safe_text(self.target)}")
        # transient=True erases the live region on stop, so the closing block is the
        # only surviving copy and nothing is printed twice.
        self._live = Live(self._spinner, console=console, transient=True, refresh_per_second=12)
        self._live.start()
        self._spinner.start()

    def begin_download(self, total: int) -> None:
        self.download_total = total
        self.download_read = 0
        self.statuses[Stage.DOWNLOAD] = StageStatus.ACTIVE

    def on_bytes(self, read: int, total: int) -> None:
        self.download_read = read
        self.download_total = total

    def on_stage(self, stage: Stage, status: StageStatus) -> None:
        self.statuses[stage] = status
        if not self.tty and status is not StageStatus.PENDING:
            label = stage_label(stage)
            if stage is Stage.DOWNLOAD and self.download_total > 0:
                label = f"{label} — {format_mb(self.download_read)} of {format_mb(self.download_total)}"
            console.print(step_line(status, label))

    def _show_stage(self, stage: Stage) -> None:
        if self._spinner is not None:
            self._spinner.set_message_pinned(text=f"Installing {safe_text(self.product)} v{safe_text(self.target)}")

    def finish(self, dto: UpdateResultDto, current: str) -> None:
        # `current` is the version captured before the update ran. After the pointer flips,
        # saying "Still on v<current>" names a release that is no longer active.
        active = _active_version()
        if active is None:
            version_note = (
                f"Active release: could not be read. The release before this update was v{safe_text(current)}."
            )
        elif active == current:
            version_note = f"Still on v{safe_text(active)}."
        else:
            version_note = f"Active release is v{safe_text(active)}; it was v{safe_text(current)} before the update."
        if dto.result == "SUCCESS":
            for stage in STAGE_ORDER:
                self.statuses[stage] = StageStatus.DONE
            self._stop()
            closing_block(
                "✓",
                UPDATE_INSTALLED_MESSAGE,
                token="title",
            )
            return
        if dto.rollback:
            self.statuses[Stage.DOWNLOAD] = StageStatus.DONE
            self.statuses[Stage.VERIFY] = StageStatus.DONE
            self.statuses[Stage.INSTALL] = StageStatus.FAILED
            self._stop()
            closing_block("▲", "The update was rolled back.", version_note, token="warning")
            return
        failed_stage = _FAILED_STAGE.get(str(dto.failure_stage or ""))
        if failed_stage is not None:
            self.statuses[failed_stage] = StageStatus.FAILED
        self._stop()
        self._print_failed_stages()
        closing_block("✕", "Update failed", None, token="danger")
        # Plain string arg, not an f-string: Rich only interprets markup in the
        # format string, but escape anyway so a crafted reason can never render as markup.
        console.print(safe_text(dto.failure_reason or "") or "The update did not finish.")
        console.print(version_note)
        console.print(
            "[yellow]Run `trace recovery` to finish putting things back.[/yellow]"
            if _needs_recovery(dto)
            else "[dim]Run `trace recovery` if this did not settle.[/dim]"
        )
        console.print("")

    def _print_failed_stages(self) -> None:
        """Which stage failed was shown by the stage block the spinner replaced."""
        failed = [stage for stage in STAGE_ORDER if self.statuses[stage] is StageStatus.FAILED]
        if not failed:
            return
        for stage in failed:
            console.print(step_line(StageStatus.FAILED, stage_label(stage)))
        console.print("")

    def _stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._spinner = None

    def close(self) -> None:
        self._stop()
