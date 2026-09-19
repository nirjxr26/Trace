import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from trace_core.updates.manifest import load_manifest_dict


def main() -> None:
    manifest_path, tag = Path(sys.argv[1]), sys.argv[2]
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
        path = Path("dist") / artifact.filename
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
        verify_manifest(manifest, Path("dist") / manifest.artifacts[key].filename, platform_key=key)
    print(f"release self-verify passed: {manifest.version} ({len(manifest.artifacts)} artifacts, signatures ok)")


if __name__ == "__main__":
    main()
