import pathlib
from pathlib import Path

import pytest

from trace_core.updates import bootstrap, selfheal


@pytest.fixture
def storage(temp_storage_root: Path) -> Path:
    import trace_core.updates.trust as trust_mod

    trust_mod._TRUST_ROOT_CACHE = None
    return temp_storage_root


class _StubEngine:
    def __enter__(self) -> "_StubEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def begin(self) -> "_StubEngine":
        return self

    def connect(self) -> "_StubEngine":
        return self


class _StubManager:
    engine = _StubEngine()


def test_self_heal_provisions_missing_anchor(storage: Path) -> None:
    results = {r.name: r for r in selfheal.run_self_heal()}
    anchor = results["trust anchor"]
    assert anchor.ok
    assert anchor.repaired
    from trace_core.updates.trust import trust_key_path

    assert trust_key_path(bootstrap.KEY_ID).exists()


def test_self_heal_anchor_idempotent(storage: Path) -> None:
    selfheal.run_self_heal()
    results = {r.name: r for r in selfheal.run_self_heal()}
    assert results["trust anchor"].ok
    assert not results["trust anchor"].repaired


def test_self_heal_removes_corrupt_state_files(storage: Path) -> None:
    state = storage / "state"
    state.mkdir()
    cache = state / "update-check.json"
    cache.write_text("{not json", encoding="utf-8")
    results = {r.name: r for r in selfheal.run_self_heal()}
    assert results["state files"].repaired
    assert not cache.exists()


def test_self_heal_cleans_tmp_artifacts(storage: Path) -> None:
    artifacts = storage / "state" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "wheel.tmp").write_bytes(b"partial")
    results = {r.name: r for r in selfheal.run_self_heal()}
    assert results["artifact tmp"].repaired
    assert not (artifacts / "wheel.tmp").exists()


def test_signing_recovers_through_selfheal(storage: Path, monkeypatch) -> None:
    from trace_core.updates.signing import load_release_pubkey

    raw = load_release_pubkey(bootstrap.KEY_ID)
    assert raw == bytes.fromhex(bootstrap.PUBKEY_HEX)


def _patch_drift(monkeypatch) -> list[int]:
    from trace_core.core.database import migrations as migrations_mod
    from trace_core.core.database import session as session_mod

    applied: list[int] = []
    monkeypatch.setattr(migrations_mod, "MIGRATIONS", ((18, "018_device_table", lambda fix: applied.append(18)),))
    monkeypatch.setattr(migrations_mod, "MIGRATION_VERIFIERS", {18: lambda conn: bool(applied)})
    monkeypatch.setattr(migrations_mod, "apply_migrations", lambda engine: None)
    monkeypatch.setattr(session_mod, "db_manager", _StubManager())
    monkeypatch.setattr(selfheal, "_recorded", lambda conn, version: True)
    return applied


def test_a_recorded_migration_whose_verifier_fails_is_reapplied(monkeypatch) -> None:
    applied = _patch_drift(monkeypatch)

    assert selfheal.heal_schema_drift() is True
    assert applied == [18]


def test_a_migration_whose_repair_does_not_take_is_rolled_back(monkeypatch) -> None:
    _patch_drift(monkeypatch)
    from trace_core.core.database import migrations as migrations_mod

    monkeypatch.setattr(migrations_mod, "MIGRATION_VERIFIERS", {18: lambda conn: False})

    with pytest.raises(RuntimeError, match="failed re-verification"):
        selfheal.heal_schema_drift()


def test_a_verified_migration_is_left_alone(monkeypatch) -> None:
    applied = _patch_drift(monkeypatch)
    from trace_core.core.database import migrations as migrations_mod

    monkeypatch.setattr(migrations_mod, "MIGRATION_VERIFIERS", {18: lambda conn: True})

    assert selfheal.heal_schema_drift() is False
    assert applied == []


def test_bootstrap_matches_burned_in_anchor() -> None:
    from trace_core.updates.signing import key_id_for_pubkey

    keys = sorted(Path("release/trusted-keys").glob("*.pub"))
    assert keys, "no burned-in trust anchors found"
    for path in keys:
        raw = bytes.fromhex(path.read_text(encoding="utf-8").strip())
        assert key_id_for_pubkey(raw).removeprefix("ed25519:") == path.stem
    target = Path(f"release/trusted-keys/{bootstrap.SUFFIX}.pub")
    assert target.read_text(encoding="utf-8").strip() == bootstrap.PUBKEY_HEX


def test_an_unreadable_state_file_is_never_deleted(tmp_path, monkeypatch) -> None:
    """A locked file is unreadable, not corrupt. Deleting it destroyed the only record of
    an interrupted update, and the run reported a successful repair."""
    from trace_core.updates import selfheal

    locked = tmp_path / "update-active.json"
    locked.write_text('{"transaction_id": "tx-1", "state": "MIGRATING"}', encoding="utf-8")
    monkeypatch.setattr(selfheal, "state_file_paths", lambda: (locked,))

    def _denied(self, *args, **kwargs):
        raise PermissionError(32, "file in use by another process")

    monkeypatch.setattr(pathlib.Path, "read_text", _denied)

    result = selfheal.check_state_json()
    assert locked.exists(), "an unreadable state file must be left in place"
    assert result.repaired is False, "must not be reported as a successful repair"
    assert result.ok is False
    assert "could not read" in result.detail
    assert "trace recovery" in result.detail


def test_a_genuinely_corrupt_state_file_is_removed(tmp_path, monkeypatch) -> None:
    """Different condition, different path. It really is damaged, so removal is correct."""
    from trace_core.updates import selfheal

    corrupt = tmp_path / "update-active.json"
    corrupt.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setattr(selfheal, "state_file_paths", lambda: (corrupt,))

    result = selfheal.check_state_json()
    assert not corrupt.exists()
    assert result.repaired is True
    assert result.ok is True


def test_a_state_file_that_is_not_an_object_is_corrupt(tmp_path, monkeypatch) -> None:
    from trace_core.updates import selfheal

    wrong_type = tmp_path / "update-result.json"
    wrong_type.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(selfheal, "state_file_paths", lambda: (wrong_type,))
    result = selfheal.check_state_json()
    assert not wrong_type.exists()
    assert result.repaired is True


def test_a_healthy_state_file_is_left_alone(tmp_path, monkeypatch) -> None:
    from trace_core.updates import selfheal

    healthy = tmp_path / "update-active.json"
    healthy.write_text('{"transaction_id": "tx-1", "state": "IDLE"}', encoding="utf-8")
    monkeypatch.setattr(selfheal, "state_file_paths", lambda: (healthy,))
    result = selfheal.check_state_json()
    assert healthy.exists()
    assert result.repaired is False
    assert result.ok is True


def test_self_heal_failures_reach_the_log(tmp_path, monkeypatch, caplog) -> None:
    """`_maybe_heal` discarded run_self_heal()'s return, so a failure was invisible."""
    from trace_core.updates import selfheal

    captured: list[dict] = []

    class _Log:
        def warning(self, event, **kwargs):
            captured.append({"event": event, **kwargs})

    monkeypatch.setattr(selfheal.structlog, "get_logger", lambda: _Log())
    monkeypatch.setattr(selfheal, "_LAST_HEAL", 0.0)
    monkeypatch.setattr(
        selfheal,
        "run_self_heal",
        lambda: [selfheal.SelfCheck("state files", False, "could not read x - left in place")],
    )
    monkeypatch.setattr(selfheal, "heal_schema_drift", lambda: False)
    selfheal._maybe_heal()
    assert any(c["event"] == "self-heal check failed" for c in captured), captured
