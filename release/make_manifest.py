import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.core.fs import check_contained, ensure_dir, sha256_file


def _parse_manifest_args(argv: list[str]) -> tuple[str, str, str, str, str | None, str | None]:
    parser = argparse.ArgumentParser(prog="make_manifest.py")
    parser.add_argument("tag")
    parser.add_argument("channel")
    parser.add_argument("release_id")
    parser.add_argument("out")
    parser.add_argument("--min-version", default=os.environ.get("TRACE_MANIFEST_MIN_VERSION"))
    parser.add_argument("--notes", default=os.environ.get("TRACE_MANIFEST_NOTES"))
    ns = parser.parse_args(argv)
    return ns.tag, ns.channel, ns.release_id, ns.out, ns.min_version or None, ns.notes or None


def main() -> None:
    tag, channel, release_id, out_arg, min_version, notes = _parse_manifest_args(sys.argv[1:])
    try:
        out = check_contained(Path(out_arg), Path.cwd())
    except ValueError:
        raise SystemExit("refusing path outside repository") from None
    version = tag.removeprefix("v")
    # Exactly one installable wheel per manifest, enforced at build time: the
    # client refuses multi-universal manifests rather than guessing (fail-closed
    # on user machines helps nobody — fail here instead). Sdists, SBOMs, and
    # checksums stay published and hash-covered, just outside the install set.
    # (Frozen per-OS bundles will extend this with tagged platform/arch entries.)
    artifacts = {}
    for path in sorted(Path("dist").glob("*.whl")):
        if not path.is_file():
            continue
        artifacts[path.name] = {
            "filename": path.name,
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "signature": "",
            "signing_key_id": "",
        }
    if len(artifacts) != 1:
        raise SystemExit(
            f"release must ship exactly one installable wheel, found {len(artifacts)}: {sorted(artifacts)}"
        )
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
    if min_version is not None:
        manifest["minimum_supported_version"] = min_version
    if notes is not None:
        manifest["notes"] = notes
    ensure_dir(out.parent)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
