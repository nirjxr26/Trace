import os
import shutil
from pathlib import Path

from trace_core.core.fs import atomic_write_lines, check_contained, ensure_dir, sha256_file
from trace_core.updates.lock import update_lock


def releases_root(base: str | Path) -> Path:
    return ensure_dir(Path(base) / "releases")


def staging_root(base: str | Path) -> Path:
    return ensure_dir(Path(base) / "staging")


def active_path(base: str | Path) -> Path:
    return Path(base) / "active-version"


def previous_path(base: str | Path) -> Path:
    return Path(base) / "previous-version"


def read_active(base: str | Path) -> str | None:
    p = active_path(base)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def read_previous(base: str | Path) -> str | None:
    p = previous_path(base)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def _binding_path(staging_dir: Path, name: str) -> Path:
    return staging_dir / f"{name}.partial.json"


def _read_binding(staging_dir: Path, name: str) -> dict | None:
    import json

    target = _binding_path(staging_dir, name)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def stage_artifact(
    src: Path,
    staging_dir: Path,
    expected_sha256: str | None = None,
    binding: dict | None = None,
) -> Path:
    with update_lock():
        return _stage_artifact_locked(src, staging_dir, expected_sha256, binding)


def _stage_artifact_locked(
    src: Path,
    staging_dir: Path,
    expected_sha256: str | None,
    binding: dict | None,
) -> Path:

    ensure_dir(staging_dir)
    dst = staging_dir / src.name
    check_contained(dst, staging_dir)
    tmp = staging_dir / f"{src.name}.partial"
    check_contained(tmp, staging_dir)
    if expected_sha256 is None:
        raise ValueError("staging requires an expected hash")
    offset = _stage_copy(src, staging_dir, dst, tmp, expected_sha256, binding)
    return offset


def _stage_copy(  # type: ignore[no-untyped-def]
    src: Path, staging_dir: Path, dst: Path, tmp: Path, expected_sha256: str | None, binding: dict | None
):
    import json

    offset = 0
    if tmp.exists():
        prior = _read_binding(staging_dir, src.name)
        if (
            prior is None
            or binding is None
            or prior.get("transaction_id") != binding.get("transaction_id")
            or prior.get("release_id") != binding.get("release_id")
            or prior.get("expected_sha256") != expected_sha256
            or prior.get("expected_size") != src.stat().st_size
            or tmp.stat().st_size > 100 * 1024 * 1024
        ):
            tmp.unlink(missing_ok=True)
            _binding_path(staging_dir, src.name).unlink(missing_ok=True)
        else:
            offset = tmp.stat().st_size
    if offset == 0 and binding is not None:
        record = {
            **binding,
            "filename": src.name,
            "expected_sha256": expected_sha256,
            "expected_size": src.stat().st_size,
        }
        _binding_path(staging_dir, src.name).write_text(json.dumps(record), encoding="utf-8")
    with src.open("rb") as fin:
        fin.seek(offset)
        with tmp.open("ab" if offset else "wb") as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
    if sha256_file(tmp) != expected_sha256:
        tmp.unlink(missing_ok=True)
        _binding_path(staging_dir, src.name).unlink(missing_ok=True)
        raise ValueError("staged artifact hash mismatch")
    tmp.replace(dst)
    _binding_path(staging_dir, src.name).unlink(missing_ok=True)
    return dst


def stage_release(
    src_dir: Path,
    base: str | Path,
    version: str,
    expected: list[str] | None = None,
    release_meta: dict | None = None,
) -> Path:
    with update_lock():
        return _stage_release_locked(src_dir, base, version, expected, release_meta)


def _stage_release_locked(
    src_dir: Path,
    base: str | Path,
    version: str,
    expected: list[str] | None,
    release_meta: dict | None,
) -> Path:
    import json

    root = releases_root(base)
    target = root / version
    check_contained(target, root)
    if target.exists():
        raise FileExistsError(f"release {version} already staged; releases are immutable")
    tmp = root / f".staging-{version}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src_dir, tmp)
    if expected:
        missing = [f for f in expected if not (tmp / f).exists()]
        if missing:
            shutil.rmtree(tmp)
            raise FileNotFoundError(f"incomplete release {version}: {missing}")
    if release_meta is not None:
        (tmp / "release.json").write_text(json.dumps(release_meta, indent=2), encoding="utf-8")
    os.rename(tmp, target)
    return target


def read_release_meta(base: str | Path, version: str) -> dict | None:
    import json

    target = releases_root(base) / version / "release.json"
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _set_active(base: str | Path, version: str) -> None:
    atomic_write_lines(active_path(base), [version])


def activate(base: str | Path, version: str) -> None:
    with update_lock():
        root = releases_root(base)
        target = root / version
        check_contained(target, root)
        if not target.is_dir() or not any(target.iterdir()):
            raise FileNotFoundError(f"release {version} is not a complete staged release")
        current = read_active(base)
        if current and current != version:
            atomic_write_lines(previous_path(base), [current])
        _set_active(base, version)


def rollback(base: str | Path) -> str:
    with update_lock():
        root = releases_root(base)
        previous = read_previous(base)
        if not previous:
            raise FileNotFoundError("no previous version to restore")
        target = root / previous
        check_contained(target, root)
        if not target.is_dir() or not any(target.iterdir()):
            raise FileNotFoundError(f"previous release {previous} is not intact")
        _set_active(base, previous)
        return previous
