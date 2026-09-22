from enum import StrEnum

from trace_core.updates.errors import UpdateError


class UpdateState(StrEnum):
    IDLE = "IDLE"
    CHECKING = "CHECKING"
    AVAILABLE = "AVAILABLE"
    AVAILABLE_BUT_DEFERRED = "AVAILABLE_BUT_DEFERRED"
    AVAILABLE_BUT_POLICY_BLOCKED = "AVAILABLE_BUT_POLICY_BLOCKED"
    READY_TO_INSTALL = "READY_TO_INSTALL"
    DOWNLOADING = "DOWNLOADING"
    STAGED = "STAGED"
    INSTALLING = "INSTALLING"
    MIGRATING = "MIGRATING"
    HEALTH_CHECK = "HEALTH_CHECK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


_ALLOWED: dict[UpdateState, set[UpdateState]] = {
    UpdateState.IDLE: {UpdateState.CHECKING, UpdateState.FAILED},
    UpdateState.CHECKING: {UpdateState.AVAILABLE, UpdateState.IDLE, UpdateState.FAILED},
    UpdateState.AVAILABLE: {
        UpdateState.AVAILABLE_BUT_DEFERRED,
        UpdateState.AVAILABLE_BUT_POLICY_BLOCKED,
        UpdateState.READY_TO_INSTALL,
        UpdateState.FAILED,
        UpdateState.IDLE,
    },
    UpdateState.AVAILABLE_BUT_DEFERRED: {UpdateState.AVAILABLE, UpdateState.FAILED, UpdateState.IDLE},
    UpdateState.AVAILABLE_BUT_POLICY_BLOCKED: {UpdateState.AVAILABLE, UpdateState.FAILED, UpdateState.IDLE},
    UpdateState.READY_TO_INSTALL: {UpdateState.DOWNLOADING, UpdateState.FAILED},
    UpdateState.DOWNLOADING: {UpdateState.STAGED, UpdateState.FAILED},
    UpdateState.STAGED: {UpdateState.INSTALLING, UpdateState.FAILED},
    UpdateState.INSTALLING: {UpdateState.MIGRATING, UpdateState.ROLLING_BACK, UpdateState.FAILED},
    UpdateState.MIGRATING: {UpdateState.HEALTH_CHECK, UpdateState.ROLLING_BACK, UpdateState.FAILED},
    UpdateState.HEALTH_CHECK: {UpdateState.COMPLETED, UpdateState.ROLLING_BACK, UpdateState.FAILED},
    UpdateState.ROLLING_BACK: {UpdateState.ROLLED_BACK, UpdateState.RECOVERY_REQUIRED, UpdateState.FAILED},
    UpdateState.FAILED: {UpdateState.IDLE},
    UpdateState.RECOVERY_REQUIRED: {UpdateState.IDLE},
}


def can_transition(a: UpdateState, b: UpdateState) -> bool:
    return b in _ALLOWED.get(a, set())


def assert_transition(a: UpdateState, b: UpdateState) -> None:
    if not can_transition(a, b):
        raise UpdateError(f"illegal update transition {a} -> {b}")


class UpdateChannel(StrEnum):
    STABLE = "stable"
    BETA = "beta"

    @classmethod
    def contains(cls, value: str) -> bool:
        """Single choke point for channel validation. Shared by manifest/policy."""
        return value in (cls.STABLE, cls.BETA)


class UpdateResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class UpdateFailureStage(StrEnum):
    """Single source for failure_stage values persisted in history."""

    POLICY = "policy"
    STAGING = "staging"
    HEALTH = "health"
    RECOVERY = "recovery"
    MIGRATION = "migration"

    @classmethod
    def from_state(cls, state: UpdateState) -> str:
        """Single source mapping lifecycle states to persisted stages."""
        if state in (UpdateState.CHECKING, UpdateState.AVAILABLE, UpdateState.READY_TO_INSTALL):
            return cls.POLICY
        if state in (UpdateState.DOWNLOADING, UpdateState.STAGED, UpdateState.INSTALLING):
            return cls.STAGING
        if state in (UpdateState.MIGRATING, UpdateState.HEALTH_CHECK, UpdateState.ROLLING_BACK):
            return cls.HEALTH
        return str(state).lower()
