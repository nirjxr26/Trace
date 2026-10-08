from enum import StrEnum
from typing import Protocol

from trace_core.updates.domain import UpdateState


class Stage(StrEnum):
    DOWNLOAD = "download"
    VERIFY = "verify"
    INSTALL = "install"
    HEALTH = "health"


class StageStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


STAGE_ORDER = (Stage.VERIFY, Stage.DOWNLOAD, Stage.INSTALL, Stage.HEALTH)

STAGE_LABEL: dict[Stage, str] = {
    Stage.VERIFY: "Verifying",
    Stage.DOWNLOAD: "Downloading",
    Stage.INSTALL: "Installing",
    Stage.HEALTH: "Finishing setup",
}

SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

SPIN_DELAY_SECONDS = 0.5

STAGE_GLYPH: dict[StageStatus, str] = {
    StageStatus.DONE: "●",
    StageStatus.ACTIVE: SPIN_FRAMES[0],
    StageStatus.FAILED: "✕",
    StageStatus.PENDING: "▲",
}

STAGE_TOKEN: dict[StageStatus, str] = {
    StageStatus.DONE: "green",
    StageStatus.ACTIVE: "green",
    StageStatus.FAILED: "red",
    StageStatus.PENDING: "muted",
}


def stage_label(stage: Stage) -> str:
    """Label for one stage. The name does not change with status: the glyph and colour
    already say what state it is in, and a status-dependent label would repeat that.

    This map used to exist three times over (active/done/failed) with identical
    contents, which is what let the three surfaces drift apart unnoticed.
    """
    return STAGE_LABEL[stage]


def stage_glyph(status: StageStatus, frame: int = 0) -> str:
    """Glyph for one status; an animating surface passes `frame` to get the next spinner
    frame instead of mutating shared state to get it."""
    if status is StageStatus.ACTIVE:
        return SPIN_FRAMES[frame % len(SPIN_FRAMES)]
    return STAGE_GLYPH[status]


def stage_is_spinning(active_since: float | None, now: float) -> bool:
    """A step only animates once it has been running long enough to be worth watching.

    Below the threshold the glyph sits still, so a step that finishes in a few tens of
    milliseconds never appears as a spinning one — the animation would have been a single
    frame of motion that reads as a glitch rather than as progress.
    """
    if active_since is None:
        return False
    return (now - active_since) >= SPIN_DELAY_SECONDS


def stage_token(status: StageStatus) -> str:
    return STAGE_TOKEN[status]


def stage_from_state(state: UpdateState) -> Stage | None:
    if state == UpdateState.DOWNLOADING:
        return Stage.DOWNLOAD
    if state == UpdateState.STAGED:
        return Stage.VERIFY
    if state in (UpdateState.INSTALLING, UpdateState.MIGRATING):
        return Stage.INSTALL
    if state == UpdateState.HEALTH_CHECK:
        return Stage.HEALTH
    if state in (UpdateState.ROLLING_BACK, UpdateState.ROLLED_BACK, UpdateState.RECOVERY_REQUIRED):
        return Stage.INSTALL
    return None


class ProgressCallback(Protocol):
    def on_bytes(self, read: int, total: int) -> None: ...
    def on_stage(self, stage: Stage, status: StageStatus) -> None: ...


class SilentProgress:
    def on_bytes(self, read: int, total: int) -> None:
        _ = (read, total)

    def on_stage(self, stage: Stage, status: StageStatus) -> None:
        _ = (stage, status)


SILENT = SilentProgress()


def format_mb(count: int) -> str:
    return f"{count / (1 << 20):.1f} MB"


def format_speed(read: int, total: int, elapsed: float) -> tuple[str, str]:
    if elapsed <= 0 or read <= 0:
        return "--", "--"
    speed = read / elapsed / (1 << 20)
    remaining = total - read
    if remaining <= 0:
        return f"{speed:.1f} MB/s", "0s"
    eta = remaining / (read / elapsed)
    if eta < 60:
        eta_text = f"{eta:.0f}s"
    else:
        eta_text = f"{eta // 60:.0f}m {eta % 60:.0f}s"
    return f"{speed:.1f} MB/s", eta_text
