from pathlib import Path

import pytest

from trace_core.updates import bootstrap, selfheal


@pytest.fixture
def storage(temp_storage_root: Path) -> Path:
    import trace_core.updates.trust as trust_mod

    trust_mod._TRUST_ROOT_CACHE = None
    return temp_storage_root


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


def test_bootstrap_matches_burned_in_anchor() -> None:
    from trace_core.updates.signing import key_id_for_pubkey

    keys = sorted(Path("release/trusted-keys").glob("*.pub"))
    assert keys, "no burned-in trust anchors found"
    for path in keys:
        raw = bytes.fromhex(path.read_text(encoding="utf-8").strip())
        assert key_id_for_pubkey(raw).removeprefix("ed25519:") == path.stem
    target = Path(f"release/trusted-keys/{bootstrap.SUFFIX}.pub")
    assert target.read_text(encoding="utf-8").strip() == bootstrap.PUBKEY_HEX
