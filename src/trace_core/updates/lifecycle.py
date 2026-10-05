from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import structlog

from trace_core.updates.domain import UpdateFailureStage, UpdateResult, UpdateState, assert_transition
from trace_core.updates.dto import UpdateResultDto
from trace_core.updates.errors import UpdateError
from trace_core.updates.gate import ForensicOperationGate, GateDecision, UpdateGateContext
from trace_core.updates.lock import update_lock
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.stages import SILENT, ProgressCallback, Stage, StageStatus

if TYPE_CHECKING:
    from trace_core.core.database.session import DatabaseSessionManager

HEALTH_PASSED: Final[str] = "passed"
HEALTH_FAILED: Final[str] = "failed"


class UpdateLifecycle:
    def __init__(
        self,
        transaction_id: str,
        session_manager: "DatabaseSessionManager | None" = None,
        state: UpdateState = UpdateState.IDLE,
    ):
        from trace_core.core.database.session import DatabaseSessionManager, db_manager

        self.transaction_id = transaction_id
        self.session_manager: DatabaseSessionManager = session_manager or db_manager
        self.state = state

    def _record(
        self,
        current: str,
        manifest: ReleaseManifest,
        channel: str,
        started_at: datetime,
        *,
        result: str,
        failure_stage: str | None = None,
        failure_reason: str | None = None,
        override_reason: str | None = None,
        migration_range: str | None = None,
        health_check_result: str | None = None,
        backup_path: str | None = None,
        rollback: bool = False,
        restart_required: bool = False,
    ) -> UpdateResultDto:
        dto = UpdateResultDto(
            from_version=current,
            to_version=manifest.version,
            channel=channel,
            result=result,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
            override_reason=override_reason,
            migration_range=migration_range,
            health_check_result=health_check_result,
            backup_path=backup_path,
            rollback=rollback,
            restart_required=restart_required,
            transaction_id=self.transaction_id,
            release_id=manifest.release_id,
            started_at=started_at,
        )
        return dto

    def transition(self, to: UpdateState) -> None:
        from trace_core.updates.marker import write_marker

        assert_transition(self.state, to)
        write_marker(
            {
                "transaction_id": self.transaction_id,
                "state": str(to),
            }
        )
        self.state = to

    def _override_note(self, current: str, manifest: ReleaseManifest, allow_minimum_bypass: bool) -> str | None:
        from trace_core.updates.migration import current_schema_version
        from trace_core.updates.policy import minimum_bypass_note

        parts = []
        if allow_minimum_bypass:
            note = minimum_bypass_note(current, manifest)
            if note:
                parts.append(note)
        if manifest.backup_waiver and manifest.schema_target is not None:
            try:
                if manifest.schema_target > current_schema_version(self.session_manager):
                    parts.append(f"backup waived: {manifest.backup_waiver}")
            except Exception as exc:
                structlog.get_logger().warning("override-note schema check failed", error=str(exc))
                parts.append("schema check unavailable; see logs")
        return "; ".join(parts) or None

    def _check_release_health(
        self,
        base: Path,
        manifest: ReleaseManifest,
        snap: object,
        schema_after: int | None = None,
        staged: Path | None = None,
    ) -> str:
        """Health must be called with a fresh snapshot taken after migration and before activation."""
        from trace_core.updates import pip_backend
        from trace_core.updates.migration import current_schema_version
        from trace_updater import updater as updater_mod

        healthy = bool(getattr(snap, "healthy", False))
        pending = getattr(snap, "pending", [])
        if not healthy or pending:
            return HEALTH_FAILED
        target = updater_mod.releases_root(base) / manifest.version
        if not target.is_dir() or not any(target.iterdir()):
            return HEALTH_FAILED
        if manifest.schema_target is not None:
            after = schema_after
            if after is None:
                after = current_schema_version(self.session_manager)
            if after != manifest.schema_target:
                return HEALTH_FAILED
        # Pip layouts must prove the venv actually imports the target version;
        # a flipped pointer over stale code is a lying update.
        if not pip_backend.pip_health(manifest, staged):
            return HEALTH_FAILED
        return HEALTH_PASSED

    def _verify_activation(self, base: Path, manifest: ReleaseManifest) -> None:
        from trace_core.updates.errors import UpdateError
        from trace_updater import updater as updater_mod

        if updater_mod.read_active(base) != manifest.version:
            raise UpdateError(f"activation not reflected for {manifest.version}")

    def run(
        self,
        manifest: ReleaseManifest,
        artifact_path: str | Path,
        *,
        channel: str = "stable",
        gate: ForensicOperationGate | None = None,
        backup_dir: str | Path | None = None,
        allow_minimum_bypass: bool = False,
        progress: ProgressCallback | None = None,
    ) -> UpdateResultDto:
        from trace_core.core.clock import now_utc
        from trace_core.updates.checker import get_installed_version
        from trace_core.updates.errors import UpdateNotAvailableError, UpdatePolicyBlockedError
        from trace_core.updates.policy import is_update_available

        progress = progress or SILENT
        gate = gate or ForensicOperationGate()
        current = get_installed_version()
        if not is_update_available(current, manifest):
            raise UpdateNotAvailableError(f"no update available (current {current})")
        started_at = now_utc()
        from trace_core.updates.migration import (
            begin_update_migration,
            finish_update_migration,
            update_migration_owner,
        )

        with update_lock(), update_migration_owner(self.transaction_id):
            begin_update_migration(self.transaction_id)
            try:
                return self._run_locked(
                    manifest,
                    artifact_path,
                    channel,
                    gate,
                    backup_dir,
                    current,
                    started_at,
                    allow_minimum_bypass,
                    progress,
                )
            except UpdatePolicyBlockedError:
                raise
            except Exception as e:
                from trace_core.updates.domain import UpdateFailureStage, can_transition

                failure_stage = UpdateFailureStage.from_state(self.state)
                if can_transition(self.state, UpdateState.FAILED):
                    self.transition(UpdateState.FAILED)
                try:
                    self._record(
                        current,
                        manifest,
                        channel,
                        started_at,
                        result=UpdateResult.FAILED,
                        failure_stage=failure_stage,
                        failure_reason=str(e),
                        override_reason=self._override_note(current, manifest, allow_minimum_bypass),
                    )
                except Exception as record_exc:
                    structlog.get_logger().warning("failure history recording failed", error=str(record_exc))
                raise
            except BaseException as e:
                from trace_core.updates.domain import UpdateFailureStage, can_transition

                failure_stage = UpdateFailureStage.from_state(self.state)
                if can_transition(self.state, UpdateState.FAILED):
                    try:
                        self.transition(UpdateState.FAILED)
                    except Exception:
                        pass
                try:
                    self._record(
                        current,
                        manifest,
                        channel,
                        started_at,
                        result=UpdateResult.FAILED,
                        failure_stage=failure_stage,
                        failure_reason=f"interrupted: {type(e).__name__}",
                    )
                except Exception as record_exc:
                    structlog.get_logger().warning("failure history recording failed", error=str(record_exc))
                raise
            finally:
                import contextlib

                with contextlib.suppress(UpdateError):
                    finish_update_migration(self.transaction_id)

    def _verify_stage(self, manifest: ReleaseManifest, artifact_path: str | Path) -> None:
        from trace_core.updates.verifier import verify_manifest

        verify_manifest(manifest, Path(artifact_path))

    def _download_stage(self, manifest: ReleaseManifest, artifact_path: str | Path, staging_dir: Path) -> Path:
        from trace_core.updates.verifier import resolve_artifact
        from trace_updater import updater as updater_mod

        artifact = resolve_artifact(manifest, Path(artifact_path))
        return updater_mod.stage_artifact(
            Path(artifact_path),
            staging_dir,
            expected_sha256=artifact.sha256,
            binding={
                "transaction_id": self.transaction_id,
                "release_id": manifest.release_id,
                "version": manifest.version,
            },
        )

    def _assert_verified_stage(
        self,
        staging_dir: Path,
        staged: Path,
        manifest: ReleaseManifest,
    ) -> None:
        from trace_core.core.fs import sha256_file
        from trace_core.updates import staging as staging_mod
        from trace_core.updates.verifier import resolve_artifact

        artifact = resolve_artifact(manifest, staged)
        staging_mod.write_staged_record(
            staging_dir,
            {
                "release_id": manifest.release_id,
                "version": manifest.version,
                "filename": staged.name,
                # Measured from the staged bytes. This used to record the manifest's
                # own claim into a field named "actual", so staging.is_verified_stage
                # compared the expected hash against itself and always agreed.
                "expected_sha256": artifact.sha256,
                "actual_sha256": sha256_file(staged),
                "signing_key_id": manifest.signing_key_id,
                "verification": "passed",
            },
        )
        if not staging_mod.is_verified_stage(staging_dir, staged):
            # H-14: this transitioned to FAILED *and* wrote a history row before raising, so
            # run()'s generic handler wrote a second FAILED row for the same transaction_id.
            # The caller owns both the transition and the history for a raise; this only
            # raises, which also keeps the stage label accurate (STAGED -> "staging").
            from trace_core.updates.errors import UpdateVerificationError

            raise UpdateVerificationError("staged artifact failed re-verification")

    def _install_stage(self, staged: Path, base: Path, manifest: ReleaseManifest) -> None:
        from trace_updater import updater as updater_mod

        updater_mod.stage_release(
            staged.parent,
            base,
            manifest.version,
            expected=[staged.name],
            release_meta={
                "version": manifest.version,
                "release_id": manifest.release_id,
                "schema_min": manifest.schema_min,
                "schema_target": manifest.schema_target,
            },
        )

    def _pip_install_stage(self, staged: Path) -> None:
        """Install the verified wheel into the running venv. No-op off venv layouts."""
        from trace_core.updates import pip_backend

        python = pip_backend.venv_python()
        if python is not None and pip_backend.pip_layout_for(staged):
            pip_backend.pip_install_wheel(python, staged)

    def _run_locked(
        self,
        manifest: ReleaseManifest,
        artifact_path: str | Path,
        channel: str,
        gate: ForensicOperationGate,
        backup_dir: str | Path | None,
        current: str,
        started_at: datetime,
        allow_minimum_bypass: bool = False,
        progress: ProgressCallback = SILENT,
    ) -> UpdateResultDto:
        from trace_core.core.database.health import fetch_db_snapshot
        from trace_core.updates.migration import current_schema_version, run_updater_migration
        from trace_core.updates.policy import is_installable
        from trace_updater import updater as updater_mod

        # Outer run() already holds update_lock(); inner is reentrant via thread-local depth.
        with update_lock():
            self.transition(UpdateState.CHECKING)
            decision = gate.can_install_update(
                UpdateGateContext(target_version=manifest.version, transaction_id=self.transaction_id)
            )
            match decision:
                case GateDecision.ACTIVE_OPERATION:
                    forensic_active = True
                case GateDecision.ALLOWED:
                    forensic_active = False
                case _:
                    raise UpdateError("unknown forensic-operation state; failing closed")

            ok, reason = is_installable(current, manifest, channel, forensic_active, allow_minimum_bypass)
            override_note = self._override_note(current, manifest, allow_minimum_bypass) if ok else None
            if not ok:
                from trace_core.updates.errors import UpdatePolicyBlockedError

                self.transition(UpdateState.FAILED)
                self._record(
                    current,
                    manifest,
                    channel,
                    started_at,
                    result=UpdateResult.FAILED,
                    failure_stage=UpdateFailureStage.POLICY,
                    failure_reason=reason,
                )
                raise UpdatePolicyBlockedError(reason or "update blocked by policy")
            self.transition(UpdateState.AVAILABLE)
            self.transition(UpdateState.READY_TO_INSTALL)
            self._verify_stage(manifest, artifact_path)
            from trace_updater.updater import install_root as _install_root

            base = _install_root()
            # H-19: this swallowed the error and substituted None, a value known to be wrong.
            # `_check_release_health` then failed the schema check against it and rolled
            # back a perfectly healthy update. A verdict computed from a substituted value
            # is not a verdict, so call it for its DB-failure side effect and discard the
            # number — the post-migration `schema_after` is the one the health check reads.
            current_schema_version(self.session_manager)
            staging_dir = base / "staging" / self.transaction_id
            self.transition(UpdateState.DOWNLOADING)
            staged = self._download_stage(manifest, artifact_path, staging_dir)
            progress.on_stage(Stage.VERIFY, StageStatus.ACTIVE)
            self._assert_verified_stage(staging_dir, staged, manifest)
            progress.on_stage(Stage.VERIFY, StageStatus.DONE)
            self.transition(UpdateState.STAGED)
            self.transition(UpdateState.INSTALLING)
            progress.on_stage(Stage.INSTALL, StageStatus.ACTIVE)
            self._install_stage(staged, base, manifest)
            self._pip_install_stage(staged)
            self.transition(UpdateState.MIGRATING)
            migration = run_updater_migration(
                self.session_manager,
                self.transaction_id,
                schema_min=manifest.schema_min,
                schema_target=manifest.schema_target,
                backup_required=manifest.backup_required,
                backup_dir=backup_dir or (base / "backups"),
                backup_waiver=manifest.backup_waiver,
            )
            self.transition(UpdateState.HEALTH_CHECK)
            progress.on_stage(Stage.INSTALL, StageStatus.DONE)
            progress.on_stage(Stage.HEALTH, StageStatus.ACTIVE)
            snap = fetch_db_snapshot(self.session_manager)
            # H-19: same defect as schema_before — a substituted schema_after silently passed the
            # post-migration check, so a migration that did not reach its target looked healthy.
            schema_after = current_schema_version(self.session_manager)
            health = self._check_release_health(base, manifest, snap, schema_after, staged=staged)
            if health != HEALTH_PASSED:
                from trace_core.updates.migration import rollback_release

                self.transition(UpdateState.ROLLING_BACK)
                try:
                    restored = rollback_release(base, self.session_manager, migration["backup"])
                    restored_snap = fetch_db_snapshot(self.session_manager)
                    restored_health = (
                        HEALTH_PASSED if restored_snap.healthy and not restored_snap.pending else HEALTH_FAILED
                    )
                except (OSError, UpdateError) as e:
                    self.transition(UpdateState.RECOVERY_REQUIRED)
                    return self._record(
                        current,
                        manifest,
                        channel,
                        started_at,
                        result=UpdateResult.FAILED,
                        failure_stage=UpdateFailureStage.HEALTH,
                        failure_reason=f"rollback failed: {e}",
                        migration_range=f"{migration['schema']}",
                        health_check_result=health,
                        backup_path=migration["backup"],
                        override_reason=override_note,
                    )
                self.transition(UpdateState.ROLLED_BACK)
                return self._record(
                    current,
                    manifest,
                    channel,
                    started_at,
                    result=UpdateResult.ROLLED_BACK,
                    failure_stage=UpdateFailureStage.HEALTH,
                    migration_range=f"{migration['schema']}",
                    health_check_result=f"failed; restored {restored} health {restored_health}",
                    backup_path=migration["backup"],
                    override_reason=override_note,
                    rollback=True,
                )
            updater_mod.activate(base, manifest.version)
            try:
                self._verify_activation(base, manifest)
            except Exception as e:
                # H-15: the pointer is already flipped and the DB already migrated, so a
                # failed post-activation verify left half-applied state marked FAILED with
                # no reconciliation path. Activation is not the point of no return —
                # roll back exactly as the health-check failure path does.
                from trace_core.updates.migration import rollback_release

                self.transition(UpdateState.ROLLING_BACK)
                try:
                    rollback_release(base, self.session_manager, migration["backup"])
                except (OSError, UpdateError):
                    self.transition(UpdateState.RECOVERY_REQUIRED)
                    return self._record(
                        current,
                        manifest,
                        channel,
                        started_at,
                        result=UpdateResult.FAILED,
                        failure_stage=UpdateFailureStage.ACTIVATION,
                        failure_reason=f"post-activation verification failed ({e}); rollback failed",
                        migration_range=f"{migration['schema']}",
                        health_check_result=health,
                        backup_path=migration["backup"],
                        override_reason=override_note,
                    )
                self.transition(UpdateState.ROLLED_BACK)
                return self._record(
                    current,
                    manifest,
                    channel,
                    started_at,
                    result=UpdateResult.ROLLED_BACK,
                    failure_stage=UpdateFailureStage.ACTIVATION,
                    failure_reason=f"post-activation verification failed: {e}",
                    migration_range=f"{migration['schema']}",
                    health_check_result=f"passed; reverted after activation check failed: {e}",
                    backup_path=migration["backup"],
                    override_reason=override_note,
                    rollback=True,
                )
            # ponytail: keep_backups restates updater.RETENTION_BACKUPS; parameter stays for callers
            updater_mod.prune_retention(base)
            self.transition(UpdateState.COMPLETED)
            dto = self._record(
                current,
                manifest,
                channel,
                started_at,
                result=UpdateResult.SUCCESS,
                migration_range=f"{migration['schema']}",
                health_check_result=health,
                backup_path=migration["backup"],
                override_reason=override_note,
                restart_required=manifest.restart_required,
            )
            from trace_core.updates.marker import write_marker

            write_marker(
                {
                    "transaction_id": self.transaction_id,
                    "state": str(UpdateState.COMPLETED),
                    "previous_version": current,
                    "target_version": manifest.version,
                    "release_id": manifest.release_id,
                    "result": "completed",
                    "migration_range": f"{migration['schema']}",
                    "health_check_result": health,
                    "backup_path": migration["backup"],
                    "rollback_performed": False,
                    "restart_required": manifest.restart_required,
                }
            )
            return dto
