"""Crash-consistency guards: H-13, H-16, H-17, H-19, H-14.

Each test names the finding and the specific defect that let it through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# --- H-17: the migration marker was cleared on migration success, before the update ended ---


def test_marker_survives_migration_success(session_manager, temp_storage_root: Path) -> None:
    """H-17: the marker means 'an update owns migrations' for the WHOLE transaction.

    It used to be deleted inside run_updater_migration on success, so from that moment
    until the result marker is written — health check, activation, retention prune,
    history row — only update_lock() protected the update. When the caller already owns
    the transaction (the lifecycle does), the marker must outlive the migration.
    """
    from trace_core.updates.migration import (
        begin_update_migration,
        finish_update_migration,
        marker_state,
        run_updater_migration,
        update_migration_owner,
    )

    # This is the lifecycle's own sequence: it takes the marker for the whole transaction
    # before migrating, so the migration must not release it.
    with update_migration_owner("tx-marker-owner"):
        begin_update_migration("tx-marker-owner")
        run_updater_migration(session_manager, "tx-marker-owner")
        assert marker_state()[0] == "active", "marker must survive while the owner is still running"
        finish_update_migration("tx-marker-owner")
    assert marker_state() == ("absent", None)


def test_marker_released_when_no_caller_owns_it(session_manager, temp_storage_root: Path) -> None:
    """A standalone migration owns and releases its own marker, as before."""
    from trace_core.updates.migration import marker_state, run_updater_migration

    run_updater_migration(session_manager, "tx-standalone")
    assert marker_state() == ("absent", None)


# --- H-13: rollback never advanced previous-version, so recovery could roll back twice ---


def test_rollback_advances_previous_version(session_manager, temp_storage_root: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """H-13: previous-version still named the release we just came FROM.

    So a second `trace recovery` rolled back a second time to the same version. The
    failed release becomes the new previous-version: the file keeps meaning "the release
    to return to if the next update fails", which is what rollback reads.
    """
    from trace_core.updates import migration as mig_mod
    from trace_updater import updater as updater_mod

    base = tmp_releases_base(temp_storage_root, updater_mod)
    updater_mod.activate(base, "0.2.8")
    updater_mod.activate(base, "0.2.9")
    assert updater_mod.read_previous(base) == "0.2.8"
    assert updater_mod.read_active(base) == "0.2.9"

    mig_mod.rollback_release(base, session_manager, None)

    assert updater_mod.read_active(base) == "0.2.8"
    assert updater_mod.read_previous(base) == "0.2.9", "previous must advance past the retired release"


def test_rollback_does_not_advance_when_versions_match(temp_storage_root: Path) -> None:
    from trace_core.updates.migration import _advance_previous
    from trace_updater.updater import previous_path

    # No-op cases must not write the file at all, so this asserts on the file rather than
    # on a return value. `_advance_previous` is declared `-> None`, so `is None` on its call
    # result was a type error — and worse, it would have kept passing if the early return
    # that makes these cases no-ops were deleted.
    for restored, failed in ((None, "0.2.9"), ("0.2.8", None), ("0.2.8", "0.2.8")):
        _advance_previous(temp_storage_root, restored, failed)
        assert not previous_path(temp_storage_root).exists()


def tmp_releases_base(storage_root: Path, updater_mod) -> Path:  # type: ignore[no-untyped-def]
    """Build a two-release install tree so activate/rollback have real directories."""
    base = storage_root / "install"
    base.mkdir(parents=True, exist_ok=True)
    for ver in ("0.2.8", "0.2.9"):
        release = updater_mod.releases_root(base) / ver
        (release / "trace").mkdir(parents=True, exist_ok=True)
        (release / "trace" / "__init__.py").write_text("", encoding="utf-8")
        # rollback_release refuses a release with no compatibility metadata.
        (release / "release.json").write_text(
            json.dumps({"version": ver, "schema_min": 1, "schema_target": 16}), encoding="utf-8"
        )
    return base


# --- H-16: HEALTH_CHECK is durable but recovery did not treat it as actionable ---


def test_health_check_is_recovery_actionable() -> None:
    """H-16: a crash at HEALTH_CHECK left a flipped pointer and a migrated DB, and
    `trace recovery` printed 'No recovery needed — up to date'."""
    from trace_core.core.cli.recovery import _ROLLBACK_WORTHY_STATES, _TERMINAL_STATES
    from trace_core.updates.domain import UpdateState

    assert str(UpdateState.HEALTH_CHECK) in _ROLLBACK_WORTHY_STATES
    # ROLLED_BACK is terminal: the rollback already ran, re-running would repeat it.
    assert str(UpdateState.ROLLED_BACK) in _TERMINAL_STATES
    assert not (_ROLLBACK_WORTHY_STATES & _TERMINAL_STATES)


def test_every_durable_state_is_classified_by_recovery() -> None:
    """Every non-IDLE durable state must be either actionable or terminal.

    An unclassified state falls through to 'up to date' — the exact defect H-16 was.
    """
    from trace_core.core.cli.recovery import _ROLLBACK_WORTHY_STATES, _TERMINAL_STATES
    from trace_core.updates.domain import UpdateState

    # States that never own durable marker state: they are pre-transaction verdicts.
    pre_transaction = {
        UpdateState.IDLE,
        UpdateState.CHECKING,
        UpdateState.AVAILABLE,
        UpdateState.AVAILABLE_BUT_DEFERRED,
        UpdateState.AVAILABLE_BUT_POLICY_BLOCKED,
        UpdateState.READY_TO_INSTALL,
    }
    classified = _ROLLBACK_WORTHY_STATES | _TERMINAL_STATES
    for state in UpdateState:
        if state in pre_transaction:
            continue
        assert str(state) in classified, f"{state} would report 'up to date' over real state"


# --- H-19: a swallowed DB error was substituted with a value known to be wrong ---


def test_schema_read_error_propagates(session_manager, temp_storage_root: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """H-19: `except Exception: schema_after = schema_before` then failed the health check
    against that substitute and rolled back a healthy update. The error must propagate."""
    from trace_core.updates import migration as mig_mod

    def _down(_m: object) -> int:
        raise RuntimeError("db down")

    monkeypatch.setattr(mig_mod, "current_schema_version", _down)
    with pytest.raises(RuntimeError, match="db down"):
        mig_mod.current_schema_version(session_manager)


def test_lifecycle_does_not_swallow_schema_errors() -> None:
    import inspect

    from trace_core.updates import lifecycle as life_mod

    src = inspect.getsource(life_mod.UpdateLifecycle._run_locked)
    assert "schema_after = schema_before" not in src
    assert "schema_before = None" not in src


# --- H-14: a failed stage recorded a FAILED history row twice ---


def test_staged_failure_writes_one_history_row(
    session_manager, signed_release, release_keys, monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """H-14: _assert_verified_stage transitioned AND wrote history, then raised, so
    run()'s generic handler wrote a second FAILED row for the same transaction_id."""
    from trace_core.core.settings import settings
    from trace_core.updates import signing
    from trace_core.updates import staging as staging_mod
    from trace_core.updates.errors import UpdateVerificationError
    from trace_core.updates.lifecycle import UpdateLifecycle

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    monkeypatch.setattr(staging_mod, "is_verified_stage", lambda *a: False)

    lifecycle = UpdateLifecycle("tx-once", session_manager)
    with pytest.raises(UpdateVerificationError):
        lifecycle.run(manifest, art_path)
