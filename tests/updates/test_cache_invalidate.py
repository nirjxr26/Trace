import json

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app

pytestmark = pytest.mark.unit


def test_cache_invalidates_on_content_change(signed_release, temp_storage_root, monkeypatch):
    from trace_core.core.settings import settings

    _, manifest_path, _, _ = signed_release(version="1.5.0")
    _, manifest_path_2, _, _ = signed_release(version="1.6.0")
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    runner = CliRunner()
    first = runner.invoke(app, ["update", "check", "--output", "json"])
    assert first.exit_code == 0
    assert json.loads(first.stdout)["target"] == "1.5.0"
    manifest_path.write_bytes(manifest_path_2.read_bytes())
    second = runner.invoke(app, ["update", "check", "--output", "json"])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["target"] == "1.6.0"


def test_stale_cache_not_served_for_changed_file(signed_release, temp_storage_root, monkeypatch):
    from trace_core.core.settings import settings
    from trace_core.updates import cache as check_cache

    _, manifest_path, _, _ = signed_release(version="1.5.0")
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    runner = CliRunner()
    runner.invoke(app, ["update", "check", "--output", "json"])
    raw = manifest_path.read_bytes()
    manifest_path.write_bytes(raw + b" ")
    cached = check_cache.read_check_cache()
    assert cached is None or not check_cache.cache_valid_for(cached, str(manifest_path), "stable")
