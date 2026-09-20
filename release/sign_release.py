import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trace_core.core.fs import check_contained, sha256_file
from trace_core.updates.manifest import load_manifest_dict
from trace_core.updates.signing import canonical_manifest_bytes, key_id_for_pubkey
from trace_core.updates.verifier import assert_safe_filename


def _safe_filename(name: str) -> str:
    try:
        return assert_safe_filename(name)
    except Exception as e:
        raise SystemExit(f"refusing unsafe artifact filename: {name!r} ({e})") from None


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: sign_release.py <manifest>")
    manifest_path = check_contained(Path(sys.argv[1]), Path.cwd())
    from cryptography.hazmat.primitives import serialization

    try:
        raw_priv = os.environ["TRACE_RELEASE_SIGNING_KEY"].strip()
    except KeyError:
        raise SystemExit("TRACE_RELEASE_SIGNING_KEY is not set; refusing to publish unsigned release")
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw_priv))
    raw_pub = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    key_id = key_id_for_pubkey(raw_pub)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in data["artifacts"].values():
        path = check_contained(Path("dist") / _safe_filename(artifact["filename"]), Path.cwd())
        digest = sha256_file(path)
        if digest != artifact["sha256"]:
            raise SystemExit(f"artifact drift before signing: {artifact['filename']}")
        artifact["signature"] = private.sign(path.read_bytes()).hex()
        artifact["signing_key_id"] = key_id
    manifest = load_manifest_dict(data)
    manifest.manifest_signature = private.sign(canonical_manifest_bytes(manifest)).hex()
    manifest.signing_key_id = key_id
    manifest_path.write_text(json.dumps(manifest.model_dump(by_alias=True, mode="json"), indent=2), encoding="utf-8")
    print(f"signed release {manifest.version} with {key_id}")


if __name__ == "__main__":
    main()
