import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.core.database.migrations import MIGRATIONS
from trace_core.core.fs import check_contained, ensure_dir, sha256_file

POLICY_PATH = Path(__file__).resolve().parent / "release_policy.json"


def _release_policy(path: str | Path) -> dict[str, str]:
    """The update floor and its migration notes, from version control.

    These were workflow_dispatch inputs, which are empty on a tag push — the normal release
    path. The shell fallbacks that covered for that made the "fail closed" assertion
    unfailable, and removing them without moving the source of truth meant a tag push could
    not publish at all. The floor is a property of the release, so it belongs in the repo
    where a reviewer can see and change it in the same diff as the code.
    """
    try:
        target = check_contained(Path(path), Path(__file__).resolve().parent)
    except ValueError:
        raise SystemExit("refusing release policy outside the release directory") from None
    try:
        policy = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read release policy {target}: {e}") from None
    if not isinstance(policy, dict):
        raise SystemExit(f"release policy {target} must be a JSON object")
    return {str(k): str(v) for k, v in policy.items()}


def _parse_manifest_args(argv: list[str]) -> tuple[str, str, str, str, str | None, str | None]:
    parser = argparse.ArgumentParser(prog="make_manifest.py")
    parser.add_argument("tag")
    parser.add_argument("channel")
    parser.add_argument("release_id")
    parser.add_argument("out")
    parser.add_argument("--min-version")
    parser.add_argument("--notes")
    parser.add_argument("--policy", default=str(POLICY_PATH))
    ns = parser.parse_args(argv)
    policy = _release_policy(ns.policy)
    # Explicit flag > env > committed policy. The policy is the default so a tag push works.
    min_version = (
        ns.min_version or os.environ.get("TRACE_MANIFEST_MIN_VERSION") or policy.get("minimum_supported_version")
    )
    notes = ns.notes or os.environ.get("TRACE_MANIFEST_NOTES") or policy.get("notes")
    return ns.tag, ns.channel, ns.release_id, ns.out, min_version or None, notes or None


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
    # A release that cannot state its floor must not ship one. The workflow's "fail closed"
    # assertion could never fire because two shell fallbacks above it guaranteed both
    # values were non-empty, so a tag push published floor 0.2.5 whatever the real minimum
    # was. Failing here means a missing floor stops the build instead of silently shipping
    # a wrong one.
    missing = [name for name, value in (("min-version", min_version), ("notes", notes)) if not value]
    if missing:
        raise SystemExit(f"refusing to publish a release without {' and '.join(missing)}")
    manifest["minimum_supported_version"] = min_version
    manifest["notes"] = notes
    manifest["schema_min"] = 1
    manifest["schema_target"] = MIGRATIONS[-1][0]
    ensure_dir(out.parent)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
