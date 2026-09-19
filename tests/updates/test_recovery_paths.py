from typer.testing import CliRunner

from trace_core.cli.main import app


def test_recovery_no_marker_reports_state(temp_storage_root):
    res = CliRunner().invoke(app, ["recovery"])
    assert res.exit_code == 0
    assert "No update marker found" in res.output or "No recovery needed" in res.output


def test_recovery_missing_previous_fails(temp_storage_root, session_manager):
    from trace_core.updates.service import UpdateService

    svc = UpdateService(session_manager)
    svc.write_result_marker(
        {
            "transaction_id": "tx-rec-1",
            "state": "FAILED",
            "from_version": "0.1.0",
            "to_version": "1.5.0",
            "result": "FAILED",
        }
    )
    res = CliRunner().invoke(app, ["recovery"])
    assert res.exit_code == 15


def test_recovery_restores_previous(temp_storage_root, session_manager, tmp_path, monkeypatch):
    import shutil

    from trace_core.core.settings import settings
    from trace_core.updates.service import UpdateService
    from trace_updater import updater as updater_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    base = tmp_path / "install"
    for version, payload in (("0.1.0", b"good"), ("0.2.0", b"bad")):
        seed = tmp_path / f"seed-{version}"
        seed.mkdir()
        (seed / "trace.bin").write_bytes(payload)
        updater_mod.stage_release(
            seed,
            base,
            version,
            expected=["trace.bin"],
            release_meta={"version": version, "schema_min": 0, "schema_target": 99},
        )
        updater_mod.activate(base, version)
    svc = UpdateService(session_manager)
    svc.write_result_marker(
        {
            "transaction_id": "tx-rec-2",
            "state": "FAILED",
            "from_version": "0.1.0",
            "to_version": "1.5.0",
            "result": "FAILED",
        }
    )
    res = CliRunner().invoke(app, ["recovery"])
    assert res.exit_code == 0
    assert updater_mod.read_active(base) == "0.1.0"
    shutil.rmtree(base, ignore_errors=True)
