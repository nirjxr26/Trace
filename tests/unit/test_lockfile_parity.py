import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements_pins(text: str) -> dict[str, tuple[str, set[str]]]:
    pins: dict[str, tuple[str, set[str]]] = {}
    name: str | None = None
    version = ""
    hashes: set[str] = set()

    def flush() -> None:
        if name is not None:
            pins[name] = (version, hashes)

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            hashes.add(line.split(":", 1)[1].split()[0])
            continue
        if line.startswith("-"):
            continue
        flush()
        raw_name, _, rest = line.partition("==")
        name = _canonical(raw_name)
        version = rest.split()[0]
        hashes = set()
    flush()
    return pins


def _lock_packages(path: Path) -> dict[str, dict[str, set[str]]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    packages: dict[str, dict[str, set[str]]] = {}
    for pkg in data["package"]:
        if "editable" in pkg.get("source", {}):
            continue
        hashes: set[str] = set()
        sdist = pkg.get("sdist")
        if sdist is not None:
            hashes.add(sdist["hash"].split(":", 1)[1])
        for wheel in pkg.get("wheels", []):
            hashes.add(wheel["hash"].split(":", 1)[1])
        packages.setdefault(_canonical(pkg["name"]), {})[pkg["version"]] = hashes
    return packages


def test_requirements_txt_matches_uv_lock() -> None:
    pins = _requirements_pins((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    lock = _lock_packages(ROOT / "uv.lock")

    only_in_requirements = sorted(set(pins) - set(lock))
    only_in_lock = sorted(set(lock) - set(pins))
    assert set(pins) == set(lock), (
        f"package sets differ; requirements.txt only: {only_in_requirements}; uv.lock only: {only_in_lock}"
    )

    mismatched = [(n, pins[n][0], sorted(lock[n])) for n in sorted(pins) if pins[n][0] not in lock[n]]
    assert not mismatched, f"version disagreements (name, requirements, uv.lock): {mismatched}"

    missing_hashes = [n for n in sorted(pins) if not pins[n][1] or not pins[n][1] <= lock[n][pins[n][0]]]
    assert not missing_hashes, f"pins whose hashes are absent from uv.lock: {missing_hashes}"
