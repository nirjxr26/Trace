import pytest

from trace_updater import updater as updater_mod


def test_partial_resume_and_promote(tmp_path):
    src = tmp_path / "payload.bin"
    src.write_bytes(b"x" * 1000)
    staging = tmp_path / "staging"
    import hashlib

    digest = hashlib.sha256(b"x" * 1000).hexdigest()
    first = updater_mod.stage_artifact(src, staging, expected_sha256=digest)
    assert first.exists()
    assert (staging / "payload.bin").exists()


def test_hash_mismatch_discards_partial(tmp_path):
    src = tmp_path / "payload.bin"
    src.write_bytes(b"good-bytes")
    staging = tmp_path / "staging"
    with pytest.raises(ValueError):
        updater_mod.stage_artifact(src, staging, expected_sha256="0" * 64)
    assert not (staging / "payload.bin").exists()


def test_staged_record_binding(tmp_path, signed_release):
    from trace_core.updates import staging as staging_mod

    manifest, _, art_path, _ = signed_release()
    staging = tmp_path / "staging"
    staging.mkdir()
    record = {
        "release_id": manifest.release_id,
        "version": manifest.version,
        "filename": art_path.name,
        "expected_sha256": manifest.artifacts["default"].sha256,
        "actual_sha256": manifest.artifacts["default"].sha256,
        "signing_key_id": manifest.signing_key_id,
        "verification": "passed",
    }
    staging_mod.write_staged_record(staging, record)
    assert staging_mod.is_verified_stage(staging, art_path) is True
    art_path.write_bytes(b"swapped")
    assert staging_mod.is_verified_stage(staging, art_path) is False
    with pytest.raises(ValueError):
        staging_mod.write_staged_record(staging, {"release_id": "x"})


def test_version_owned_activation_and_rollback(tmp_path):
    base = tmp_path / "install"
    v1 = tmp_path / "v1"
    (v1).mkdir()
    (v1 / "trace.bin").write_bytes(b"v1")
    v2 = tmp_path / "v2"
    (v2).mkdir()
    (v2 / "trace.bin").write_bytes(b"v2")
    updater_mod.stage_release(v1, base, "1.4.2", expected=["trace.bin"])
    updater_mod.activate(base, "1.4.2")
    assert updater_mod.read_active(base) == "1.4.2"
    updater_mod.stage_release(v2, base, "1.5.0", expected=["trace.bin"])
    updater_mod.activate(base, "1.5.0")
    assert updater_mod.read_active(base) == "1.5.0"
    assert updater_mod.read_previous(base) == "1.4.2"
    assert (base / "releases" / "1.4.2" / "trace.bin").read_bytes() == b"v1"
    assert updater_mod.rollback(base) == "1.4.2"
    assert updater_mod.read_active(base) == "1.4.2"
    assert updater_mod.read_previous(base) == "1.4.2"
    assert updater_mod.rollback(base) == "1.4.2"
    assert updater_mod.read_previous(base) == "1.4.2"


def test_crash_before_activation_leaves_no_active(tmp_path):
    base = tmp_path / "install"
    v1 = tmp_path / "v1"
    v1.mkdir()
    (v1 / "trace.bin").write_bytes(b"v1")
    updater_mod.stage_release(v1, base, "1.4.2", expected=["trace.bin"])
    assert updater_mod.read_active(base) is None
    assert (base / "releases" / "1.4.2").exists()


def test_immutable_release_rejected(tmp_path):
    base = tmp_path / "install"
    v1 = tmp_path / "v1"
    v1.mkdir()
    (v1 / "trace.bin").write_bytes(b"v1")
    updater_mod.stage_release(v1, base, "1.4.2", expected=["trace.bin"])
    with pytest.raises(FileExistsError):
        updater_mod.stage_release(v1, base, "1.4.2", expected=["trace.bin"])


def test_concurrent_update_lock_serializes(temp_storage_root):
    import threading

    from trace_core.updates.lock import update_lock

    order = []
    guard = threading.Lock()

    def _work(n):
        with update_lock():
            with guard:
                order.append(f"enter-{n}")
            import time

            time.sleep(0.05)
            with guard:
                order.append(f"exit-{n}")

    threads = [threading.Thread(target=_work, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(order) == 4
    assert order[1].startswith("exit-")
