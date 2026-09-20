import pytest

from trace_core.updates.dto import UpdateHistoryCreateDto
from trace_core.updates.errors import UpdateNotAvailableError, UpdateVerificationError
from trace_core.updates.lifecycle import UpdateLifecycle
from trace_core.updates.service import UpdateService

pytestmark = pytest.mark.unit


def test_run_rejects_downgrade_directly(session_manager, signed_release):
    manifest, _, art_path, _ = signed_release(version="0.0.1")
    svc = UpdateService(session_manager)
    life = UpdateLifecycle("tx-gate-1", svc)
    with pytest.raises(UpdateNotAvailableError):
        life.run(manifest, art_path)
    assert svc.list_history() == []


def test_run_rejects_same_version(session_manager, signed_release):
    manifest, _, art_path, _ = signed_release(version="0.1.0")
    svc = UpdateService(session_manager)
    life = UpdateLifecycle("tx-gate-2", svc)
    with pytest.raises(UpdateNotAvailableError):
        life.run(manifest, art_path)


def test_bypass_override_recorded(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release(minimum_supported_version="9.9.9")
    svc = UpdateService(session_manager)
    dto = UpdateLifecycle("tx-gate-3", svc).run(manifest, art_path, allow_minimum_bypass=True)
    assert dto.override_reason is not None
    assert "9.9.9" in dto.override_reason
    rows = svc.list_history()
    assert any(r.transaction_id == "tx-gate-3" and (r.override_reason or "") != "" for r in rows)


def test_staged_reverify_failure(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_core.updates import signing
    from trace_core.updates import staging as staging_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    monkeypatch.setattr(staging_mod, "is_verified_stage", lambda *a: False)
    life = UpdateLifecycle("tx-gate-4", svc)
    with pytest.raises(UpdateVerificationError):
        life.run(manifest, art_path)
    rows = svc.list_history()
    assert any(r.transaction_id == "tx-gate-4" and r.failure_stage == "staging" for r in rows)


def test_activation_mismatch_recorded(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_updater import updater as updater_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    from trace_core.updates import signing

    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    monkeypatch.setattr(updater_mod, "activate", lambda base, version: None)
    from trace_core.updates.errors import UpdateError

    life = UpdateLifecycle("tx-gate-5", svc)
    with pytest.raises(UpdateError, match="activation not reflected"):
        life.run(manifest, art_path)
    rows = svc.list_history()
    assert any(r.transaction_id == "tx-gate-5" and r.result == "FAILED" for r in rows)


def test_waiver_recorded_on_advancing_schema(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from sqlalchemy import Column, Integer, MetaData, Table

    from trace_core.core.database import migrations as mig_mod
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    meta = MetaData()
    Table("waiver_probe", meta, Column("id", Integer, primary_key=True))

    @mig_mod.register_migration(17, "017_test_waiver_probe")
    def _probe(bind):
        meta.create_all(bind=bind)

    try:
        manifest, _, art_path, _ = signed_release(schema_min=1, schema_target=17, backup_waiver="lab device")
        svc = UpdateService(session_manager)
        dto = UpdateLifecycle("tx-gate-7", svc).run(manifest, art_path)
        assert dto.result == "SUCCESS"
        assert dto.override_reason is not None
        assert "lab device" in dto.override_reason
    finally:
        mig_mod.MIGRATIONS[:] = [m for m in mig_mod.MIGRATIONS if m[1] != "017_test_waiver_probe"]
        mig_mod.MIGRATION_VERIFIERS.pop(17, None)


def test_started_at_captured(session_manager, signed_release, release_keys, monkeypatch, tmp_path):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    dto = UpdateLifecycle("tx-gate-6", svc).run(manifest, art_path)
    rows = [r for r in svc.list_history() if r.transaction_id == "tx-gate-6"]
    assert rows
    assert rows[0].completed_at is not None
    assert rows[0].started_at <= rows[0].completed_at
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
        UpdateHistoryCreateDto(**kwargs)
