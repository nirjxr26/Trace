import pytest

from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.verifier import verify_artifact, verify_artifact_content


def test_valid_artifact(signed_release):
    manifest, _, art_path, _ = signed_release()
    verify_artifact(art_path, manifest.artifacts["default"])


def test_modified_artifact_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    art_path.write_bytes(b"tampered-bytes!!")
    with pytest.raises(UpdateVerificationError):
        verify_artifact(art_path, manifest.artifacts["default"])


def test_wrong_size_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.artifacts["default"].size += 1
    with pytest.raises(UpdateVerificationError):
        verify_artifact(art_path, manifest.artifacts["default"])


def test_filename_mismatch_rejected(signed_release, tmp_path):
    manifest, _, art_path, _ = signed_release()
    other = tmp_path / "other.bin"
    other.write_bytes(art_path.read_bytes())
    with pytest.raises(UpdateVerificationError):
        verify_artifact(other, manifest.artifacts["default"])


def test_staged_tmp_name_verifies_by_content(signed_release, tmp_path):
    manifest, _, art_path, _ = signed_release()
    staged = tmp_path / f"{art_path.name}.tmp"
    staged.write_bytes(art_path.read_bytes())
    with pytest.raises(UpdateVerificationError):
        verify_artifact(staged, manifest.artifacts["default"])
    verify_artifact_content(staged, manifest.artifacts["default"])


def test_staged_tmp_tampering_rejected(signed_release, tmp_path):
    manifest, _, art_path, _ = signed_release()
    staged = tmp_path / f"{art_path.name}.tmp"
    staged.write_bytes(b"tampered-bytes!!")
    with pytest.raises(UpdateVerificationError):
        verify_artifact_content(staged, manifest.artifacts["default"])


def test_traversal_filename_rejected(signed_release, tmp_path):
    manifest, _, art_path, _ = signed_release()
    manifest.artifacts["default"].filename = "../evil.bin"
    with pytest.raises(UpdateVerificationError):
        verify_artifact(art_path, manifest.artifacts["default"])


def test_missing_artifact_signature_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.artifacts["default"].signature = ""
    with pytest.raises(UpdateVerificationError):
        verify_artifact(art_path, manifest.artifacts["default"])


def test_wrong_artifact_key_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.artifacts["default"].signing_key_id = "ed25519:0000000000000000"
    with pytest.raises(UpdateVerificationError):
        verify_artifact(art_path, manifest.artifacts["default"])
