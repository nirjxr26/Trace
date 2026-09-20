import json

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app

pytestmark = pytest.mark.unit


def test_cache_invalidates_on_content_change(signed_release, temp_storage_root):
    _, manifest_path, _, _ = signed_release(version="1.5.0")
    _, manifest_path_2, _, _ = signed_release(version="1.6.0")
    runner = CliRunner()
    first = runner.invoke(app, ["update", "check", "--manifest", str(manifest_path), "--output", "json"])
    assert first.exit_code == 0
    assert json.loads(first.stdout)["target"] == "1.5.0"
    manifest_path.write_bytes(manifest_path_2.read_bytes())
    second = runner.invoke(app, ["update", "check", "--manifest", str(manifest_path), "--output", "json"])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["target"] == "1.6.0"


def test_stale_cache_not_served_for_changed_file(signed_release, temp_storage_root):
    from trace_core.updates import cache as check_cache

    _, manifest_path, _, _ = signed_release(version="1.5.0")
    runner = CliRunner()
    runner.invoke(app, ["update", "check", "--manifest", str(manifest_path), "--output", "json"])
    raw = manifest_path.read_bytes()
    manifest_path.write_bytes(raw + b" ")
    cached = check_cache.read_check_cache()
    assert cached is None or not check_cache.cache_valid_for(cached, str(manifest_path), "stable")
