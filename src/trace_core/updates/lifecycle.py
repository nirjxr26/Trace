import sys
from datetime import datetime
from pathlib import Path

from trace_core.updates.domain import UpdateFailureStage, UpdateResult, UpdateState, assert_transition
from trace_core.updates.dto import UpdateHistoryCreateDto
from trace_core.updates.errors import UpdateError
from trace_core.updates.gate import ForensicOperationGate, GateDecision, UpdateGateContext
from trace_core.updates.lock import update_lock
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.service import UpdateService


class UpdateLifecycle:
    def __init__(
        self,
        transaction_id: str,
        service: UpdateService | None = None,
        state: UpdateState = UpdateState.IDLE,
    ):
        self.transaction_id = transaction_id
        self.service = service or UpdateService()
        self.state = state

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
        import structlog

        from trace_core.updates.migration import current_schema_version
        from trace_core.updates.policy import minimum_bypass_note

        parts = []
        if allow_minimum_bypass:
            note = minimum_bypass_note(current, manifest)
            if note:
                parts.append(note)
        if manifest.backup_waiver and manifest.schema_target is not None:
            try:
                if manifest.schema_target > current_schema_version(self.service.session_manager):
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
            return "failed"
        target = updater_mod.releases_root(base) / manifest.version
        if not target.is_dir() or not any(target.iterdir()):
            return "failed"
        if manifest.schema_target is not None:
            after = schema_after
            if after is None:
                after = current_schema_version(self.service.session_manager)
            if after != manifest.schema_target:
                return "failed"
        # Pip layouts must prove the venv actually imports the target version;
        # a flipped pointer with stale code is a lying update.
        if staged is not None and pip_backend.pip_layout_for(manifest, staged):
            if pip_backend.pip_installed_version() != manifest.version:
                return "failed"
        return "passed"

    def _verify_activation(self, base: Path, manifest: ReleaseManifest) -> None:
        from trace_core.updates.errors import UpdateError
        from trace_updater import updater as updater_mod

        if updater_mod.read_active(base) != manifest.version:
            raise UpdateError(f"activation not reflected for {manifest.version}")

    @classmethod
    def load(cls, transaction_id: str, service: UpdateService | None = None) -> "UpdateLifecycle":
        from trace_core.updates.errors import RecoveryError
        from trace_core.updates.marker import read_marker

        svc = service or UpdateService()
        marker = read_marker()
        if marker.get("transaction_id") != transaction_id:
            raise RecoveryError(f"no recoverable state for transaction {transaction_id}")
        try:
            state = UpdateState(marker["state"])
        except ValueError as e:
            raise RecoveryError(f"unrecognized marker state {marker['state']!r}") from e
        return cls(transaction_id, svc, state=state)

    def run(
        self,
        manifest: ReleaseManifest,
        artifact_path: str | Path,
        *,
        channel: str = "stable",
        gate: ForensicOperationGate | None = None,
        backup_dir: str | Path | None = None,
        allow_minimum_bypass: bool = False,
        preverified_sha256: str | None = None,
    ) -> UpdateHistoryCreateDto:
        from trace_core.core.domain import now_utc
        from trace_core.updates.checker import get_installed_version
        from trace_core.updates.errors import UpdateNotAvailableError, UpdatePolicyBlockedError
        from trace_core.updates.policy import is_update_available

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
                    preverified_sha256,
                )
            except UpdatePolicyBlockedError:
                raise
            except Exception as e:
                import structlog as _structlog

                from trace_core.updates.domain import UpdateFailureStage, can_transition

                if can_transition(self.state, UpdateState.FAILED):
                    self.transition(UpdateState.FAILED)
                try:
                    self.service.record_history(
                        UpdateHistoryCreateDto(
                            from_version=current,
                            to_version=manifest.version,
                            channel=channel,
                            result=UpdateResult.FAILED,
                            failure_stage=UpdateFailureStage.from_state(self.state),
                            failure_reason=str(e),
                            override_reason=self._override_note(current, manifest, allow_minimum_bypass),
                            transaction_id=self.transaction_id,
                            release_id=manifest.release_id,
                            started_at=started_at,
                        )
                    )
                except Exception as record_exc:
                    _structlog.get_logger().warning("failure history recording failed", error=str(record_exc))
                raise
            except BaseException as e:
                import structlog as _structlog

                from trace_core.updates.domain import UpdateFailureStage, can_transition

                if can_transition(self.state, UpdateState.FAILED):
                    try:
                        self.transition(UpdateState.FAILED)
                    except Exception:
                        pass
                try:
                    self.service.record_history(
                        UpdateHistoryCreateDto(
                            from_version=current,
                            to_version=manifest.version,
                            channel=channel,
                            result=UpdateResult.FAILED,
                            failure_stage=UpdateFailureStage.from_state(self.state),
                            failure_reason=f"interrupted: {type(e).__name__}",
                            transaction_id=self.transaction_id,
                            release_id=manifest.release_id,
                            started_at=started_at,
                        )
                    )
                except Exception as record_exc:
                    _structlog.get_logger().warning("failure history recording failed", error=str(record_exc))
                raise
            finally:
                import contextlib

                with contextlib.suppress(UpdateError):
                    finish_update_migration(self.transaction_id)

    def _verify_stage(
        self, manifest: ReleaseManifest, artifact_path: str | Path, preverified_sha256: str | None = None
    ) -> None:
        from trace_core.core.fs import sha256_file
        from trace_core.updates.verifier import resolve_artifact, verify_manifest

        if preverified_sha256 is not None:
            artifact = resolve_artifact(manifest, Path(artifact_path))
            if artifact.sha256 == preverified_sha256:
                try:
                    if sha256_file(artifact_path) == artifact.sha256:
                        from trace_core.updates.signing import verify_artifact_signature_file

                        verify_artifact_signature_file(artifact_path, artifact.signature, artifact.signing_key_id)
                        return
                except OSError:
                    pass
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
        channel: str,
        current: str,
        started_at: datetime,
    ) -> None:
        from trace_core.updates import staging as staging_mod
        from trace_core.updates.verifier import resolve_artifact

        artifact = resolve_artifact(manifest, staged)
        staging_mod.write_staged_record(
            staging_dir,
            {
                "release_id": manifest.release_id,
                "version": manifest.version,
                "filename": staged.name,
                "expected_sha256": artifact.sha256,
                "actual_sha256": artifact.sha256,
                "signing_key_id": manifest.signing_key_id,
                "verification": "passed",
            },
        )
        if not staging_mod.is_verified_stage(staging_dir, staged):
            from trace_core.updates.errors import UpdateVerificationError

            self.transition(UpdateState.FAILED)
            self.service.record_history(
                UpdateHistoryCreateDto(
                    from_version=current,
                    to_version=manifest.version,
                    channel=channel,
                    result=UpdateResult.FAILED,
                    failure_stage=UpdateFailureStage.STAGING,
                    failure_reason="staged artifact failed re-verification",
                    transaction_id=self.transaction_id,
                    started_at=started_at,  # type: ignore[arg-type]
                    release_id=manifest.release_id,
                )
            )
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

    def _pip_install_stage(self, staged: Path, manifest: ReleaseManifest) -> None:
        """Install the verified wheel into the running venv. No-op off venv layouts."""
        from trace_core.updates import pip_backend

        if not pip_backend.pip_layout_for(manifest, staged):
            return
        pip_backend.pip_install_wheel(Path(sys.executable), staged)

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
        preverified_sha256: str | None = None,
    ) -> UpdateHistoryCreateDto:
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
                dto = UpdateHistoryCreateDto(
                    from_version=current,
                    to_version=manifest.version,
                    channel=channel,
                    result=UpdateResult.FAILED,
                    failure_stage=UpdateFailureStage.POLICY,
                    failure_reason=reason,
                    transaction_id=self.transaction_id,
                    started_at=started_at,
                    release_id=manifest.release_id,
                )
                self.service.record_history(dto)
                raise UpdatePolicyBlockedError(reason or "update blocked by policy")
            self.transition(UpdateState.AVAILABLE)
            self.transition(UpdateState.READY_TO_INSTALL)
            self._verify_stage(manifest, artifact_path, preverified_sha256)
            from trace_updater.updater import install_root as _install_root

            base = _install_root()
            schema_before: int | None
            try:
                schema_before = current_schema_version(self.service.session_manager)
            except Exception:
                schema_before = None
            staging_dir = base / "staging" / self.transaction_id
            self.transition(UpdateState.DOWNLOADING)
            staged = self._download_stage(manifest, artifact_path, staging_dir)
            self._assert_verified_stage(staging_dir, staged, manifest, channel, current, started_at)
            self.transition(UpdateState.STAGED)
            self.transition(UpdateState.INSTALLING)
            self._install_stage(staged, base, manifest)
            self._pip_install_stage(staged, manifest)
            self.transition(UpdateState.MIGRATING)
            migration = run_updater_migration(
                self.service.session_manager,
                self.transaction_id,
                schema_min=manifest.schema_min,
                schema_target=manifest.schema_target,
                backup_required=manifest.backup_required,
                backup_dir=backup_dir or (base / "backups"),
                backup_waiver=manifest.backup_waiver,
            )
            self.transition(UpdateState.HEALTH_CHECK)
            snap = fetch_db_snapshot(self.service.session_manager)
            schema_after: int | None
            try:
                schema_after = current_schema_version(self.service.session_manager)
            except Exception:
                schema_after = schema_before
            health = self._check_release_health(base, manifest, snap, schema_after, staged=staged)
            if health != "passed":
                from trace_core.updates.migration import rollback_release

                self.transition(UpdateState.ROLLING_BACK)
                try:
                    restored = rollback_release(base, self.service.session_manager, migration["backup"])
                    restored_health = "passed" if fetch_db_snapshot(self.service.session_manager).healthy else "failed"
                except (OSError, UpdateError) as e:
                    self.transition(UpdateState.RECOVERY_REQUIRED)
                    dto = UpdateHistoryCreateDto(
                        from_version=current,
                        to_version=manifest.version,
                        channel=channel,
                        result=UpdateResult.FAILED,
                        failure_stage=UpdateFailureStage.HEALTH,
                        failure_reason=f"rollback failed: {e}",
                        migration_range=f"{migration['schema']}",
                        health_check_result=health,
                        backup_path=migration["backup"],
                        override_reason=override_note,
                        transaction_id=self.transaction_id,
                        started_at=started_at,
                        release_id=manifest.release_id,
                    )
                    self.service.record_history(dto)
                    return dto
                self.transition(UpdateState.ROLLED_BACK)
                dto = UpdateHistoryCreateDto(
                    from_version=current,
                    to_version=manifest.version,
                    channel=channel,
                    result=UpdateResult.ROLLED_BACK,
                    failure_stage=UpdateFailureStage.HEALTH,
                    migration_range=f"{migration['schema']}",
                    health_check_result=f"failed; restored {restored} health {restored_health}",
                    backup_path=migration["backup"],
                    override_reason=override_note,
                    rollback=True,
                    transaction_id=self.transaction_id,
                    started_at=started_at,
                    release_id=manifest.release_id,
                )
                self.service.record_history(dto)
                return dto
            updater_mod.activate(base, manifest.version)
            self._verify_activation(base, manifest)
            updater_mod.prune_retention(base, keep_backups=3)
            self.transition(UpdateState.COMPLETED)
            dto = UpdateHistoryCreateDto(
                from_version=current,
                to_version=manifest.version,
                channel=channel,
                result=UpdateResult.SUCCESS,
                migration_range=f"{migration['schema']}",
                health_check_result=health,
                backup_path=migration["backup"],
                override_reason=override_note,
                restart_required=manifest.restart_required,
                transaction_id=self.transaction_id,
                release_id=manifest.release_id,
                started_at=started_at,
            )
            self.service.record_history(dto)
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
