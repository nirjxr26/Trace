import pytest

from trace_core.updates.domain import UpdateResult
from trace_core.updates.errors import UpdateError, UpdatePolicyBlockedError
from trace_core.updates.gate import GateDecision
from trace_core.updates.lifecycle import UpdateLifecycle
from trace_core.updates.service import UpdateService


def test_full_lifecycle_success(
    session_manager, temp_storage_root, signed_release, release_keys, monkeypatch, tmp_path
):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    dto = UpdateLifecycle("tx-life-1", svc).run(manifest, art_path)
    assert dto.result == UpdateResult.SUCCESS
    assert dto.transaction_id == "tx-life-1"
    rows = svc.list_history()
    assert any(r.transaction_id == "tx-life-1" and r.result == "SUCCESS" for r in rows)
    marker = svc.read_result_marker()
    assert marker is not None
    assert marker["transaction_id"] == "tx-life-1"
    assert marker["result"] == "completed"
    assert marker["rollback_performed"] is False


def test_policy_blocked_records_and_raises(session_manager, temp_storage_root, signed_release):
    manifest, _, art_path, _ = signed_release(minimum_supported_version="9.9.9")
    svc = UpdateService(session_manager)
    life = UpdateLifecycle("tx-life-2", svc)
    with pytest.raises(UpdatePolicyBlockedError):
        life.run(manifest, art_path)
    rows = svc.list_history()
    assert any(r.transaction_id == "tx-life-2" and r.result == "FAILED" for r in rows)


def test_unknown_gate_fails_closed(session_manager, temp_storage_root, signed_release):
    from trace_core.updates.gate import ForensicOperationGate

    class UnknownGate(ForensicOperationGate):
        def can_install_update(self):
            return GateDecision.UNKNOWN

    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    life = UpdateLifecycle("tx-life-3", svc)
    with pytest.raises(UpdateError):
        life.run(manifest, art_path, gate=UnknownGate())


def test_health_failure_rolls_back(
    session_manager, temp_storage_root, signed_release, release_keys, monkeypatch, tmp_path
):
    from trace_core.core.database import health as health_mod
    from trace_core.core.settings import settings
    from trace_updater import updater as updater_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    from trace_core.updates import signing

    signing.import_release_pubkey(release_keys["pub_hex"])
    base = tmp_path / "install"
    for version, payload in (("0.1.0", b"good"), ("0.2.0", b"bad")):
        seed = tmp_path / f"seed-{version}"
        seed.mkdir()
        (seed / "trace.bin").write_bytes(payload)
        updater_mod.stage_release(
            seed,
            base,
            version,
            expected=["trace.bin"],
            release_meta={"version": version, "schema_min": 1, "schema_target": 99},
        )
        updater_mod.activate(base, version)

    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    real_snapshot = health_mod.fetch_db_snapshot

    def _unhealthy(manager):
        snap = real_snapshot(manager)
        snap.healthy = False
        return snap

    monkeypatch.setattr(health_mod, "fetch_db_snapshot", _unhealthy)
    dto = UpdateLifecycle("tx-life-4", svc).run(manifest, art_path)
    assert dto.result == UpdateResult.ROLLED_BACK
    assert dto.rollback is True


def test_rollback_failure_enters_recovery(
    session_manager, temp_storage_root, signed_release, release_keys, monkeypatch, tmp_path
):
    from trace_core.core.database import health as health_mod
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    real_snapshot = health_mod.fetch_db_snapshot

    def _unhealthy(manager):
        snap = real_snapshot(manager)
        snap.healthy = False
        return snap

    monkeypatch.setattr(health_mod, "fetch_db_snapshot", _unhealthy)
    dto = UpdateLifecycle("tx-life-5", svc).run(manifest, art_path)
    assert dto.result == UpdateResult.FAILED
    assert dto.failure_stage == "health"
    recovered = UpdateLifecycle.load("tx-life-5", svc)
    assert recovered.state.value == "RECOVERY_REQUIRED"


def test_corrupt_marker_recovery(temp_storage_root, session_manager):
    from typer.testing import CliRunner

    from trace_core.cli.main import app

    marker = temp_storage_root / "update-result.json"
    marker.write_text("{not-json", encoding="utf-8")
    res = CliRunner().invoke(app, ["recovery"])
    assert res.exit_code == 15
    assert "corrupt" in res.output.lower() or "Recovery Failed" in res.output
