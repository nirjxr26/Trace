import json

import pytest

from trace_core.updates import signing
from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.verifier import verify_manifest


def _unsigned_dict(manifest_path):
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_valid_manifest(signed_release):
    manifest, _, art_path, _ = signed_release()
    verify_manifest(manifest, art_path)


def test_modified_manifest_rejected(signed_release):
    manifest, manifest_path, art_path, _ = signed_release()
    data = _unsigned_dict(manifest_path)
    data["version"] = "9.9.9"
    from trace_core.updates.manifest import load_manifest_dict

    tampered = load_manifest_dict(data)
    with pytest.raises(UpdateVerificationError):
        verify_manifest(tampered, art_path)


def test_invalid_signature_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.manifest_signature = "00" * 64
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path)


def test_unknown_key_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.signing_key_id = "ed25519:ffffffffffffffff"
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path)


def test_revoked_key_rejected(signed_release, release_keys):
    manifest, _, art_path, _ = signed_release()
    signing.revoke_release_key(release_keys["key_id"])
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path)


def test_wrong_algorithm_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.signing_key_id = "hmac-v1"
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path)


def test_missing_signature_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.manifest_signature = ""
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path)


def test_missing_key_rejected(signed_release):
    manifest, _, art_path, _ = signed_release()
    manifest.signing_key_id = ""
    with pytest.raises(UpdateVerificationError):
        verify_manifest(manifest, art_path)
