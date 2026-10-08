import time

from rich.live import Live
from rich.text import Text

from trace_core.core.ui.renderers import closing_block, console, safe_text, step_line
from trace_core.updates.dto import UpdateResultDto
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.stages import (
    STAGE_ORDER,
    ProgressCallback,
    Stage,
    StageStatus,
    format_mb,
    format_speed,
    stage_glyph,
    stage_is_spinning,
    stage_label,
)

BAR_WIDTH = 28
DRAW_INTERVAL = 0.25
RESTART_REQUIRED_MESSAGE = "Trace will restart to complete this update."

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
    console.print("[dim]See `trace update history` for past attempts.[/dim]")


def render_up_to_date(current: str, channel: str) -> None:
    """Single source for the 'nothing newer' line. Shared by check, install and the REPL."""
    console.print(f"[green]✓ You're up to date[/green] — Trace v{safe_text(current)} ({safe_text(channel)})")


def render_check_card(payload: dict, channel: str) -> None:
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


def render_install_summary(manifest: ReleaseManifest, current: str, bypass_note: str) -> None:
    """Pre-flight facts only.

    The target version and the step list are deliberately absent: `begin_update` titles
    the region with the version, and the four steps are printed as live rows a moment
    later. Both used to appear here as well, so one screen stated each of them three times.
    """
    console.print("")
    console.print("Update available")
    console.print(f"Product: {safe_text(manifest.product)}")
    console.print(f"Current: v{safe_text(current)}")
    if manifest.restart_required:
        console.print("Restart: Required")
    if bypass_note:
        console.print(f"[yellow]Override: {safe_text(bypass_note)}[/yellow]")


class UpdateProgressDisplay(ProgressCallback):
    def __init__(self, current: str, target: str, product: str = "Trace") -> None:
        self.current = current
        self.target = target
        self.product = product
        self.statuses = {stage: StageStatus.PENDING for stage in STAGE_ORDER}
        self.download_total = 0
        self.download_read = 0
        self.download_started = 0.0
        self.tty = console.is_terminal
        self._live: Live | None = None
        self._last_draw = 0.0
        self._spin = 0
        self._active_since: float | None = None

    def begin_update(self) -> None:
        console.print("")
        # product/target/current come from the (signature-verified) manifest, but a
        # verified manifest still controls these strings — escape before markup.
        console.print(f"Updating {safe_text(self.product)} to v{safe_text(self.target)}")
        console.print("")
        if self.tty:
            # transient=True erases the live region on stop, so the single final frame
            # printed by finish() is the only copy. transient=False left Rich's own copy
            # on screen and printed a second one over it.
            self._live = Live(self._frame(), console=console, transient=True, refresh_per_second=8)
            self._live.start()

    def begin_download(self, total: int) -> None:
        self.download_total = total
        self.download_read = 0
        self.download_started = time.monotonic()
        self.statuses[Stage.DOWNLOAD] = StageStatus.ACTIVE
        self._active_since = self.download_started
        self._draw(force=True)

    def on_bytes(self, read: int, total: int) -> None:
        self.download_read = read
        self.download_total = total
        now = time.monotonic()
        if now - self._last_draw >= DRAW_INTERVAL:
            self._draw()

    def on_stage(self, stage: Stage, status: StageStatus) -> None:
        self.statuses[stage] = status
        if status is StageStatus.ACTIVE:
            self._active_since = time.monotonic()
        elif status is not StageStatus.PENDING:
            self._active_since = None
        if not self.tty and status is not StageStatus.PENDING:
            label = stage_label(stage)
            if stage is Stage.DOWNLOAD and self.download_total > 0:
                label = f"{label} — {format_mb(self.download_read)} of {format_mb(self.download_total)}"
            console.print(step_line(status, label))
        self._draw(force=True)

    def finish(self, dto: UpdateResultDto, current: str) -> None:
        if dto.result == "SUCCESS":
            for stage in STAGE_ORDER:
                self.statuses[stage] = StageStatus.DONE
            self._stop()
            self._print_final_frame()
            closing_block(
                "✓",
                f"Trace updated to v{safe_text(dto.to_version)}",
                "Run `trace case list` to resume work.",
            )
            return
        if dto.rollback:
            self.statuses[Stage.DOWNLOAD] = StageStatus.DONE
            self.statuses[Stage.VERIFY] = StageStatus.DONE
            self.statuses[Stage.INSTALL] = StageStatus.FAILED
            self._stop()
            self._print_final_frame()
            closing_block(
                "▲", "The update was rolled back.", f"Current version: v{safe_text(current)}", token="warning"
            )
            return
        failed_stage = _FAILED_STAGE.get(str(dto.failure_stage or ""))
        if failed_stage is not None:
            self.statuses[failed_stage] = StageStatus.FAILED
        self._stop()
        self._print_final_frame()
        closing_block("✕", "Update failed", "Run `trace update history` for details.", token="danger")
        # Plain string arg, not an f-string: Rich only interprets markup in the
        # format string, but escape anyway so a crafted reason can never render as markup.
        console.print(safe_text(dto.failure_reason or "") or "Update did not complete.")
        console.print(f"Current version: v{safe_text(current)}")
        console.print("")

    def _print_final_frame(self) -> None:
        """The one surviving copy of the step block. Live is transient, so it has already
        erased itself; printing here is what leaves the finished block on screen."""
        if any(status is not StageStatus.PENDING for status in self.statuses.values()):
            console.print(self._frame())
            console.print("")

    def _frame(self) -> Text:
        body = Text()
        if self.statuses[Stage.DOWNLOAD] == StageStatus.ACTIVE and self.download_total > 0:
            filled = min(BAR_WIDTH, self.download_read * BAR_WIDTH // self.download_total)
            body.append("Downloading\n")
            body.append("[" + "█" * filled + "░" * (BAR_WIDTH - filled) + "]", style="green")
            body.append(f" {self.download_read * 100 // self.download_total}%\n")
            speed, eta = format_speed(self.download_read, self.download_total, time.monotonic() - self.download_started)
            body.append(f"{format_mb(self.download_read)} / {format_mb(self.download_total)}   {speed}   ETA {eta}\n")
            body.append("\n")
        for stage in STAGE_ORDER:
            status = self.statuses[stage]
            body.append_text(step_line(status, stage_label(stage), glyph=stage_glyph(status, self._spin)))
            body.append("\n")
        return body

    def _draw(self, force: bool = False) -> None:
        if not self.tty or self._live is None:
            return
        now = time.monotonic()
        if not force and now - self._last_draw < DRAW_INTERVAL:
            return
        self._last_draw = now
        # The spinner advances once per drawn frame, and only once the running step has
        # been going long enough to be worth animating. Two rows can never share a frame,
        # one frame never advances twice, and a step that finishes immediately never
        # shows a frame of motion that reads as a flicker.
        if stage_is_spinning(self._active_since, now):
            self._spin += 1
        self._live.update(self._frame())

    def _stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def close(self) -> None:
        self._stop()
