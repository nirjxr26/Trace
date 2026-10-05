import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.updates.manifest import load_manifest_dict
from trace_core.updates.trust import KEY_PREFIX
from trace_core.updates.verifier import safe_filename_or_exit


def _safe_filename(name: str) -> str:
    return safe_filename_or_exit(name)


def _verify_artifact_integrity(manifest: object, cwd: Path) -> None:
    from trace_core.core.fs import check_contained, sha256_file

    artifacts = getattr(manifest, "artifacts", {})
    for key, artifact in artifacts.items():
        path = check_contained(Path("dist") / _safe_filename(artifact.filename), cwd)
        if not path.exists():
            raise SystemExit(f"missing artifact {artifact.filename} for {key}")
        if path.stat().st_size != artifact.size:
            raise SystemExit(f"size drift for {artifact.filename}")
        if sha256_file(path) != artifact.sha256:
            raise SystemExit(f"hash drift for {artifact.filename}")


def _sync_trusted_keys() -> None:
    """Import the burned-in keys the manifest was signed with.

    The filename is the trust anchor, and nothing else in the pipeline checks it
    against the key's own content: the bundle is assembled with `basename`, so a
    renamed file would ship a key that no install can ever match. Derive the id
    from the key bytes and refuse on mismatch.
    """

    sources = _collect_trust_sources()
    if not sources:
        raise SystemExit("no trust anchors found in release/trusted-keys or trusted-keys.bundle")
    for stem, hexpub in sources:
        _import_trust_source(stem, hexpub)


def _collect_trust_sources() -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for pub in Path("release/trusted-keys").glob("*.pub"):
        sources.append((pub.stem, pub.read_text(encoding="utf-8").strip()))
    bundle = Path("trusted-keys.bundle")
    if bundle.exists():
        for line in bundle.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                sources.append((parts[0], parts[1]))
    return sources


def _import_trust_source(stem: str, hexpub: str) -> None:
    from trace_core.updates.signing import key_id_for_pubkey
    from trace_core.updates.trust import trust_root

    raw = bytes.fromhex(hexpub)
    derived = key_id_for_pubkey(raw)
    if derived.removeprefix(KEY_PREFIX) != stem:
        raise SystemExit(f"trust anchor {stem!r} does not match its own key content: key derives {derived!r}")
    # revoked/ is runtime-only; source-of-truth keys that were revoked must not be re-trusted.
    if (trust_root() / "revoked" / stem).exists():
        return
    dest = trust_root() / f"{stem}.pub"
    dest.parent.mkdir(parents=True, exist_ok=True)
    from trace_core.core.fs import atomic_write_lines

    atomic_write_lines(dest, [hexpub], mode=0o600)


def _verify_trust_bundle(manifest: object, cwd: Path) -> None:
    """The published bundle must contain the key the manifest was signed with.

    Without this the release cannot be verified on a clean machine, because the
    trust store starts empty and `load_release_pubkey` finds nothing.
    """
    from trace_core.core.fs import check_contained
    from trace_core.updates.signing import key_id_for_pubkey

    bundle = check_contained(Path("trusted-keys.bundle"), cwd)
    if not bundle.exists():
        raise SystemExit("missing trusted-keys.bundle; the release must publish its own trust anchor")
    entries = {}
    for line in bundle.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise SystemExit(f"malformed trusted-keys.bundle line: {line!r}")
        entries[parts[0]] = parts[1]
    signing_key_id = getattr(manifest, "signing_key_id", "")
    stem = signing_key_id.removeprefix(KEY_PREFIX)
    if stem not in entries:
        raise SystemExit(f"bundle does not carry the manifest signing key {signing_key_id!r}")
    raw = bytes.fromhex(entries[stem])
    if key_id_for_pubkey(raw) != signing_key_id:
        raise SystemExit(f"bundle key {stem!r} does not derive {signing_key_id!r}")


def main() -> None:
    from trace_core.core.fs import check_contained

    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_release.py <manifest> <tag>")
    manifest_path, tag = check_contained(Path(sys.argv[1]), Path.cwd()), sys.argv[2]
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = load_manifest_dict(data)
    expected = tag.removeprefix("v")
    if manifest.version != expected:
        raise SystemExit(f"tag/version mismatch: {tag} != {manifest.version}")
    import tomllib

    py_version = tomllib.loads(Path("pyproject.toml").read_bytes().decode())["project"]["version"]
    if py_version != expected:
        raise SystemExit(f"package/version mismatch: {py_version} != {expected}")
    _verify_artifact_integrity(manifest, Path.cwd())
    _verify_trust_bundle(manifest, Path.cwd())
    _sync_trusted_keys()
    from trace_core.updates.verifier import verify_artifact as verify_one_artifact
    from trace_core.updates.verifier import verify_manifest_signature

    verify_manifest_signature(manifest)
    # Selects each artifact by its own manifest key rather than asking the client-side
    # resolver for it, so the update API is not widened for a build-time tool.
    for key, entry in manifest.artifacts.items():
        verify_one_artifact(check_contained(Path("dist") / _safe_filename(entry.filename), Path.cwd()), entry)
    print(f"release self-verify passed: {manifest.version} ({len(manifest.artifacts)} artifacts, signatures ok)")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        print(f"release self-verify FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
