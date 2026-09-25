from http.server import BaseHTTPRequestHandler

from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.updates.domain import UpdateState
from trace_core.updates.dto import UpdateHistoryCreateDto
from trace_core.updates.stages import (
    STAGE_ORDER,
    Stage,
    StageStatus,
    format_mb,
    format_speed,
    stage_from_state,
)


def _payload(**over):
    base = {
        "current": "0.2.3",
        "available": True,
        "target": "0.2.4",
        "installable": True,
        "block_reason": None,
        "security_update": False,
        "minimum_supported_version": None,
        "restart_required": True,
        "notes": None,
    }
    base.update(over)
    return base


def test_stage_mapping_covers_all_states():
    assert stage_from_state(UpdateState.DOWNLOADING) == Stage.DOWNLOAD
    assert stage_from_state(UpdateState.STAGED) == Stage.VERIFY
    assert stage_from_state(UpdateState.INSTALLING) == Stage.INSTALL
    assert stage_from_state(UpdateState.MIGRATING) == Stage.INSTALL
    assert stage_from_state(UpdateState.HEALTH_CHECK) == Stage.HEALTH
    assert stage_from_state(UpdateState.ROLLING_BACK) == Stage.INSTALL
    assert stage_from_state(UpdateState.ROLLED_BACK) == Stage.INSTALL
    assert stage_from_state(UpdateState.RECOVERY_REQUIRED) == Stage.INSTALL
    for state in (
        UpdateState.IDLE,
        UpdateState.CHECKING,
        UpdateState.AVAILABLE,
        UpdateState.AVAILABLE_BUT_DEFERRED,
        UpdateState.AVAILABLE_BUT_POLICY_BLOCKED,
        UpdateState.READY_TO_INSTALL,
        UpdateState.COMPLETED,
        UpdateState.FAILED,
    ):
        assert stage_from_state(state) is None
    assert tuple(STAGE_ORDER) == (Stage.DOWNLOAD, Stage.VERIFY, Stage.INSTALL, Stage.HEALTH)


def test_format_speed_guards():
    assert format_mb(20132659) == "19.2 MB"
    assert format_speed(0, 100, 5.0) == ("--", "--")
    assert format_speed(100, 100, 0.0) == ("--", "--")
    assert format_speed(1 << 20, 2 << 20, 2.0) == ("0.5 MB/s", "2s")
    assert format_speed(1 << 20, 121 << 20, 2.0) == ("0.5 MB/s", "4m 0s")
    assert format_speed(100, 100, 2.0)[1] == "0s"


def test_on_bytes_reports_cumulative(serve, tmp_path):
    from trace_core.updates.sources import stream_artifact_to_file

    body = b"x" * (3 << 20)

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    base = serve(_H)
    dest = tmp_path / "out.bin"
    seen = []
    stream_artifact_to_file(base, "pkg.bin", dest, len(body) + 1, timeout=10.0, on_bytes=seen.append)
    assert dest.read_bytes() == body
    assert seen and seen[-1] == len(body)
    assert all(b >= a for a, b in zip(seen, seen[1:]))


def test_check_card_available(capsys):
    from trace_core.updates.renderers import render_check_card

    render_check_card(_payload(), "stable")
    out = capsys.readouterr().out
    assert "Update 0.2.4 available" in out
    assert "ed25519" not in out
    assert "sha256" not in out.lower()


def test_check_card_deferred_notes(capsys):
    from trace_core.updates.renderers import render_check_blocked, render_check_card

    payload = _payload(installable=False, block_reason="minimum supported version 0.2.3 not met", notes="do the thing")
    render_check_card(payload, "stable")
    out = capsys.readouterr().out
    assert "deferred" in out
    assert "do the thing" in out
    render_check_blocked(payload)
    assert "do the thing" in capsys.readouterr().out


def test_check_card_up_to_date(capsys):
    from trace_core.updates.renderers import render_check_card

    render_check_card(_payload(available=False, target=None), "stable")
    assert "Up to date" in capsys.readouterr().out


def test_install_summary_hides_trust_details(capsys, signed_release):
    from trace_core.updates.renderers import render_install_summary

    manifest, _, _, _ = signed_release()
    render_install_summary(manifest, "0.2.3", "")
    out = capsys.readouterr().out
    assert "Product: trace" in out
    assert "Current: v0.2.3" in out
    assert "Signature: Verified" in out
    assert "TRUSTED" not in out
    assert "sha256" not in out.lower()
    assert manifest.signing_key_id not in out


def test_finish_success_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateHistoryCreateDto(from_version="0.2.3", to_version="0.2.4", result="SUCCESS")
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "Trace updated successfully." in out
    assert "v0.2.3 → v0.2.4" in out


def test_finish_rolled_back_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateHistoryCreateDto(from_version="0.2.3", to_version="0.2.4", result="ROLLED_BACK", rollback=True)
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "rolled back" in out
    assert "Current version: v0.2.3" in out


def test_finish_failed_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateHistoryCreateDto(
        from_version="0.2.3",
        to_version="0.2.4",
        result="FAILED",
        failure_reason="staged artifact failed re-verification",
    )
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "Update failed" in out
    assert "staged artifact failed re-verification" in out
    assert "trace update history" in out


def test_frame_checklist_states():
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.on_stage(Stage.DOWNLOAD, StageStatus.DONE)
    display.on_stage(Stage.VERIFY, StageStatus.ACTIVE)
    frame = display._frame()
    text = frame.plain
    assert "✓ Downloaded" in text
    assert "◌ Verifying" in text
    assert "Installing" not in text


def test_check_cli_variants(signed_release, temp_storage_root, monkeypatch):
    from trace_core.core.settings import settings

    _, manifest_path, _, _ = signed_release(version="1.5.0")
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    res = CliRunner().invoke(app, ["update", "check"])
    assert res.exit_code == 0
    assert "Update 1.5.0 available" in res.output
    _, old_path, _, _ = signed_release(version="0.1.0")
    monkeypatch.setattr(settings, "update_manifest", str(old_path))
    res = CliRunner().invoke(app, ["update", "check"])
    assert res.exit_code == 0
    assert "Up to date" in res.output


def test_shell_help_lists_three_update_actions(capsys):
    from trace_core.cli.shell import InteractiveShell

    shell = InteractiveShell()
    shell.execute_line("help")
    out = capsys.readouterr().out
    assert "update check" in out
    assert "update verify" not in out
    assert "update show" not in out
