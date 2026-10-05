"""Pre-release rehearsal: run the REAL update pipeline against the published release.

Run this before every release tag. It is not a mock and it is not a re-implementation:
it imports the shipped `trace_core.updates` code and drives it exactly as a user's box
would, so any break in the real path fails here first.

    python release/rehearse_update.py [--manifest URL] [--keep]

What it does, each step through the production code path:

  1. sandbox          isolated storage/trust/install roots (your real box is never touched)
  2. self-heal        a fresh trust store, then run_self_heal() -> proves a brand-new
                      machine can provision the release anchor (the bug that left every
                      Windows box on "unknown release key")
  3. fetch manifest   HttpManifestSource against the published stable.json
  4. verify manifest  verify_manifest_signature with the provisioned anchor
  5. policy           is_installable against the release's own minimum_supported_version
  6. download         stream_artifact_to_file, 1 MB chunks, size-capped
  7. verify artifact  sha256 + Ed25519 signature, exactly like ensure_artifact_path
  8. self-check       cached_check end to end (the path `trace update check` uses)

Exit code 0 only when every step passes.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

DEFAULT_MANIFEST = "https://github.com/nirjxr26/Trace/releases/latest/download/stable.json"

_step_number = 0


def step(title: str) -> None:
    global _step_number
    _step_number += 1
    print(f"\n[{_step_number}] {title}")


def ok(detail: str) -> None:
    print(f"    OK  {detail}")


def fail(detail: str) -> None:
    print(f"    FAIL {detail}")
    raise SystemExit(1)


def sandbox(root: Path) -> Path:
    """Point every derived root (storage, trust, install) inside one temp tree."""
    from trace_core.core.settings import settings

    storage = root / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    settings.storage_root = storage
    import trace_core.updates.selfheal as selfheal_mod
    import trace_core.updates.trust as trust_mod

    trust_mod._TRUST_ROOT_CACHE = None
    selfheal_mod._LAST_HEAL = 0.0
    return storage


def check_self_heal() -> None:
    step("Self-heal on an empty machine (fresh trust store)")
    from trace_core.updates import bootstrap, selfheal
    from trace_core.updates.trust import trust_key_path

    results = {r.name: r for r in selfheal.run_self_heal()}
    for name, result in results.items():
        ok(f"{name}: ok={result.ok} repaired={result.repaired} {result.detail}")
    anchor = results["trust anchor"]
    if not (anchor.ok and anchor.repaired):
        fail(f"a new machine did not provision the release anchor: {anchor.detail}")
    path = trust_key_path(bootstrap.KEY_ID)
    if not path.exists():
        fail(f"trust anchor missing after heal: {path}")
    ok(f"anchor provisioned: {bootstrap.KEY_ID}")


def fetch_manifest(url: str):
    step("Fetch the published manifest over HTTPS")
    from trace_core.updates.sources import HttpManifestSource, split_manifest_url

    base, channel = split_manifest_url(url)
    try:
        raw = HttpManifestSource(base).fetch(channel)
    except Exception as exc:
        fail(f"manifest download failed: {exc}")
    ok(f"{url} ({len(raw)} bytes)")
    return base, channel, raw


def check_manifest_signature(raw: bytes):
    step("Verify the manifest signature with the provisioned anchor")
    from trace_core.updates.manifest import load_manifest_bytes
    from trace_core.updates.signing import verify_manifest_signature

    manifest = load_manifest_bytes(raw)
    try:
        verify_manifest_signature(manifest)
    except Exception as exc:
        fail(f"manifest signature refused: {exc}")
    ok(f"Ed25519 signature valid for {manifest.signing_key_id}, version {manifest.version}")
    return manifest


def check_policy(manifest, channel: str) -> None:
    step("Policy: will a real user box be allowed to install this release?")
    from trace_core.updates.checker import get_installed_version
    from trace_core.updates.policy import is_installable, is_update_available

    current = get_installed_version()
    installable, reason = is_installable(current, manifest, channel, False)
    if not installable:
        fail(f"a box on {current} cannot install this release: {reason}")
    ok(f"box on {current} -> {manifest.version}: installable")
    if is_update_available(current, manifest):
        ok(f"{manifest.version} is newer than {current}, so users WILL receive it")
    else:
        ok(f"box already on {current}: nothing newer to roll out (expected before tagging)")
    floor = manifest.minimum_supported_version
    if not floor:
        return
    blocked, why = is_installable("0.0.1", manifest, channel, False)
    if blocked:
        fail(f"a box below the floor {floor} is still allowed to install: {why}")
    ok(f"boxes below {floor} stay blocked, as intended ({why})")


def download_artifact(manifest, base: str, storage: Path) -> Path:
    step("Download the release artifact (streamed, size-capped)")
    from trace_core.updates.policy import select_artifact
    from trace_core.updates.sources import stream_artifact_to_file
    from trace_core.updates.verifier import assert_safe_filename

    artifact = select_artifact(manifest)
    assert_safe_filename(artifact.filename)
    dest = storage / "state" / "artifacts" / artifact.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream_artifact_to_file(
            base,
            artifact.filename,
            dest,
            max(artifact.size + 1, 1_048_576),
            on_bytes=None,
        )
    except Exception as exc:
        fail(f"artifact download failed: {exc}")
    ok(f"{artifact.filename} ({artifact.size} bytes expected)")
    return dest


def check_artifact_signature(dest: Path, artifact) -> None:
    step("Verify the artifact (size, sha256, Ed25519)")
    from trace_core.updates.verifier import verify_artifact

    try:
        verify_artifact(dest, artifact)
    except Exception as exc:
        fail(f"artifact verification refused: {exc}")
    ok(f"sha256 {artifact.sha256[:16]}... and signature valid")


def check_end_to_end(url: str, channel: str) -> None:
    step("End-to-end `trace update check` on this sandbox")
    from trace_core.updates.checker import cached_check

    payload = cached_check(url, channel)
    ok(f"current={payload['current']} target={payload['target']} available={payload['available']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rehearse the real update pipeline against a published release.")
    parser.add_argument(
        "--manifest", default=DEFAULT_MANIFEST, help="Published manifest URL (default: latest stable.json)"
    )
    parser.add_argument("--keep", action="store_true", help="Keep the sandbox directory for inspection")
    return parser.parse_args(argv)


def run(url: str, root: Path) -> None:
    storage = sandbox(root)
    check_self_heal()
    base, channel, raw = fetch_manifest(url)
    manifest = check_manifest_signature(raw)
    check_policy(manifest, channel)
    from trace_core.updates.policy import select_artifact

    dest = download_artifact(manifest, base, storage)
    check_artifact_signature(dest, select_artifact(manifest))
    check_end_to_end(url, channel)
    step("Cleanup")
    ok("every production code path accepted the release")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(tempfile.mkdtemp(prefix="trace-rehearsal-"))
    print(f"Sandbox: {root}")
    try:
        run(args.manifest, root)
        print("\nREHEARSAL PASSED - the published release installs on a clean machine.")
        return 0
    except SystemExit:
        print("\nREHEARSAL FAILED - do not tag this release.")
        raise
    finally:
        if args.keep:
            print(f"Sandbox kept at {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
