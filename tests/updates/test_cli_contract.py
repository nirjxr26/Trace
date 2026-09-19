import json

from typer.testing import CliRunner

from trace_core.cli.main import app


def _manifest_json(manifest_path):
    import json as _json

    data = _json.loads(manifest_path.read_text(encoding="utf-8"))
    return data


def test_check_json_stable_across_cache(signed_release, temp_storage_root):
    _, manifest_path, _, _ = signed_release()
    runner = CliRunner()
    first = runner.invoke(app, ["update", "check", "--manifest", str(manifest_path), "--output", "json"])
    assert first.exit_code == 0
    second = runner.invoke(app, ["update", "check", "--manifest", str(manifest_path), "--output", "json"])
    assert second.exit_code == 0
    assert json.loads(second.output) == json.loads(first.output)
    payload = json.loads(first.output)
    assert payload["available"] is True
    assert payload["target"] == "1.5.0"
    assert payload["installable"] is True


def test_verify_failure_exit_code(signed_release):
    _, manifest_path, art_path, _ = signed_release()
    art_path.write_bytes(b"tampered")
    res = CliRunner().invoke(app, ["update", "verify", "--manifest", str(manifest_path), "--artifact", str(art_path)])
    assert res.exit_code == 11


def test_policy_deferred_exit_zero(signed_release):
    manifest, manifest_path, _, _ = signed_release(minimum_supported_version="9.9.9")
    res = CliRunner().invoke(app, ["update", "check", "--manifest", str(manifest_path)])
    assert res.exit_code == 0
    assert "deferred" in res.output.lower()


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
