import pytest

from trace_core.updates.errors import UpdateVerificationError

pytestmark = pytest.mark.unit


def test_stable_rejects_nightly(signed_release):
    from trace_core.updates.manifest import load_manifest_dict
    from trace_core.updates.policy import is_installable

    manifest, manifest_path, _, _ = signed_release()
    import json

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["channel"] = "nightly"
    data["version"] = "1.5.0"
    from trace_core.updates import signing as signing_mod

    probe = load_manifest_dict({**data, "channel": "stable"})
    tampered_channel = probe.model_copy(update={"channel": "nightly"})
    ok, reason = is_installable("0.1.0", tampered_channel, "stable")
    assert ok is False
    assert reason is not None
    _ = signing_mod


def test_beta_accepts_stable(signed_release):
    from trace_core.updates.policy import is_installable

    manifest, _, _, _ = signed_release(channel="stable")
    ok, _ = is_installable("0.1.0", manifest, "beta")
    assert ok is True


def test_duplicate_filename_rejected(signed_release):
    import hashlib
    import json

    from trace_core.updates.manifest import load_manifest_dict
    from trace_core.updates.verifier import resolve_artifact

    manifest, manifest_path, art_path, _ = signed_release()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    dup = dict(data["artifacts"]["default"])
    data["artifacts"]["second"] = dup
    loaded = load_manifest_dict(data)
    with pytest.raises(UpdateVerificationError, match="duplicate filename"):
        resolve_artifact(loaded, art_path)
    _ = hashlib


def test_missing_hash_typed(tmp_path):
    from trace_core.updates.errors import UpdateVerificationError
    from trace_updater import updater as updater_mod

    src = tmp_path / "payload.bin"
    src.write_bytes(b"bytes")
    with pytest.raises(UpdateVerificationError):
        updater_mod.stage_artifact(src, tmp_path / "staging", expected_sha256=None)


def test_owner_needs_context_not_just_file(temp_storage_root):
    import threading

    from trace_core.updates.migration import (
        begin_update_migration,
        finish_update_migration,
        is_owner,
        update_migration_owner,
    )

    begin_update_migration("tx-owner-1")
    try:
        assert is_owner("tx-owner-1") is False
        assert is_owner("tx-other") is False
        with update_migration_owner("tx-owner-1"):
            assert is_owner("tx-owner-1") is True
            assert is_owner("tx-other") is False
        seen = {}

        def _probe():
            seen["bare"] = is_owner("tx-owner-1")

        thread = threading.Thread(target=_probe)
        thread.start()
        thread.join()
        assert seen["bare"] is False
    finally:
        finish_update_migration("tx-owner-1")


def test_migration_self_owns_worker_thread(session_manager, temp_storage_root):
    import threading

    from trace_core.updates.migration import marker_state, run_updater_migration

    seen = {}

    def _work():
        try:
            seen["result"] = run_updater_migration(session_manager, "tx-worker-1")
        except Exception as e:  # noqa: BLE001
            seen["error"] = e

    thread = threading.Thread(target=_work)
    thread.start()
    thread.join()
    assert "error" not in seen
    assert seen["result"]["schema"] >= 0
    assert marker_state() == ("absent", None)


def test_recovery_edges_legal():
    from trace_core.updates.domain import UpdateState, can_transition

    assert can_transition(UpdateState.IDLE, UpdateState.FAILED) is True
    assert can_transition(UpdateState.FAILED, UpdateState.IDLE) is True
    assert can_transition(UpdateState.RECOVERY_REQUIRED, UpdateState.IDLE) is True


def test_run_keyword_only(session_manager, signed_release):
    from trace_core.updates.lifecycle import UpdateLifecycle
    from trace_core.updates.service import UpdateService

    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    run_fn = getattr(UpdateLifecycle("tx-kw", svc), "run")
    with pytest.raises(TypeError):
        run_fn(manifest, art_path, "stable")


def test_manifest_schema_range_both_or_neither(signed_release):
    import json

    from trace_core.updates.manifest import load_manifest_dict

    _, manifest_path, _, _ = signed_release()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["schema_min"] = 5
    data.pop("schema_target", None)
    with pytest.raises(UpdateVerificationError):
        load_manifest_dict(data)
