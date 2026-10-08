"""Tribunal tests for the shared helpers introduced by the reusability pass."""

import importlib
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trace_core.audit import helpers as audit_helpers
from trace_core.audit import signing as audit_signing
from trace_core.audit import verifier as audit_verifier
from trace_core.cases import domain as cases_domain
from trace_core.cases import service as cases_service
from trace_core.core.domain import InvariantViolationError
from trace_core.tui import widgets as tui_widgets
from trace_core.tui.screens import audit as audit_screen
from trace_core.tui.screens import cases as cases_screen
from trace_core.updates import cache as update_cache
from trace_core.updates import checker as update_checker
from trace_core.updates import manifest as update_manifest
from trace_core.updates import renderers as update_renderers
from trace_core.updates import signing as update_signing
from trace_core.updates import stages as update_stages
from trace_core.updates.stages import Stage, StageStatus

audit_shell = importlib.import_module("trace_core.audit.shell_handler")
audit_commands = importlib.import_module("trace_core.audit.commands")

pytestmark = pytest.mark.unit


def _manifest() -> Any:  # type: ignore[no-untyped-def]
    return update_manifest.ReleaseManifest.model_validate(
        {
            "schema": 1,
            "product": "Trace",
            "channel": "stable",
            "version": "0.2.9",
            "release_id": "rel-1",
            "security_update": False,
            "restart_required": False,
            "manifest_signature": "aa",
            "signing_key_id": "ed25519:" + "0" * 16,
            "artifacts": {},
        }
    )


def _source(module) -> str:  # type: ignore[no-untyped-def]
    return inspect.getsource(module)


def test_update_lifecycle_has_one_history_recorder() -> None:
    from trace_core.updates import lifecycle as lifecycle_mod

    src = _source(lifecycle_mod)
    assert src.count("UpdateResultDto(") == 1, "only _record may build the DTO; run()/_run_locked must delegate"
    assert src.count("self._record(") == 8, "7 call sites plus the definition"


def test_update_lifecycle_record_fills_the_invariant_fields() -> None:
    from trace_core.updates.lifecycle import UpdateLifecycle

    lifecycle = UpdateLifecycle("tx-1")
    manifest = _manifest()
    started = datetime(2026, 1, 1, tzinfo=UTC)
    dto = lifecycle._record("0.2.8", manifest, "stable", started, result="SUCCESS")
    assert dto.transaction_id == "tx-1"
    assert dto.release_id == "rel-1"
    assert dto.from_version == "0.2.8"
    assert dto.to_version == "0.2.9"
    assert dto.started_at == started


def test_case_service_audit_hooks_are_built_by_one_factory() -> None:
    src = _source(cases_service)
    assert src.count("_audit_hook(") == 6, "5 builder sites plus the factory definition"
    assert src.count("def _audit_hook(") == 1
    built: tuple[Any, Any, dict[str, Any], Any] = ("ACTION", object(), {}, object())
    hook = cases_service._audit_hook(lambda: built, "actor", claimed="claimed")
    assert callable(hook)


def test_case_service_close_hook_still_pins_the_ledger_position() -> None:
    src = _source(cases_service)
    assert "close audit hook produced no ledger position" in src
    assert "record_anchor_intent" in src


@pytest.mark.parametrize("view", [cases_screen.CasesView, audit_screen.AuditView])
def test_both_table_views_inherit_one_pane_base(view: type) -> None:  # type: ignore[type-arg]
    assert issubclass(view, tui_widgets.TablePane)
    for attr in ("TABLE_ID", "HEADER_ID", "DETAIL_ID", "SEARCH_ID"):
        assert getattr(view, attr), f"{view.__name__} must declare {attr}"
    assert view.COLUMNS


@pytest.mark.parametrize("view", [cases_screen.CasesView, audit_screen.AuditView])
def test_neither_view_redefines_the_shared_pane_behaviour(view: type) -> None:  # type: ignore[type-arg]
    own = vars(view)
    for shared in ("on_mount", "focus_default", "_repaint_selection", "_selected", "action_search", "_searched"):
        assert shared not in own, f"{view.__name__} redefines {shared}; it must come from TablePane once"


def test_table_pane_leaves_the_two_hooks_to_subclasses() -> None:
    for hook in ("row_cells", "render_detail", "refresh_data"):
        assert getattr(tui_widgets.TablePane, hook).__qualname__.startswith("TablePane.")


def test_update_cache_path_is_the_shared_state_layout() -> None:
    from trace_core.updates.marker import storage_state_path

    assert update_cache.cache_path() == storage_state_path("update-check.json")
    assert update_cache.cache_path().parent.name == "state"


def test_check_payload_is_shared_by_both_check_paths() -> None:
    src = _source(update_checker)
    assert src.count('"minimum_supported_version": ') == 1
    assert "_check_payload(" in src
    manifest = _manifest()
    payload = update_checker._check_payload("0.2.8", manifest, available=True, installable=False, block_reason="held")
    assert payload["target"] is manifest.version
    assert payload["installable"] is False
    assert payload["block_reason"] == "held"
    blocked = update_checker._check_payload(
        "0.2.8", manifest, available=False, installable=True, block_reason="ignored"
    )
    assert blocked["target"] is None
    assert blocked["installable"] is False
    assert blocked["block_reason"] is None


def test_signature_verification_has_one_guarded_body() -> None:
    src = _source(update_signing)
    assert src.count("Ed25519PublicKey.from_public_bytes(raw_pub).verify") == 1
    assert "missing {subject} signing key" in src


@pytest.mark.parametrize("subject", ["manifest", "artifact"])
def test_signature_guard_messages_name_the_subject(subject: str) -> None:
    from trace_core.updates.errors import UpdateVerificationError

    with pytest.raises(UpdateVerificationError, match=f"missing {subject} signing key"):
        update_signing._verify_signature(None, "aa", b"data", subject)
    with pytest.raises(UpdateVerificationError, match=f"missing {subject} signature"):
        update_signing._verify_signature(f"ed25519:{'0' * 16}", None, b"data", subject)


def test_stage_label_is_one_map_shared_by_every_surface():
    for stage in Stage:
        assert update_stages.stage_label(stage) == update_stages.STAGE_LABEL[stage]
    # The map used to exist three times over (active/done/failed) with identical contents.
    assert not [name for name in dir(update_stages) if name.endswith("_LABEL") and name != "STAGE_LABEL"], (
        "a status-specific label map came back; the label must not vary with status"
    )


def test_stage_line_consumers_read_the_shared_map():
    assert "stage_label" in _source(update_renderers)
    from trace_core.tui.screens import settings as settings_screen

    settings_src = _source(settings_screen)
    assert "STAGE_DONE_LABEL" not in settings_src
    assert "stage_label(stage)" in settings_src
    assert "STAGE_ORDER" in settings_src


def test_step_line_renders_a_glyph_for_every_status():
    """A status must render as its glyph, never as the enum's own name.

    step_line used to take a glyph and reverse-map it to a status, so callers that passed
    the status rendered the words pending/active/done/failed where a glyph belonged.
    """
    from rich.console import Console

    from trace_core.core.ui.renderers import step_line

    console = Console(force_terminal=False, width=40)
    for status in StageStatus:
        rendered = step_line(status, "Label").plain
        assert rendered == f"│ {update_stages.stage_glyph(status)} Label"
        assert str(status) not in rendered
        assert console is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("  Laptop SSD  ", "Laptop SSD"), ("with\x00control", "withcontrol")],
)
def test_required_text_normalises_like_the_case_fields(value: str, expected: str) -> None:
    assert cases_domain._required_text(value, "empty") == expected


def test_required_text_rejects_an_empty_result() -> None:
    with pytest.raises(InvariantViolationError, match="empty"):
        cases_domain._required_text("   \x00 ", "empty")


def test_case_entity_fields_use_the_shared_required_text_rule() -> None:
    from pydantic import ValidationError

    from trace_core.cases.domain import Case

    with pytest.raises(ValidationError, match="Case title cannot be empty."):
        Case(number="2026-CR-0001", title="   ", lead_examiner="Ex")
    with pytest.raises(ValidationError, match="Lead examiner cannot be empty."):
        Case(number="2026-CR-0001", title="T", lead_examiner="  \x07 ")


def test_report_written_is_the_only_export_tail() -> None:
    assert callable(audit_helpers.report_written)
    assert audit_commands.__name__.endswith("commands")
    for module in (audit_commands, audit_shell):
        src = _source(module)
        assert "report_written(path," in src
        assert 'console.print(f"[dim]{path}[/dim]")' not in src


def test_audit_signing_still_fails_closed_on_unknown_keys() -> None:
    assert audit_signing.verify_bytes("ed25519:deadbeefdeadbeef", b"data", "ff") is False
    assert audit_verifier.verify_event("{}", "0" * 64, "0" * 64, "0" * 64, 1) is False


def test_cache_path_stays_under_storage(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "storage_root", tmp_path, raising=False)
    assert str(update_cache.cache_path()).startswith(str(tmp_path))


def _fake_tty(monkeypatch: Any, stdin: bool, stdout: bool) -> None:  # type: ignore[no-untyped-def]
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout, raising=False)


def test_interactive_terminal_needs_both_streams(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core.cli.args import interactive_terminal

    _fake_tty(monkeypatch, True, True)
    assert interactive_terminal() is True
    _fake_tty(monkeypatch, True, False)
    assert interactive_terminal() is False
    _fake_tty(monkeypatch, False, True)
    assert interactive_terminal() is False
    _fake_tty(monkeypatch, False, False)
    assert interactive_terminal() is False


def test_every_interactive_guard_goes_through_the_shared_helper() -> None:
    """No surface may keep a private isatty check; the three had drifted apart."""
    import sys

    from trace_core.core.cli import uninstall
    from trace_core.updates import commands as update_commands

    for module in (audit_helpers, uninstall, update_commands):
        assert "isatty" not in _source(module), module.__name__
    assert sys.modules["trace_core.core.cli.args"].interactive_terminal is not None
    assert audit_helpers._is_interactive() is not None


def test_uninstall_refuses_an_interactive_prompt_without_yes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Only the refusal path is exercised: the affirmative path runs the uninstaller."""
    from typer.testing import CliRunner

    from trace_core.cli.main import app
    from trace_core.core.cli import uninstall

    monkeypatch.setattr(uninstall, "interactive_terminal", lambda: False)
    res = CliRunner().invoke(app, ["uninstall"])
    assert res.exit_code != 0
    assert "--yes" in res.output


def test_uninstall_prompts_only_when_both_streams_are_terminals(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With a terminal available it reaches the confirm, and declining never uninstalls."""
    from typer.testing import CliRunner

    from trace_core.cli.main import app
    from trace_core.core.cli import uninstall

    def _must_not_run(purge: bool) -> int:
        raise AssertionError("uninstaller ran after a declined confirmation")

    monkeypatch.setattr(uninstall, "interactive_terminal", lambda: True)
    monkeypatch.setattr(uninstall, "run_uninstall", _must_not_run)
    res = CliRunner().invoke(app, ["uninstall"], input="n\n")
    assert res.exit_code == 0
