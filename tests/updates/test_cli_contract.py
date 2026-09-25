import json

from typer.testing import CliRunner

from trace_core.cli.main import app


def _manifest_json(manifest_path):
    import json as _json

    data = _json.loads(manifest_path.read_text(encoding="utf-8"))
    return data


def test_check_json_stable_across_cache(signed_release, temp_storage_root, monkeypatch):
    from trace_core.core.settings import settings

    _, manifest_path, _, _ = signed_release()
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    runner = CliRunner()
    first = runner.invoke(app, ["update", "check", "--output", "json"])
    assert first.exit_code == 0
    second = runner.invoke(app, ["update", "check", "--output", "json"])
    assert second.exit_code == 0
    assert json.loads(second.output) == json.loads(first.output)
    payload = json.loads(first.output)
    assert payload["available"] is True
    assert payload["target"] == "1.5.0"
    assert payload["installable"] is True


def test_policy_deferred_exit_zero(signed_release, temp_storage_root, monkeypatch):
    from trace_core.core.settings import settings

    _, manifest_path, _, _ = signed_release(minimum_supported_version="9.9.9", notes="reinstall required")
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    res = CliRunner().invoke(app, ["update", "check"])
    assert res.exit_code == 0
    assert "deferred" in res.output.lower()
    assert "reinstall required" in res.output


def test_history_json_shape(session_manager, temp_storage_root, monkeypatch):
    from trace_core.updates.dto import UpdateHistoryCreateDto
    from trace_core.updates.service import UpdateService

    monkeypatch.setattr("trace_core.updates.commands.UpdateService", lambda: UpdateService(session_manager))
    svc = UpdateService(session_manager)
    svc.record_history(UpdateHistoryCreateDto(from_version="0.1.0", to_version="1.5.0"))
    res = CliRunner().invoke(app, ["update", "history", "--output", "json"])
    assert res.exit_code == 0
    rows = json.loads(res.output)
    assert rows
    assert rows[0]["from_version"] == "0.1.0"


def test_unrelated_json_uncontaminated():
    res = CliRunner().invoke(app, ["case", "list", "--output", "json"])
    assert res.exit_code == 0
    assert "block_reason" not in res.stdout
    assert "installable" not in res.stdout
