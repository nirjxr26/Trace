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


STAGE_ORDER = (Stage.DOWNLOAD, Stage.VERIFY, Stage.INSTALL, Stage.HEALTH)

STAGE_ACTIVE_LABEL = {
    Stage.DOWNLOAD: "Downloading",
    Stage.VERIFY: "Verifying",
    Stage.INSTALL: "Installing",
    Stage.HEALTH: "Checking health",
}

STAGE_DONE_LABEL = {
    Stage.DOWNLOAD: "Downloaded",
    Stage.VERIFY: "Verified",
    Stage.INSTALL: "Installed",
    Stage.HEALTH: "Health check passed",
}

STAGE_FAILED_LABEL = {
    Stage.DOWNLOAD: "Download failed",
    Stage.VERIFY: "Verification failed",
    Stage.INSTALL: "Install failed",
    Stage.HEALTH: "Health check failed",
}

_STAGE_LABEL_BY_STATUS = {
    StageStatus.ACTIVE: STAGE_ACTIVE_LABEL,
    StageStatus.DONE: STAGE_DONE_LABEL,
    StageStatus.FAILED: STAGE_FAILED_LABEL,
}


def stage_label(stage: Stage, status: StageStatus) -> str:
    """Label for one stage/status pair. Single source for the CLI and TUI stage lines."""
    return _STAGE_LABEL_BY_STATUS.get(status, STAGE_FAILED_LABEL)[stage]


STAGE_GLYPH: dict[StageStatus, str] = {
    StageStatus.DONE: "●",
    StageStatus.ACTIVE: "●",
    StageStatus.FAILED: "▲",
    StageStatus.PENDING: "◌",
}

STAGE_TOKEN: dict[StageStatus, str] = {
    StageStatus.DONE: "green",
    StageStatus.ACTIVE: "blue",
    StageStatus.FAILED: "amber",
    StageStatus.PENDING: "muted",
}


def stage_glyph(status: StageStatus) -> str:
    """One glyph per status, never colour alone. CLI and TUI share this."""
    return STAGE_GLYPH[status]


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
