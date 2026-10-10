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
POLICY = REPO_ROOT / "release" / "release_policy.json"


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
    # `--policy` is contained against the directory holding this script, so run a copy
    # beside tmp_path. That makes the release directory a scratch dir no test has to write
    # into the repository to reach.
    script = tmp_path / "make_manifest.py"
    script.write_bytes(SCRIPT.read_bytes())
    (tmp_path / POLICY.name).write_bytes(POLICY.read_bytes())
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    env.pop("TRACE_MANIFEST_MIN_VERSION", None)
    env.pop("TRACE_MANIFEST_NOTES", None)
    if extra_env:
        env.update(extra_env)
    # A release must state its floor, so the default is a valid one. `[]` means "no floor
    # supplied at all", which must be refused.
    args = extra_args if extra_args is not None else ["--min-version", "0.2.3", "--notes", "migration notes"]
    cmd = [sys.executable, str(script), "v9.9.9", "stable", "r9", "out.json"] + args
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


def test_the_floor_comes_from_version_control_not_dispatch_inputs(tmp_path: Path) -> None:
    """The floor was a workflow_dispatch input, which is empty on a tag push — the normal
    release path. A tag push must therefore publish, using release/release_policy.json."""
    policy = json.loads((REPO_ROOT / "release" / "release_policy.json").read_text(encoding="utf-8"))
    assert policy["minimum_supported_version"], "the committed floor must be stated"
    assert policy["notes"], "the committed migration notes must be stated"

    proc = _run_manifest(tmp_path, {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"}, extra_args=[])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = _read_manifest(tmp_path)
    assert manifest["minimum_supported_version"] == policy["minimum_supported_version"]
    assert manifest["notes"] == policy["notes"]


def test_an_explicit_flag_overrides_the_committed_policy(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--min-version", "0.9.9", "--notes", "one-off notes"],
    )
    assert proc.returncode == 0, proc.stderr
    manifest = _read_manifest(tmp_path)
    assert manifest["minimum_supported_version"] == "0.9.9"
    assert manifest["notes"] == "one-off notes"


def test_the_workflow_does_not_require_dispatch_inputs_for_a_tag_push() -> None:
    """`inputs.min_version` is empty on `push`, so requiring it blocked every release."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "MANIFEST_MIN_VERSION:?" not in workflow, "a tag push must not be blocked on a dispatch-only input"
    assert "release_policy.json" in workflow or "make_manifest.py" in workflow


def test_a_missing_policy_file_is_refused(tmp_path: Path) -> None:
    """A release must state its floor. The policy file is now that source, so an unreadable
    or absent one stops the build rather than shipping a manifest with no floor."""
    broken = tmp_path / "broken_policy.json"
    broken.write_text("{not json", encoding="utf-8")
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--policy", str(broken)],
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "cannot read release policy" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    assert not (tmp_path / "out.json").exists(), "no manifest may be written without a floor"


def test_a_policy_without_a_floor_is_refused(tmp_path: Path) -> None:
    partial = tmp_path / "partial_policy.json"
    partial.write_text(json.dumps({"notes": "notes only"}), encoding="utf-8")
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--policy", str(partial)],
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "min-version" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


def test_an_absent_policy_file_is_refused(tmp_path: Path) -> None:
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--policy", str(tmp_path / "absent.json")],
    )
    assert proc.returncode != 0
    assert "cannot read release policy" in (proc.stdout + proc.stderr)


def test_a_policy_outside_the_release_directory_is_refused(tmp_path: Path) -> None:
    """`--policy` is signed into the published manifest, so a path outside the release
    directory would inject arbitrary text into a signed artifact. `out` is already
    contained against the same root; the policy path was not."""
    outside = tmp_path.parent / "outside_policy.json"
    outside.write_text(json.dumps({"minimum_supported_version": "9.9.9", "notes": "injected"}), encoding="utf-8")
    try:
        proc = _run_manifest(
            tmp_path,
            {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
            extra_args=["--policy", str(outside)],
        )
    finally:
        outside.unlink()
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "refusing release policy outside the release directory" in (proc.stdout + proc.stderr), (
        proc.stdout + proc.stderr
    )
    assert not (tmp_path / "out.json").exists(), (
        "no manifest may be written from a policy outside the release directory"
    )


def test_a_traversing_policy_path_is_refused(tmp_path: Path) -> None:
    """`..` must not be a way around the containment check."""
    proc = _run_manifest(
        tmp_path,
        {"trace-9.9.9-py3-none-any.whl": b"wheel-bytes"},
        extra_args=["--policy", "../release_policy.json"],
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "refusing release policy outside the release directory" in (proc.stdout + proc.stderr), (
        proc.stdout + proc.stderr
    )


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
