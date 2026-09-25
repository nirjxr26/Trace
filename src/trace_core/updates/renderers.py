import time

from rich.live import Live
from rich.text import Text

from trace_core.core.ui.renderers import console
from trace_core.updates.dto import UpdateHistoryCreateDto
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.stages import (
    STAGE_ACTIVE_LABEL,
    STAGE_DONE_LABEL,
    STAGE_ORDER,
    ProgressCallback,
    Stage,
    StageStatus,
    format_mb,
    format_speed,
)

BAR_WIDTH = 28
DRAW_INTERVAL = 0.25
RESTART_REQUIRED_MESSAGE = "Trace will restart to complete this update."

_STAGE_GLYPH = {
    StageStatus.DONE: "✓",
    StageStatus.ACTIVE: "◌",
    StageStatus.FAILED: "✕",
}

_STAGE_STYLE = {
    StageStatus.DONE: "green",
    StageStatus.ACTIVE: "yellow",
    StageStatus.FAILED: "red",
}

_FAILED_STAGE = {
    "staging": Stage.VERIFY,
    "health": Stage.HEALTH,
    "migration": Stage.INSTALL,
    "recovery": Stage.HEALTH,
}


def render_check_blocked(payload: dict) -> None:
    console.print(f"[yellow]Update {payload['target']} available but deferred: {payload['block_reason']}[/yellow]")
    if payload.get("notes"):
        console.print(payload["notes"])


def render_check_card(payload: dict, channel: str) -> None:
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
        render_check_blocked(payload)
        return
    console.print(f"[green]Update {payload['target']} available[/green] — current {payload['current']} ({channel})")


def render_install_summary(manifest: ReleaseManifest, current: str, bypass_note: str) -> None:
    console.print("Update available")
    console.print(f"Product: {manifest.product}")
    console.print(f"Current: v{current}")
    console.print(f"Target:  v{manifest.version}")
    console.print("Security: Verified")
    if manifest.restart_required:
        console.print("Restart: Required")
    if bypass_note:
        console.print(f"[yellow]Override: {bypass_note}[/yellow]")


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

    def begin_update(self) -> None:
        console.print(f"Updating {self.product} v{self.current} → v{self.target}")
        console.print()
        if self.tty:
            self._live = Live(self._frame(), console=console, transient=False, refresh_per_second=4)
            self._live.start()

    def begin_download(self, total: int) -> None:
        self.download_total = total
        self.download_read = 0
        self.download_started = time.monotonic()
        self.statuses[Stage.DOWNLOAD] = StageStatus.ACTIVE
        if not self.tty:
            console.print("Downloading")
        self._draw(force=True)

    def on_bytes(self, read: int, total: int) -> None:
        self.download_read = read
        self.download_total = total
        now = time.monotonic()
        if now - self._last_draw >= DRAW_INTERVAL:
            self._draw()

    def on_stage(self, stage: Stage, status: StageStatus) -> None:
        self.statuses[stage] = status
        if not self.tty and status in (StageStatus.DONE, StageStatus.FAILED):
            if stage == Stage.DOWNLOAD and status == StageStatus.DONE:
                console.print(f"Downloaded {format_mb(self.download_read)} / {format_mb(self.download_total)}")
            console.print(self._stage_line(stage, status))
        self._draw(force=True)

    def finish(self, dto: UpdateHistoryCreateDto, current: str) -> None:
        if dto.result == "SUCCESS":
            for stage in STAGE_ORDER:
                self.statuses[stage] = StageStatus.DONE
            self._stop()
            console.print(self._frame())
            console.print()
            console.print("Trace updated successfully.")
            console.print()
            console.print(f"v{dto.from_version} → v{dto.to_version}")
            return
        if dto.rollback:
            self.statuses[Stage.DOWNLOAD] = StageStatus.DONE
            self.statuses[Stage.VERIFY] = StageStatus.DONE
            self.statuses[Stage.INSTALL] = StageStatus.FAILED
            self._stop()
            console.print(self._frame())
            console.print()
            console.print("The update was rolled back.")
            console.print()
            console.print(f"Current version: v{current}")
            return
        failed_stage = _FAILED_STAGE.get(str(dto.failure_stage or ""))
        if failed_stage is not None:
            self.statuses[failed_stage] = StageStatus.FAILED
        self._stop()
        if any(status != StageStatus.PENDING for status in self.statuses.values()):
            console.print(self._frame())
            console.print()
        console.print("[red]✕ Update failed[/red]")
        console.print()
        console.print(dto.failure_reason or "Update did not complete.")
        console.print()
        console.print(f"Current version: v{current}")
        console.print()
        console.print("Run `trace update history` for details.")

    def _stage_line(self, stage: Stage, status: StageStatus) -> str:
        if status == StageStatus.DONE:
            return f"{_STAGE_GLYPH[status]} {STAGE_DONE_LABEL[stage]}"
        if status == StageStatus.ACTIVE:
            return f"{_STAGE_GLYPH[status]} {STAGE_ACTIVE_LABEL[stage]}"
        return f"{_STAGE_GLYPH[status]} {STAGE_DONE_LABEL[stage]}"

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
            if status == StageStatus.PENDING:
                continue
            body.append(self._stage_line(stage, status) + "\n", style=_STAGE_STYLE[status])
        return body

    def _draw(self, force: bool = False) -> None:
        if not self.tty or self._live is None:
            return
        now = time.monotonic()
        if not force and now - self._last_draw < DRAW_INTERVAL:
            return
        self._last_draw = now
        self._live.update(self._frame())

    def _stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def close(self) -> None:
        self._stop()
