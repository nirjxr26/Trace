import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    tag, channel, release_id, out = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
    version = tag.removeprefix("v")
    artifacts = {}
    for path in sorted(Path("dist").glob("*")):
        if not path.is_file():
            continue
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        artifacts[path.name] = {
            "filename": path.name,
            "sha256": h.hexdigest(),
            "size": path.stat().st_size,
            "signature": "",
            "signing_key_id": "",
        }
    manifest = {
        "schema": 1,
        "product": "trace",
        "channel": channel,
        "version": version,
        "release_id": release_id,
        "security_update": False,
        "restart_required": True,
        "manifest_signature": "",
        "signing_key_id": "",
        "artifacts": artifacts,
    }
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
