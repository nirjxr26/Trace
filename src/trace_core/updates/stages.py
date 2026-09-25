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
