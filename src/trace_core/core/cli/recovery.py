from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.ui.renderers import console
from trace_core.updates.errors import RecoveryBlockedError, RecoveryError


def run_recovery() -> None:
    with capture_cli_errors("Recovery"):
        _recover()


def _recovery_states() -> tuple[frozenset[str], frozenset[str]]:
    """(rollback-worthy, already-resolved) durable marker states. Single source for both lists."""
    from trace_core.updates.domain import UpdateState

    # Every durable state an update can be in when it dies mid-transaction. A crash in any
    # of these leaves work half-applied, so all of them are actionable. H-16 named
    # HEALTH_CHECK; the install/migration states had the same "reports up to date" defect.
    rollback_worthy = frozenset(
        str(state)
        for state in (
            UpdateState.DOWNLOADING,
            UpdateState.STAGED,
            UpdateState.INSTALLING,
            UpdateState.MIGRATING,
            UpdateState.HEALTH_CHECK,
            UpdateState.FAILED,
            UpdateState.ROLLING_BACK,
            UpdateState.RECOVERY_REQUIRED,
        )
    )
    # Terminal: the rollback already ran, so re-running would repeat it to the same version.
    terminal = frozenset({str(UpdateState.COMPLETED), str(UpdateState.ROLLED_BACK)})
    return rollback_worthy, terminal


_ROLLBACK_WORTHY_STATES, _TERMINAL_STATES = _recovery_states()


def _triage_update_marker(svc) -> None:  # type: ignore[no-untyped-def]
    from trace_core.updates.lock import try_update_lock
    from trace_core.updates.migration import finish_update_migration, marker_state

    state, active = marker_state()
    if state == "absent":
        return
    with try_update_lock() as held:
        if not held:
            raise RecoveryBlockedError("a live updater owns migration; retry after it finishes")
    if state == "active":
        tx = (active or {}).get("transaction_id", "unknown")
        finish_update_migration(tx)
    else:
        tx = _corrupt_marker_id()
        _clear_corrupt_marker()
    from trace_core.core.clock import now_utc
    from trace_core.updates.domain import UpdateFailureStage
    from trace_core.updates.dto import UpdateHistoryCreateDto

    svc.record_history(
        UpdateHistoryCreateDto(
            from_version="unknown",
            to_version="unknown",
            result="FAILED",
            failure_stage=UpdateFailureStage.RECOVERY,
            failure_reason=f"stale {state} update marker cleared for transaction {tx}",
            transaction_id=tx,
            started_at=now_utc(),
        )
    )
    console.print(f"[yellow]Cleared stale {state} update marker (transaction {tx}).[/yellow]")


def _corrupt_marker_id() -> str:
    import hashlib

    from trace_core.updates.migration import migration_marker_path

    try:
        digest = hashlib.sha256(migration_marker_path().read_bytes()).hexdigest()[:12]
    except OSError:
        return "corrupt-unknown"
    return f"corrupt-{digest}"


def _clear_corrupt_marker() -> None:
    from trace_core.updates.migration import migration_marker_path

    migration_marker_path().unlink(missing_ok=True)


def _recover() -> None:
    from trace_core.core.database.health import fetch_db_snapshot
    from trace_core.core.database.session import get_db
    from trace_core.updates.service import UpdateService
    from trace_updater import updater as updater_mod

    base = updater_mod.install_root()
    active = updater_mod.read_active(base)
    previous = updater_mod.read_previous(base)
    console.print(f"[dim]Active release: {active or 'unknown'}[/dim]")
    console.print(f"[dim]Previous release: {previous or 'none'}[/dim]")
    try:
        mgr = get_db(None)
        snap = fetch_db_snapshot(mgr)
    except Exception as exc:
        raise RecoveryError(f"database unreachable ({exc})") from exc
    if not snap.healthy:
        raise RecoveryError(f"database unreachable ({snap.message})")
    svc = UpdateService(mgr)
    _triage_update_marker(svc)
    from trace_core.updates.marker import marker_path, read_marker

    result_marker_path = marker_path()
    if not result_marker_path.exists():
        console.print("[dim]No update marker found.[/dim]")
    else:
        marker = read_marker()
        state = marker["state"]
        console.print(f"[dim]Marker state: {state}[/dim]")
        if state in _ROLLBACK_WORTHY_STATES:
            from trace_core.updates.migration import rollback_release

            restored = rollback_release(base, mgr, marker.get("backup_path"))
            console.print(f"[green]Restored previous release {restored}.[/green]")
            return
        if state in _TERMINAL_STATES:
            # H-13/H-16: HEALTH_CHECK and ROLLED_BACK are both durable states that this
            # list did not name, so `trace recovery` printed "No recovery needed — up to
            # date" over a genuinely half-applied update. HEALTH_CHECK is included
            # because the pointer is already flipped and the DB already migrated there.
            # ROLLED_BACK is terminal: the rollback already ran, so re-running would roll
            # back a second time to the same version.
            console.print(f"[dim]Update already resolved as {state}; nothing to recover.[/dim]")
            return
    if snap.pending:
        console.print(f"[yellow]{len(snap.pending)} pending migration(s).[/yellow]")
        console.print("Run `trace db migrate` to apply.")
    else:
        console.print("[green]No recovery needed — up to date.[/green]")
