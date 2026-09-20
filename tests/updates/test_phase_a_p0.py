import pytest

from trace_core.updates.errors import UpdatePolicyBlockedError, UpdateVerificationError

pytestmark = pytest.mark.unit


def test_gate_active_probe_blocks_install(session_manager, temp_storage_root, signed_release):
    from trace_core.updates.gate import ForensicOperationGate, UpdateGateContext
    from trace_core.updates.lifecycle import UpdateLifecycle
    from trace_core.updates.service import UpdateService

    seen = {}

    def _probe(context):
        seen["context"] = context
        return True

    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    gate = ForensicOperationGate(active_probe=_probe)
    with pytest.raises(UpdatePolicyBlockedError, match="forensic operation active"):
        UpdateLifecycle("tx-p0-gate", svc).run(manifest, art_path, gate=gate)
    assert isinstance(seen["context"], UpdateGateContext)
    assert seen["context"].transaction_id == "tx-p0-gate"


def test_gate_probe_error_fails_closed(session_manager, temp_storage_root, signed_release):
    from trace_core.updates.errors import UpdateError
    from trace_core.updates.gate import ForensicOperationGate
    from trace_core.updates.lifecycle import UpdateLifecycle
    from trace_core.updates.service import UpdateService

    def _boom(context):
        raise RuntimeError("probe down")

    manifest, _, art_path, _ = signed_release()
    svc = UpdateService(session_manager)
    with pytest.raises(UpdateError, match="failing closed"):
        UpdateLifecycle("tx-p0-gate-unknown", svc).run(manifest, art_path, gate=ForensicOperationGate(_boom))


def test_stage_release_excludes_sidecars(tmp_path):
    from trace_updater import updater as updater_mod

    src = tmp_path / "src"
    src.mkdir()
    (src / "trace.bin").write_bytes(b"v1")
    (src / "staged.json").write_text("{}", encoding="utf-8")
    (src / "trace.bin.partial.json").write_text("{}", encoding="utf-8")
    base = tmp_path / "install"
    release = updater_mod.stage_release(src, base, "1.4.2", expected=["trace.bin"])
    assert (release / "trace.bin").exists()
    assert not (release / "staged.json").exists()
    assert not (release / "trace.bin.partial.json").exists()


def test_strict_key_import_rejects_trailing_garbage(release_keys):
    from trace_core.updates import signing

    with pytest.raises(UpdateVerificationError):
        signing.import_release_pubkey(release_keys["pub_hex"] + " extra-garbage")


def test_ipv6_loopback_with_port_allowed():
    from trace_core.updates.errors import UpdateError
    from trace_core.updates.sources import _validate_manifest_url

    _validate_manifest_url("http://[::1]:8000/stable.json")
    _validate_manifest_url("http://localhost:8000/stable.json")
    _validate_manifest_url("https://updates.example.com/stable.json")
    with pytest.raises(UpdateError):
        _validate_manifest_url("http://updates.example.com/stable.json")


def test_trust_path_traversal_rejected(temp_storage_root):
    from trace_core.updates.trust import revoked_path, trust_key_path

    with pytest.raises(UpdateVerificationError):
        trust_key_path("ed25519:../../../etc/passwd")
    with pytest.raises(UpdateVerificationError):
        revoked_path("ed25519:../../../etc/passwd")
