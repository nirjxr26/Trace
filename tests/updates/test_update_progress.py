from http.server import BaseHTTPRequestHandler

from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.updates.domain import UpdateState
from trace_core.updates.dto import UpdateResultDto
from trace_core.updates.stages import (
    SPIN_DELAY_SECONDS,
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


def test_the_install_header_is_updating_trace_dots_with_space_around_it(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.tty = False
    display.begin_update()
    out = capsys.readouterr().out
    assert out == "\nUpdating Trace...\n\n"


def test_finish_success_frame(capsys):
    from trace_core.updates.renderers import UPDATE_INSTALLED_MESSAGE, UpdateProgressDisplay

    dto = UpdateResultDto(from_version="0.2.3", to_version="0.2.4", result="SUCCESS")
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "✓ Update installed successfully. Restart to view changes." in out
    assert "Trace updated to v0.2.4" not in out
    assert out.count("Verifying") == 0
    assert UPDATE_INSTALLED_MESSAGE == "Update installed successfully. Restart to view changes."


def test_finish_rolled_back_frame(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateResultDto(from_version="0.2.3", to_version="0.2.4", result="ROLLED_BACK", rollback=True)
    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "rolled back" in out
    # Reads the install pointer rather than echoing the pre-update capture.
    assert "Active release" in out, out
    assert "0.2.3" in out, out


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
    assert "Active release" in out, out
    assert "0.2.3" in out, out
    # `trace update history` was never built; pointing users at it was the defect.
    assert "update history" not in out


def test_the_failure_frame_names_the_release_that_is_actually_active(capsys, monkeypatch):
    """`current` is captured before the update runs. After `activate` flips the pointer,
    "Still on v<current>" names a release that is no longer running."""
    from trace_core.updates import renderers
    from trace_core.updates.renderers import UpdateProgressDisplay

    monkeypatch.setattr(renderers, "_active_version", lambda: "0.2.4")
    dto = UpdateResultDto(from_version="0.2.3", to_version="0.2.4", result="FAILED", failure_reason="verify failed")
    UpdateProgressDisplay(current="0.2.3", target="0.2.4").finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "Active release is v0.2.4" in out, out
    assert "Still on v0.2.3" not in out, out


def test_a_failed_rollback_tells_the_user_to_run_recovery(capsys):
    """`failure_stage == RECOVERY` is never produced, so the recovery hint never fired for
    the failures that most need it."""
    from trace_core.updates.renderers import UpdateProgressDisplay

    dto = UpdateResultDto(
        from_version="0.2.3",
        to_version="0.2.4",
        result="FAILED",
        failure_stage="activation",
        failure_reason="post-activation verification failed; rollback failed",
    )
    UpdateProgressDisplay(current="0.2.3", target="0.2.4").finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "Run `trace recovery` to finish putting things back." in out, out


def test_an_unreadable_pointer_does_not_claim_the_old_version_is_still_active(capsys, monkeypatch):
    from trace_core.updates import renderers
    from trace_core.updates.renderers import UpdateProgressDisplay

    monkeypatch.setattr(renderers, "_active_version", lambda: None)
    dto = UpdateResultDto(from_version="0.2.3", to_version="0.2.4", result="FAILED", failure_reason="x")
    UpdateProgressDisplay(current="0.2.3", target="0.2.4").finish(dto, "0.2.3")
    out = capsys.readouterr().out
    assert "could not be read" in out, out
    assert "Still on" not in out, out


def test_stage_state_is_tracked_independently_of_rendering():
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.on_stage(Stage.VERIFY, StageStatus.DONE)
    display.on_stage(Stage.DOWNLOAD, StageStatus.ACTIVE)
    assert display.statuses[Stage.VERIFY] is StageStatus.DONE
    assert display.statuses[Stage.DOWNLOAD] is StageStatus.ACTIVE
    assert display.statuses[Stage.INSTALL] is StageStatus.PENDING


def _tty_display():
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.tty = True
    display.begin_update()
    return display


def _rendered(display) -> str:
    """What the spinner actually paints, rather than its private fields.

    The shimmer styles each character separately, so the raw output interleaves escape
    codes between letters; they are stripped here to recover the text a user reads.
    """
    import io
    import re

    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, width=100, force_terminal=True)
    console.print(display._spinner)
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", buffer.getvalue())


def test_the_spinner_names_the_product_and_target_and_holds_still_across_stages():
    """One line for the whole run. It previously retexted itself per stage, so the
    display flickered between Downloading / Verifying / Installing."""
    display = _tty_display()
    display.on_stage(Stage.VERIFY, StageStatus.ACTIVE)
    first = _rendered(display)
    display.on_stage(Stage.INSTALL, StageStatus.ACTIVE)
    second = _rendered(display)
    assert "Installing Trace v0.2.4" in first
    assert first == second
    for label in ("Downloading", "Verifying", "Finishing setup"):
        assert label not in first, f"{label} leaked into the live line"
    display.close()


def test_the_spinner_advertises_no_hint_this_cli_cannot_honour():
    """The widget's default hint offers esc-to-cancel. Nothing in this CLI handles that
    key, so the line would promise a way out that does nothing."""
    display = _tty_display()
    painted = _rendered(display)
    assert "esc to" not in painted
    assert "esc to cancel" not in painted
    display.close()


def test_the_spinner_is_pinned_so_the_stage_cannot_drift_to_other_text():
    """message_text only seeds a rotating word list the widget cycles through on its own,
    which showed unrelated text in place of the line."""
    import time

    display = _tty_display()
    display.on_stage(Stage.DOWNLOAD, StageStatus.ACTIVE)
    time.sleep(0.2)
    painted = _rendered(display)
    assert "Installing Trace v0.2.4" in painted
    for foreign in ("Decrypting", "Compiling", "Fetching", "Analyzing"):
        assert foreign not in painted, f"line drifted to {foreign!r}"
    display.close()


def test_the_spinner_uses_theme_colours_and_not_the_widget_default():
    """The widget ships an amber highlight; this product has no amber in its palette."""
    from trace_core.updates import renderers

    assert renderers.DIM == renderers.THEME_HEX["muted"]
    assert renderers.SHIMMER_HIGHLIGHT == renderers.THEME_HEX["title"]

    display = _tty_display()
    spinner = display._spinner
    assert spinner is not None
    message = spinner.get_component("message")
    assert message.color == renderers.DIM
    assert message.shimmer_light_color == renderers.SHIMMER_HIGHLIGHT
    assert message.shimmer_light_color != "#FFA500"
    assert message.shimmer_width == renderers.SHIMMER_WIDTH
    assert message.shimmer_speed == renderers.SHIMMER_SPEED
    assert renderers.SHIMMER_SPEED >= 1.0, "the sweep was slowed down and asked to stay fast"
    assert spinner.get_component("spinner").color == renderers.DIM
    display.close()


def test_a_non_tty_console_prints_one_line_per_stage(capsys):
    from trace_core.updates.renderers import UpdateProgressDisplay

    display = UpdateProgressDisplay(current="0.2.3", target="0.2.4")
    display.tty = False
    display.begin_update()
    display.begin_download(2048)
    display.on_bytes(2048, 2048)
    display.on_stage(Stage.DOWNLOAD, StageStatus.DONE)
    display.on_stage(Stage.VERIFY, StageStatus.ACTIVE)
    out = capsys.readouterr().out
    assert "Downloading" in out
    assert "Verifying" in out


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
