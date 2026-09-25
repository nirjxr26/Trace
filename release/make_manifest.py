import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.core.fs import check_contained, ensure_dir


def _parse_manifest_args(argv: list[str]) -> tuple[str, str, str, str, str | None, str | None]:
    positionals: list[str] = []
    options: dict[str, str] = {}
    names = ("--min-version", "--notes")
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        matched = False
        for name in names:
            if arg == name and idx + 1 < len(argv):
                options[name] = argv[idx + 1]
                idx += 2
                matched = True
                break
            if arg.startswith(name + "="):
                options[name] = arg.split("=", 1)[1]
                idx += 1
                matched = True
                break
        if not matched:
            positionals.append(arg)
            idx += 1
    if len(positionals) != 4:
        raise SystemExit("usage: make_manifest.py <tag> <channel> <release_id> <out> [--min-version X] [--notes Y]")
    min_version = options.get("--min-version", os.environ.get("TRACE_MANIFEST_MIN_VERSION"))
    notes = options.get("--notes", os.environ.get("TRACE_MANIFEST_NOTES"))
    if min_version is not None and not min_version.strip():
        min_version = None
    if notes is not None and not notes.strip():
        notes = None
    return positionals[0], positionals[1], positionals[2], positionals[3], min_version, notes


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
