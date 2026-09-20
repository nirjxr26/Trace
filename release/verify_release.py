import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.updates.manifest import load_manifest_dict


def main() -> None:
    from trace_core.core.fs import check_contained

    def _safe_filename(name: str) -> str:
        if not name or "/" in name or "\\" in name or ".." in name:
            raise SystemExit(f"refusing unsafe artifact filename: {name!r}")
        return name

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
    for key, artifact in manifest.artifacts.items():
        path = check_contained(Path("dist") / _safe_filename(artifact.filename), Path.cwd())
        if not path.exists():
            raise SystemExit(f"missing artifact {artifact.filename} for {key}")
        if path.stat().st_size != artifact.size:
            raise SystemExit(f"size drift for {artifact.filename}")
        from trace_core.core.fs import sha256_file

        if sha256_file(path) != artifact.sha256:
            raise SystemExit(f"hash drift for {artifact.filename}")
    import shutil

    from trace_core.updates.trust import trust_root
    from trace_core.updates.verifier import verify_manifest

    for pub in Path("release/trusted-keys").glob("*.pub"):
        shutil.copy2(pub, trust_root() / pub.name)
    for key in manifest.artifacts:
        verify_manifest(
            manifest,
            check_contained(Path("dist") / _safe_filename(manifest.artifacts[key].filename), Path.cwd()),
            platform_key=key,
        )
    print(f"release self-verify passed: {manifest.version} ({len(manifest.artifacts)} artifacts, signatures ok)")


if __name__ == "__main__":
    main()
