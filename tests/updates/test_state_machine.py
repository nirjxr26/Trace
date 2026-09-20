import pytest

from trace_core.updates.domain import UpdateState, assert_transition, can_transition
from trace_core.updates.errors import UpdateError


def test_happy_path_walk():
    path = [
        UpdateState.IDLE,
        UpdateState.CHECKING,
        UpdateState.AVAILABLE,
        UpdateState.READY_TO_INSTALL,
        UpdateState.DOWNLOADING,
        UpdateState.STAGED,
        UpdateState.INSTALLING,
        UpdateState.MIGRATING,
        UpdateState.HEALTH_CHECK,
        UpdateState.COMPLETED,
    ]
    for a, b in zip(path, path[1:]):
        assert can_transition(a, b) is True
        assert_transition(a, b)


def test_deferred_and_rollback_branches():
    assert can_transition(UpdateState.AVAILABLE, UpdateState.AVAILABLE_BUT_DEFERRED)
    assert can_transition(UpdateState.AVAILABLE, UpdateState.AVAILABLE_BUT_POLICY_BLOCKED)
    assert can_transition(UpdateState.HEALTH_CHECK, UpdateState.ROLLING_BACK)
    assert can_transition(UpdateState.ROLLING_BACK, UpdateState.ROLLED_BACK)
    assert can_transition(UpdateState.ROLLING_BACK, UpdateState.RECOVERY_REQUIRED)


@pytest.mark.parametrize(
    "a,b",
    [
        (UpdateState.IDLE, UpdateState.COMPLETED),
        (UpdateState.AVAILABLE, UpdateState.INSTALLING),
        (UpdateState.COMPLETED, UpdateState.IDLE),
        (UpdateState.FAILED, UpdateState.AVAILABLE),
        (UpdateState.STAGED, UpdateState.MIGRATING),
        (UpdateState.ROLLED_BACK, UpdateState.IDLE),
    ],
)
def test_illegal_transitions_fail(a, b):
    assert can_transition(a, b) is False
    with pytest.raises(UpdateError):
        assert_transition(a, b)


def test_lifecycle_persists_state_for_restart(session_manager, temp_storage_root):
    from trace_core.updates.lifecycle import UpdateLifecycle
    from trace_core.updates.service import UpdateService

    svc = UpdateService(session_manager)
    life = UpdateLifecycle("tx-state-1", svc)
    life.transition(UpdateState.CHECKING)
    life.transition(UpdateState.AVAILABLE)
    recovered = UpdateLifecycle.load("tx-state-1", svc)
    assert recovered.state == UpdateState.AVAILABLE
    with pytest.raises(UpdateError):
        UpdateLifecycle.load("tx-missing", svc)
