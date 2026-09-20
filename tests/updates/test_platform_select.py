import pytest

from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.policy import select_artifact

pytestmark = pytest.mark.unit


def test_single_artifact_selected(signed_release):
    manifest, _, _, _ = signed_release()
    assert select_artifact(manifest).filename


def test_multi_untagged_rejected(signed_release):
    from trace_core.updates.manifest import ManifestArtifact

    manifest, _, art_path, _ = signed_release()
    base = manifest.artifacts["default"]
    manifest.artifacts["second"] = ManifestArtifact(
        filename="other.bin",
        sha256=base.sha256,
        size=base.size,
        signature=base.signature,
        signing_key_id=base.signing_key_id,
    )
    with pytest.raises(UpdateVerificationError):
        select_artifact(manifest)


def test_verify_manifest_pins_key(signed_release):
    from trace_core.updates.verifier import verify_manifest

    manifest, _, art_path, _ = signed_release()
    verify_manifest(manifest, art_path, platform_key="default")
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path, platform_key="nope")


def test_explicit_filename_resolves_despite_ambiguity(signed_release, release_keys, tmp_path):
    from trace_core.updates import signing
    from trace_core.updates.manifest import ManifestArtifact
    from trace_core.updates.verifier import verify_manifest

    manifest, _, art_path, _ = signed_release()
    base = manifest.artifacts["default"]
    manifest.artifacts["second"] = ManifestArtifact(
        filename="other.bin",
        sha256=base.sha256,
        size=base.size,
        signature=base.signature,
        signing_key_id=base.signing_key_id,
    )
    manifest.manifest_signature = release_keys["private"].sign(signing.canonical_manifest_bytes(manifest)).hex()
    verify_manifest(manifest, art_path)
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, tmp_path / "unknown.bin")


def test_platform_match_selected(signed_release, monkeypatch):
    import sys

    manifest, _, _, _ = signed_release()
    base = manifest.artifacts["default"]
    other = base.model_copy(update={"filename": "other.bin", "platform": "plan9", "arch": "x64"})
    manifest.artifacts = {"other": other, "mine": base.model_copy(update={"platform": "windows", "arch": "arm64"})}
    monkeypatch.setattr(sys, "platform", "win32")
    import platform as _platform

    monkeypatch.setattr(_platform, "machine", lambda: "ARM64")
    chosen = select_artifact(manifest)
    assert chosen.filename == base.filename


def test_no_match_rejected(signed_release):
    manifest, _, _, _ = signed_release()
    base = manifest.artifacts["default"]
    manifest.artifacts = {
        "a": base.model_copy(update={"platform": "plan9", "arch": "x64"}),
        "b": base.model_copy(update={"platform": "macos", "arch": "x64"}),
    }
    with pytest.raises(UpdateVerificationError):
        select_artifact(manifest)


def test_empty_artifacts_rejected(signed_release):
    manifest, _, _, _ = signed_release()
    manifest.artifacts = {}
    with pytest.raises(UpdateVerificationError):
        select_artifact(manifest)


def test_unknown_channel_rejected(signed_release):
    from trace_core.updates.manifest import load_manifest_dict

    manifest, manifest_path, _, _ = signed_release()
    import json

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["channel"] = "nightly"
    with pytest.raises(UpdateVerificationError):
        load_manifest_dict(data)


def test_oversized_manifest_typed(tmp_path):
    from trace_core.updates.errors import UpdateVerificationError
    from trace_core.updates.manifest import load_manifest

    big = tmp_path / "big.json"
    big.write_bytes(b"x" * (1_048_576 + 1))
    with pytest.raises(UpdateVerificationError):
        load_manifest(big)


def test_strict_key_parse_rejects_garbage(temp_storage_root):
    from trace_core.updates import signing
    from trace_core.updates.errors import UpdateVerificationError

    key_id = signing.import_release_pubkey("ab" * 32)
    from trace_core.updates.trust import trust_key_path

    trust_key_path(key_id).write_text("ab" * 32 + " extra garbage", encoding="utf-8")
    with pytest.raises(UpdateVerificationError):
        signing.load_release_pubkey(key_id)
