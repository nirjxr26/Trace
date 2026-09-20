import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.unit


@pytest.fixture
def release_keys(temp_storage_root):
    from trace_core.updates import signing

    _ = temp_storage_root
    private = Ed25519PrivateKey.generate()
    raw_pub = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = signing.import_release_pubkey(raw_pub.hex())
    return {"private": private, "key_id": key_id, "pub_hex": raw_pub.hex()}


def _sign(private: Ed25519PrivateKey, data: bytes) -> str:
    return private.sign(data).hex()


@pytest.fixture
def signed_release(tmp_path, release_keys):
    from trace_core.updates import signing
    from trace_core.updates.manifest import ReleaseManifest, load_manifest

    def _make(version="1.5.0", channel="stable", artifact_bytes=b"trace-1.5.0-payload", **over):
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        art_path = tmp_path / f"trace-{version}.bin"
        art_path.write_bytes(artifact_bytes)
        unsigned = {
            "schema": 1,
            "product": "trace",
            "channel": channel,
            "version": version,
            "release_id": over.get("release_id", f"2026-{version}"),
            "security_update": over.get("security_update", False),
            "restart_required": over.get("restart_required", True),
            "manifest_signature": "",
            "signing_key_id": "",
            "artifacts": {
                "default": {
                    "filename": art_path.name,
                    "sha256": digest,
                    "size": len(artifact_bytes),
                    "signature": "",
                    "signing_key_id": "",
                }
            },
        }
        for k in (
            "minimum_supported_version",
            "notes",
            "schema_min",
            "schema_target",
            "backup_required",
            "backup_waiver",
        ):
            if k in over:
                unsigned[k] = over[k]
        art_sig = _sign(release_keys["private"], artifact_bytes)
        unsigned["artifacts"]["default"]["signature"] = art_sig
        unsigned["artifacts"]["default"]["signing_key_id"] = release_keys["key_id"]
        probe = ReleaseManifest.model_validate(unsigned)
        manifest_sig = _sign(release_keys["private"], signing.canonical_manifest_bytes(probe))
        unsigned["manifest_signature"] = manifest_sig
        unsigned["signing_key_id"] = release_keys["key_id"]
        manifest_path = tmp_path / f"manifest-{version}.json"
        manifest_path.write_text(json.dumps(unsigned), encoding="utf-8")
        return load_manifest(manifest_path), manifest_path, art_path, artifact_bytes

    return _make
