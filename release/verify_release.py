import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.updates.manifest import load_manifest_dict


def _safe_filename(name: str) -> str:
    from trace_core.updates.verifier import assert_safe_filename

    try:
        return assert_safe_filename(name)
    except Exception as e:
        raise SystemExit(f"refusing unsafe artifact filename: {name!r} ({e})") from None


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
    import shutil

    from trace_core.updates.trust import trust_root

    for pub in Path("release/trusted-keys").glob("*.pub"):
        # revoked/ is runtime-only; source-of-truth keys that were revoked must not be re-trusted.
        if not (trust_root() / "revoked" / pub.stem).exists():
            shutil.copy2(pub, trust_root() / pub.name)


def main() -> None:
    from trace_core.core.fs import check_contained
    from trace_core.updates.verifier import verify_manifest

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
    _sync_trusted_keys()
    for key in manifest.artifacts:
        verify_manifest(
            manifest,
            check_contained(Path("dist") / _safe_filename(manifest.artifacts[key].filename), Path.cwd()),
            platform_key=key,
        )
    print(f"release self-verify passed: {manifest.version} ({len(manifest.artifacts)} artifacts, signatures ok)")


if __name__ == "__main__":
    main()
