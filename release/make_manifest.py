import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.core.fs import check_contained


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: make_manifest.py <tag> <channel> <release_id> <out>")
    tag, channel, release_id = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        out = check_contained(Path(sys.argv[4]), Path.cwd())
    except ValueError:
        raise SystemExit("refusing path outside repository") from None
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
