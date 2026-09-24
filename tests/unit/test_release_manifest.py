"""Release tooling contract: manifests ship exactly one installable wheel.

Ambiguous multi-artifact manifests are refused at build time, never on user
machines (see stable.json v0.2.2 serving wheel+sdist untagged).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "release" / "make_manifest.py"


def _run_manifest(tmp_path: Path, dist_files: dict[str, bytes]) -> subprocess.CompletedProcess[str]:
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, data in dist_files.items():
        (dist / name).write_bytes(data)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "v9.9.9", "stable", "r9", "out.json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_manifest_lists_only_the_wheel(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {
            "trace-9.9.9-py3-none-any.whl": b"wheel-bytes",
            "trace-9.9.9.tar.gz": b"sdist-bytes",
            "sbom.json": b"{}",
            "SHA256SUMS": b"sums",
        },
    )
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert list(manifest["artifacts"]) == ["trace-9.9.9-py3-none-any.whl"]
    assert manifest["version"] == "9.9.9"


def test_manifest_refuses_zero_wheels(tmp_path: Path) -> None:
    proc = _run_manifest(tmp_path, {"trace-9.9.9.tar.gz": b"sdist-bytes"})
    assert proc.returncode != 0


def test_manifest_refuses_two_wheels(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"a-9.9.9-py3-none-any.whl": b"a", "b-9.9.9-py3-none-any.whl": b"b"},
    )
    assert proc.returncode != 0
