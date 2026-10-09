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


def _triage_update_marker() -> None:
    from trace_core.updates.lock import try_update_lock
    from trace_core.updates.migration import finish_update_migration, marker_state

    state, active = marker_state()
    if state == "absent":
        return
    with try_update_lock() as held:
        if not held:
            raise RecoveryBlockedError("a live updater owns migration; retry after it finishes")
    if state == "unreadable":
        # Holding the lock proves no updater is running. It does not prove this marker is
        # stale, and it is the only record that an update owned migrations. Deleting it
        # would destroy evidence the operator needs, so it stays.
        raise RecoveryError(
            "could not read the update marker, so it could not be cleared. It was left in place. "
            "Close anything using this install and retry, or inspect the marker file."
        )
    if state == "active":
        tx = (active or {}).get("transaction_id")
        if not tx:
            raise RecoveryError("update marker names no transaction; left in place for inspection")
        finish_update_migration(tx)
        console.print(f"[yellow]Cleared the unfinished update marker for transaction {tx}.[/yellow]")
        return
    _clear_corrupt_marker()
    console.print(
        "[yellow]Cleared a corrupt update marker. Its contents could not be read, so it carried "
        "no recoverable transaction id.[/yellow]"
    )


def _clear_corrupt_marker() -> None:
    from trace_core.updates.migration import migration_marker_path

    migration_marker_path().unlink(missing_ok=True)


def _mark_rolled_back(marker: dict) -> None:
    """Discharge the marker after a successful rollback.

    `trace recovery` never wrote an outcome, so the marker stayed on the state that sent
    it here — still RECOVERY_REQUIRED, still in _ROLLBACK_WORTHY_STATES. A second run
    rolled back again, and `_advance_previous` had by then pointed previous-version at the
    release that just failed, so it re-activated the bad release and reported success.
    """
    from trace_core.updates.domain import UpdateState
    from trace_core.updates.marker import write_marker

    try:
        write_marker({**marker, "state": UpdateState.ROLLED_BACK.value, "rollback": True})
    except Exception as exc:  # the rollback already happened; this only stops a repeat
        console.print(f"[yellow]Could not record the rollback ({exc}). Re-running recovery may repeat it.[/yellow]")


def _recover() -> None:
    from trace_core.core.database.health import fetch_db_snapshot
    from trace_core.core.database.session import get_db
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
    _triage_update_marker()
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
            _mark_rolled_back(marker)
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
