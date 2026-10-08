from http.server import BaseHTTPRequestHandler

from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.updates.domain import UpdateState
from trace_core.updates.dto import UpdateResultDto
from trace_core.updates.stages import (
    SPIN_DELAY_SECONDS,
    SPIN_FRAMES,
    STAGE_ORDER,
    Stage,
    StageStatus,
    format_mb,
    format_speed,
    stage_from_state,
    stage_is_spinning,
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
    assert tuple(STAGE_ORDER) == (Stage.VERIFY, Stage.DOWNLOAD, Stage.INSTALL, Stage.HEALTH)


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
    assert seen
    assert seen[-1] == len(body)
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
    out = capsys.readouterr().out
    assert "up to date" in out
    assert "0.2.3" in out


def test_install_summary_hides_trust_details(capsys, signed_release):
    from trace_core.updates.renderers import render_install_summary

    manifest, _, _, _ = signed_release()
    render_install_summary(manifest, "0.2.3", "")
    out = capsys.readouterr().out
    assert "Product: trace" in out
    assert "Current: v0.2.3" in out
    assert "Signature" not in out
    assert "TRUSTED" not in out
    assert "sha256" not in out.lower()
    assert manifest.signing_key_id not in out
    # The target version and the step list are the live region's job; stating either here
    # too put both on screen three times over.
    assert f"Target:  v{manifest.version}" not in out
    assert "Steps: download" not in out


def test_finish_success_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateResultDto(from_version="0.2.3", to_version="0.2.4", result="SUCCESS")
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    # The target version rides on the closing line; it used to be a second line of its
    # own, so the success path stated the outcome twice.
    assert "Trace updated to v0.2.4" in out
    assert "Trace updated successfully." not in out
    assert out.count("Verifying") == 1
    assert "  ✓ Trace updated to v0.2.4" in out
    assert "  Run `trace case list` to resume work." in out


def test_finish_rolled_back_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateResultDto(from_version="0.2.3", to_version="0.2.4", result="ROLLED_BACK", rollback=True)
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "rolled back" in out
    assert "Current version: v0.2.3" in out


def test_finish_failed_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateResultDto(
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
    display.on_stage(Stage.VERIFY, StageStatus.DONE)
    display.on_stage(Stage.DOWNLOAD, StageStatus.ACTIVE)
    frame = display._frame()
    lines = frame.plain.splitlines()
    assert lines == [
        "│ ● Verifying",
        f"│ {SPIN_FRAMES[0]} Downloading",
        "│ ▲ Installing",
        "│ ▲ Finishing setup",
    ]


def test_frame_is_pure_and_draw_owns_the_spinner():
    """Building a frame must not change it. The spinner advances in _draw, once per
    drawn frame, never as a side effect of rendering.

    It used to advance inside the row loop, so rendering the same state twice returned
    two different glyphs and calling _frame() twice desynced the animation from the screen.
    """
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.on_stage(Stage.DOWNLOAD, StageStatus.ACTIVE)
    assert display._frame().plain == display._frame().plain

    display.tty = True
    before = display._spin
    display._frame()
    assert display._spin == before


def test_spinner_waits_until_the_step_has_been_running():
    """A step that finishes immediately must never show a frame of motion.

    Animating from the first frame meant a step completing in a few tens of milliseconds
    flashed a spinner for a single frame, which reads as a glitch rather than as progress.
    """
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.on_stage(Stage.DOWNLOAD, StageStatus.ACTIVE)
    display.tty = True

    class _Sink:
        def update(self, _frame):  # noqa: ANN001, ANN202
            return None

    display._live = _Sink()
    for _ in range(4):
        display._draw(force=True)
    assert display._spin == 0
    assert display._frame().plain.splitlines()[1] == f"│ {SPIN_FRAMES[0]} Downloading"

    display._active_since -= SPIN_DELAY_SECONDS + 0.01
    display._draw(force=True)
    assert display._spin == 1
    assert display._frame().plain.splitlines()[1] == f"│ {SPIN_FRAMES[1]} Downloading"


def test_stage_is_spinning_bounds():
    assert stage_is_spinning(None, 100.0) is False
    assert stage_is_spinning(100.0, 100.0 + SPIN_DELAY_SECONDS / 2) is False
    assert stage_is_spinning(100.0, 100.0 + SPIN_DELAY_SECONDS) is True


def test_failed_and_pending_have_different_glyphs():
    """A failure must be distinguishable from a step that has not started."""
    from trace_core.updates.stages import stage_glyph

    assert stage_glyph(StageStatus.FAILED) != stage_glyph(StageStatus.PENDING)
    assert stage_glyph(StageStatus.FAILED) == "✕"


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
    assert "up to date" in res.output


def test_shell_help_lists_three_update_actions(capsys):
    from trace_core.cli.shell import InteractiveShell

    shell = InteractiveShell()
    shell.execute_line("help")
    out = capsys.readouterr().out
    assert "update check" in out
    assert "update verify" not in out
    assert "update show" not in out
