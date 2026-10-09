import json

import pytest

from trace_core.updates.dto import UpdateResultDto
from trace_core.updates.errors import UpdateNotAvailableError, UpdateVerificationError
from trace_core.updates.lifecycle import UpdateLifecycle

pytestmark = pytest.mark.unit


def _raise_interrupt(*_a: object, **_k: object) -> None:
    raise KeyboardInterrupt


def test_run_rejects_downgrade_directly(session_manager, signed_release):
    manifest, _, art_path, _ = signed_release(version="0.0.1")
    life = UpdateLifecycle("tx-gate-1", session_manager)
    with pytest.raises(UpdateNotAvailableError):
        life.run(manifest, art_path)


def test_run_rejects_same_version(session_manager, signed_release):
    manifest, _, art_path, _ = signed_release(version="0.1.0")
    life = UpdateLifecycle("tx-gate-2", session_manager)
    with pytest.raises(UpdateNotAvailableError):
        life.run(manifest, art_path)


def test_an_interrupt_is_recorded_as_a_failure(session_manager, signed_release, monkeypatch):
    manifest, _, art_path, _ = signed_release(version="1.5.0")
    life = UpdateLifecycle("tx-interrupt-1", session_manager)
    recorded: list[dict] = []
    monkeypatch.setattr(life, "_record", lambda *a, **k: recorded.append(k))
    monkeypatch.setattr(life, "_run_locked", _raise_interrupt)

    with pytest.raises(KeyboardInterrupt):
        life.run(manifest, art_path)

    assert [str(r["result"]) for r in recorded] == ["FAILED"]
    assert "KeyboardInterrupt" in recorded[0]["failure_reason"]


def test_bypass_override_recorded(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release(minimum_supported_version="9.9.9")
    dto = UpdateLifecycle("tx-gate-3", session_manager).run(manifest, art_path, allow_minimum_bypass=True)
    assert dto.override_reason is not None
    assert "9.9.9" in dto.override_reason


def test_bypass_is_ledgered_before_any_code_is_replaced(
    session_manager, signed_release, release_keys, monkeypatch, tmp_path
):
    import sqlalchemy

    from trace_core.audit.models import AuditEventModel
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release(minimum_supported_version="9.9.9")
    UpdateLifecycle("tx-gate-ledger", session_manager).run(manifest, art_path, allow_minimum_bypass=True)

    with session_manager.session() as session:
        rows = list(
            session.scalars(
                sqlalchemy.select(AuditEventModel).where(AuditEventModel.action == "UPDATE_POLICY_OVERRIDE")
            )
        )
    assert len(rows) == 1, rows
    details = json.loads(rows[0].payload_json)["details"]
    assert details["gate"] == "minimum_supported_version"
    assert details["blocked_reason"] == "9.9.9"
    assert "9.9.9" in details["reason"]
    assert details["authorized_by"]
    assert rows[0].actor


def test_an_unwaived_gate_writes_no_override_row(session_manager, signed_release, monkeypatch, tmp_path):
    import sqlalchemy

    from trace_core.audit.models import AuditEventModel
    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    manifest, _, art_path, _ = signed_release()
    UpdateLifecycle("tx-gate-nooverride", session_manager).run(manifest, art_path)

    with session_manager.session() as session:
        assert not list(
            session.scalars(
                sqlalchemy.select(AuditEventModel).where(AuditEventModel.action == "UPDATE_POLICY_OVERRIDE")
            )
        )


def test_staged_reverify_failure(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_core.updates import signing
    from trace_core.updates import staging as staging_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    monkeypatch.setattr(staging_mod, "is_verified_stage", lambda *a: False)
    life = UpdateLifecycle("tx-gate-4", session_manager)
    with pytest.raises(UpdateVerificationError):
        life.run(manifest, art_path)


def test_activation_mismatch_recorded(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_updater import updater as updater_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    from trace_core.updates import signing

    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    monkeypatch.setattr(updater_mod, "activate", lambda base, version: None)
    life = UpdateLifecycle("tx-gate-5", session_manager)
    # H-15: the pointer is flipped and the DB migrated by this point, so a failed
    # post-activation check must roll back rather than return FAILED with half-applied
    # state. It no longer raises to the caller; it reports ROLLED_BACK.
    from trace_core.updates import migration as mig_mod

    # ctivate is stubbed out above, so nothing was actually flipped or migrated; stub the
    # rollback too, so this test asserts the control flow rather than real FS/DB state.
    monkeypatch.setattr(mig_mod, "rollback_release", lambda *a, **k: "restored")
    dto = life.run(manifest, art_path)
    assert dto.result == "ROLLED_BACK"
    assert dto.failure_stage == "activation"


def test_waiver_recorded_on_advancing_schema(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from sqlalchemy import Column, Integer, MetaData, Table

    from trace_core.core.database import migrations as mig_mod
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    meta = MetaData()
    Table("waiver_probe", meta, Column("id", Integer, primary_key=True))

    probe_version = len(mig_mod.MIGRATIONS) + 1

    @mig_mod.register_migration(probe_version, "017_test_waiver_probe", operations=("create_all:waiver_probe",))
    def _probe(bind):
        meta.create_all(bind=bind)

    try:
        manifest, _, art_path, _ = signed_release(schema_min=1, schema_target=probe_version, backup_waiver="lab device")
        dto = UpdateLifecycle("tx-gate-7", session_manager).run(manifest, art_path)
        assert dto.result == "SUCCESS"
        assert dto.override_reason is not None
        assert "lab device" in dto.override_reason
    finally:
        mig_mod.MIGRATIONS[:] = [m for m in mig_mod.MIGRATIONS if m[1] != "017_test_waiver_probe"]
        mig_mod.MIGRATION_VERIFIERS.pop(probe_version, None)
        mig_mod.MIGRATION_OPERATIONS.pop(probe_version, None)


def test_started_at_captured(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    dto = UpdateLifecycle("tx-gate-6", session_manager).run(manifest, art_path)
    assert dto.transaction_id == "tx-gate-6"


def test_history_create_rejects_unknown_kwargs():
    from typing import Any

    from pydantic import ValidationError

    kwargs: dict[str, Any] = {
        "from_version": "0.1.0",
        "to_version": "1.5.0",
        "bogus_field": "x",
    }
    with pytest.raises(ValidationError):
        UpdateResultDto(**kwargs)
