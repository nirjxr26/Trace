from pathlib import Path

from trace_core.updates.domain import UpdateResult, UpdateState, assert_transition
from trace_core.updates.dto import UpdateHistoryCreateDto
from trace_core.updates.errors import UpdateError
from trace_core.updates.gate import ForensicOperationGate, GateDecision
from trace_core.updates.lock import update_lock
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.service import UpdateService


class UpdateLifecycle:
    def __init__(self, transaction_id: str, service: UpdateService | None = None):
        self.transaction_id = transaction_id
        self.service = service or UpdateService()
        self.state = UpdateState.IDLE

    def transition(self, to: UpdateState) -> None:
        from trace_core.updates.marker import write_marker

        assert_transition(self.state, to)
        self.state = to
        write_marker(
            {
                "transaction_id": self.transaction_id,
                "state": str(self.state),
            }
        )

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
                if manifest.schema_target > current_schema_version(self.service.session_manager):
                    parts.append(f"backup waived: {manifest.backup_waiver}")
            except Exception:
                pass
        return "; ".join(parts) or None

    def _check_release_health(self, base: Path, manifest: ReleaseManifest, snap) -> str:  # type: ignore[no-untyped-def]
        from trace_core.updates.migration import current_schema_version
        from trace_updater import updater as updater_mod

        if not snap.healthy or snap.pending:
            return "failed"
        target = updater_mod.releases_root(base) / manifest.version
        if not target.is_dir() or not any(target.iterdir()):
            return "failed"
        if manifest.schema_target is not None:
            if current_schema_version(self.service.session_manager) != manifest.schema_target:
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
            raise UpdateError(f"no recoverable state for transaction {transaction_id}")
        try:
            state = UpdateState(marker["state"])
        except ValueError as e:
            raise RecoveryError(f"unrecognized marker state {marker['state']!r}") from e
        obj = cls(transaction_id, svc)
        obj.state = state
        return obj

    def run(
        self,
        manifest: ReleaseManifest,
        artifact_path: str | Path,
        channel: str = "stable",
        gate: ForensicOperationGate | None = None,
        backup_dir: str | Path | None = None,
        allow_minimum_bypass: bool = False,
    ) -> UpdateHistoryCreateDto:
        from trace_core.core.domain import now_utc
        from trace_core.core.settings import settings
        from trace_core.updates.errors import UpdateNotAvailableError, UpdatePolicyBlockedError
        from trace_core.updates.policy import is_update_available

        gate = gate or ForensicOperationGate()
        current = settings.version
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
                    manifest, artifact_path, channel, gate, backup_dir, current, started_at, allow_minimum_bypass
                )
            except UpdatePolicyBlockedError:
                raise
            except Exception as e:
                from trace_core.updates.domain import can_transition

                if can_transition(self.state, UpdateState.FAILED):
                    self.transition(UpdateState.FAILED)
                self.service.record_history(
                    UpdateHistoryCreateDto(
                        from_version=current,
                        to_version=manifest.version,
                        channel=channel,
                        result=UpdateResult.FAILED,
                        failure_stage=str(self.state),
                        failure_reason=str(e),
                        override_reason=self._override_note(current, manifest, allow_minimum_bypass),
                        transaction_id=self.transaction_id,
                        release_id=manifest.release_id,
                        started_at=started_at,
                    )
                )
                raise
            finally:
                import contextlib

                with contextlib.suppress(UpdateError):
                    finish_update_migration(self.transaction_id)

    def _run_locked(  # type: ignore[no-untyped-def]
        self, manifest, artifact_path, channel, gate, backup_dir, current, started_at, allow_minimum_bypass=False
    ) -> UpdateHistoryCreateDto:
        from trace_core.core.database.health import fetch_db_snapshot
        from trace_core.core.settings import settings
        from trace_core.updates import staging as staging_mod
        from trace_core.updates.migration import run_updater_migration
        from trace_core.updates.policy import is_installable, select_artifact
        from trace_core.updates.verifier import verify_manifest
        from trace_updater import updater as updater_mod

        with update_lock():
            self.transition(UpdateState.CHECKING)
            decision = gate.can_install_update()
            if decision == GateDecision.ACTIVE_OPERATION:
                forensic_active = True
            elif decision == GateDecision.UNKNOWN:
                raise UpdateError("unknown forensic-operation state; failing closed")
            else:
                forensic_active = False

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
                    failure_stage="policy",
                    failure_reason=reason,
                    transaction_id=self.transaction_id,
                    started_at=started_at,
                    release_id=manifest.release_id,
                )
                self.service.record_history(dto)
                raise UpdatePolicyBlockedError(reason or "update blocked by policy")
            self.transition(UpdateState.AVAILABLE)
            self.transition(UpdateState.READY_TO_INSTALL)
            verify_manifest(manifest, Path(artifact_path))
            base = Path(settings.storage_root).parent / "install"
            staging_dir = base / "staging" / self.transaction_id
            self.transition(UpdateState.DOWNLOADING)
            artifact = select_artifact(manifest)
            staged = updater_mod.stage_artifact(
                Path(artifact_path),
                staging_dir,
                expected_sha256=artifact.sha256,
                binding={
                    "transaction_id": self.transaction_id,
                    "release_id": manifest.release_id,
                    "version": manifest.version,
                },
            )
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
                dto = UpdateHistoryCreateDto(
                    from_version=current,
                    to_version=manifest.version,
                    channel=channel,
                    result=UpdateResult.FAILED,
                    failure_stage="staging",
                    failure_reason="staged artifact failed re-verification",
                    transaction_id=self.transaction_id,
                    started_at=started_at,
                    release_id=manifest.release_id,
                )
                self.service.record_history(dto)
                raise UpdateVerificationError("staged artifact failed re-verification")
            self.transition(UpdateState.STAGED)
            self.transition(UpdateState.INSTALLING)
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
            health = self._check_release_health(base, manifest, snap)
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
                        failure_stage="health",
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
                    failure_stage="health",
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
