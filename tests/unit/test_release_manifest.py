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

from trace_core.core.database.migrations import MIGRATIONS

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "release" / "make_manifest.py"


def _run_manifest(
    tmp_path: Path,
    dist_files: dict[str, bytes],
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, data in dist_files.items():
        (dist / name).write_bytes(data)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    env.pop("TRACE_MANIFEST_MIN_VERSION", None)
    env.pop("TRACE_MANIFEST_NOTES", None)
    if extra_env:
        env.update(extra_env)
    # A release must state its floor, so the default is a valid one. `[]` means "no floor
    # supplied at all", which must be refused.
    args = extra_args if extra_args is not None else ["--min-version", "0.2.3", "--notes", "migration notes"]
    cmd = [sys.executable, str(SCRIPT), "v9.9.9", "stable", "r9", "out.json"] + args
    return subprocess.run(
        cmd,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_manifest(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))


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
    manifest = _read_manifest(tmp_path)
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


def test_a_release_without_a_floor_is_refused(tmp_path: Path) -> None:
    """The workflow's "fail closed" step could never fire: two shell fallbacks above it
    guaranteed both values were non-empty, so every tag push published floor 0.2.5 whatever
    the real minimum was. The refusal now lives where the value is produced."""
    proc = _run_manifest(tmp_path, {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"}, extra_args=[])
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "min-version" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    assert not (tmp_path / "out.json").exists(), "no manifest may be written without a floor"


def test_a_release_with_notes_but_no_floor_is_still_refused(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--notes", "migration notes"],
    )
    assert proc.returncode != 0
    assert "min-version" in (proc.stdout + proc.stderr)


def test_the_workflow_has_no_fallback_that_defeats_its_own_assertion() -> None:
    """`MIN_VER="${VAR:-0.2.5}"` is what made the floor assertion unfailable."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "MANIFEST_MIN_VERSION:-" not in workflow, "a shell fallback defeats the floor assertion"
    assert "MANIFEST_NOTES:-" not in workflow, "a shell fallback defeats the notes assertion"
    assert ":-0.2.5" not in workflow, "the floor must not be hardcoded in the workflow"


def test_manifest_includes_min_version_and_notes_via_flags(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--min-version", "0.2.3", "--notes", "migration notes"],
    )
    assert proc.returncode == 0, proc.stderr
    manifest = _read_manifest(tmp_path)
    assert manifest["minimum_supported_version"] == "0.2.3"
    assert manifest["notes"] == "migration notes"


def test_manifest_includes_min_version_and_notes_via_env(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=[],
        extra_env={"TRACE_MANIFEST_MIN_VERSION": "0.2.3", "TRACE_MANIFEST_NOTES": "env notes"},
    )
    assert proc.returncode == 0, proc.stderr
    manifest = _read_manifest(tmp_path)
    assert manifest["minimum_supported_version"] == "0.2.3"
    assert manifest["notes"] == "env notes"


def test_manifest_declares_the_schema_range_it_migrates_to(tmp_path: Path) -> None:
    proc = _run_manifest(tmp_path, {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"})
    assert proc.returncode == 0, proc.stderr
    manifest = _read_manifest(tmp_path)
    assert manifest["schema_target"] == MIGRATIONS[-1][0]
    assert manifest["schema_min"] == 1


def test_manifest_rejects_dangling_flag(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--min-version"],
    )
    assert proc.returncode != 0
