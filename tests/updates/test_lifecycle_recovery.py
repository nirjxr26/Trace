import pytest

from trace_core.core.cli.exit_codes import EXIT_RECOVERY_FAILED
from trace_core.updates.domain import UpdateResult
from trace_core.updates.errors import UpdateError, UpdatePolicyBlockedError
from trace_core.updates.gate import GateDecision
from trace_core.updates.lifecycle import UpdateLifecycle


@pytest.fixture
def install_root(tmp_path, monkeypatch, release_keys):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    return tmp_path


@pytest.fixture
def seeded_install(install_root):
    from trace_updater import updater as updater_mod

    base = install_root / "install"
    for version, payload in (("0.1.0", b"good"), ("0.2.0", b"bad")):
        seed = install_root / f"seed-{version}"
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
    return base


@pytest.fixture
def failing_health_check(monkeypatch):
    from trace_core.core.database import health as health_mod

    real_snapshot = health_mod.fetch_db_snapshot

    def _unhealthy(manager):
        snap = real_snapshot(manager)
        snap.healthy = False
        return snap

    monkeypatch.setattr(health_mod, "fetch_db_snapshot", _unhealthy)


def test_full_lifecycle_success(
    session_manager, temp_storage_root, signed_release, release_keys, monkeypatch, tmp_path
):
    from trace_core.core.settings import settings
    from trace_core.updates import signing

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, _, art_path, _ = signed_release()
    dto = UpdateLifecycle("tx-life-1", session_manager).run(manifest, art_path)
    assert dto.result == UpdateResult.SUCCESS
    assert dto.transaction_id == "tx-life-1"
    from trace_core.updates.marker import read_marker

    marker = read_marker()
    assert marker["transaction_id"] == "tx-life-1"
    assert marker["result"] == "completed"
    assert marker["rollback_performed"] is False


def test_policy_blocked_records_and_raises(session_manager, temp_storage_root, signed_release):
    manifest, _, art_path, _ = signed_release(minimum_supported_version="9.9.9")
    life = UpdateLifecycle("tx-life-2", session_manager)
    with pytest.raises(UpdatePolicyBlockedError):
        life.run(manifest, art_path)


def test_unknown_gate_fails_closed(session_manager, temp_storage_root, signed_release):
    from trace_core.updates.gate import ForensicOperationGate

    class UnknownGate(ForensicOperationGate):
        def can_install_update(self, context=None):
            return GateDecision.UNKNOWN

    manifest, _, art_path, _ = signed_release()
    life = UpdateLifecycle("tx-life-3", session_manager)
    gate = UnknownGate()
    with pytest.raises(UpdateError):
        life.run(manifest, art_path, gate=gate)


def test_health_failure_rolls_back(session_manager, signed_release, seeded_install, failing_health_check):
    manifest, _, art_path, _ = signed_release()
    dto = UpdateLifecycle("tx-life-4", session_manager).run(manifest, art_path)
    assert dto.result == UpdateResult.ROLLED_BACK
    assert dto.rollback is True


def test_rollback_onto_pending_migrations_is_not_passed(session_manager, signed_release, seeded_install, monkeypatch):
    """A rollback landing on a schema with pending migrations is not "passed"."""
    from trace_core.core.database import health as health_mod

    manifest, _, art_path, _ = signed_release()
    real_snapshot = health_mod.fetch_db_snapshot
    calls = {"health_checks": 0}

    def _pending_after_rollback(manager):
        snap = real_snapshot(manager)
        calls["health_checks"] += 1
        if calls["health_checks"] == 1:
            snap.healthy = False  # fails the post-migration health check, triggering rollback
            return snap
        snap.pending = [(17, "subpart3_devices")]  # the restored schema is mid-migration
        return snap

    monkeypatch.setattr(health_mod, "fetch_db_snapshot", _pending_after_rollback)
    dto = UpdateLifecycle("tx-life-4b", session_manager).run(manifest, art_path)
    assert dto.result == UpdateResult.ROLLED_BACK
    assert dto.health_check_result.endswith("health failed")


def test_rollback_failure_enters_recovery(session_manager, signed_release, install_root, failing_health_check):
    manifest, _, art_path, _ = signed_release()
    dto = UpdateLifecycle("tx-life-5", session_manager).run(manifest, art_path)
    assert dto.result == UpdateResult.FAILED
    assert dto.failure_stage == "health"
    # The durable marker is the recovery surface; UpdateLifecycle.load() was deleted
    # rather than repaired, because _run_locked's mandatory CHECKING transition made it
    # raise for every non-idle state.
    from trace_core.updates.marker import read_marker

    assert read_marker()["state"] == "RECOVERY_REQUIRED"


def test_corrupt_marker_recovery(temp_storage_root, session_manager):
    from typer.testing import CliRunner

    from trace_core.cli.main import app

    marker = temp_storage_root / "update-result.json"
    marker.write_text("{not-json", encoding="utf-8")
    res = CliRunner().invoke(app, ["recovery"])
    assert res.exit_code == EXIT_RECOVERY_FAILED
    assert "corrupt" in res.output.lower() or "Recovery Failed" in res.output
