"""Unit tests for interactive console shell dispatching."""

import pytest

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.shell import InteractiveShell

pytestmark = pytest.mark.unit


def test_shell_line_execution_and_aliases(service: CaseService) -> None:
    shell = InteractiveShell()
    shell.service = service

    # Prepopulate a case
    service.create_case(
        CaseCreateDto(
            number="2026-SH-0001",
            title="Shell Test Case",
            lead_examiner="Investigator Shell",
        )
    )

    # Test 'list cases' natural alias
    shell.execute_line("list cases")

    # Test 'case select' context setting
    shell.execute_line("case select 2026-SH-0001")
    assert shell.active_case is not None
    assert shell.active_case.number == "2026-SH-0001"
    assert shell.get_prompt_text() == "trace [2026-SH-0001]> "

    # Test 'show case' with active case context
    shell.execute_line("show case")

    # Test 'status' command
    shell.execute_line("status")

    # Test 'case list --output json'
    shell.execute_line("case list --output json")

    # Test 'case show 2026-SH-0001 --output json'
    shell.execute_line("case show 2026-SH-0001 --output json")

    # Test 'case deselect'
    shell.execute_line("case deselect")
    assert shell.active_case is None
    assert shell.get_prompt_text() == "trace> "


def test_shell_autocompletion_and_suggestions(service: CaseService) -> None:
    from prompt_toolkit.document import Document

    shell = InteractiveShell(service=service)
    service.create_case(
        CaseCreateDto(
            number="2026-SH-0002",
            title="Auto Suggestion Test",
            lead_examiner="Investigator Suggest",
        )
    )

    # 1. Root command completion
    doc_root = Document("c")
    completions = [c.text for c in shell.completer.get_completions(doc_root, None)]
    assert "case" in completions
    assert "clear" in completions

    # 2. Subcommand completion for "case "
    doc_sub = Document("case ")
    sub_completions = [c.text for c in shell.completer.get_completions(doc_sub, None)]
    assert "create" in sub_completions
    assert "list" in sub_completions
    assert "show" in sub_completions

    # 3. Specific prefix completion for "case l"
    doc_prefix = Document("case l")
    prefix_completions = [c.text for c in shell.completer.get_completions(doc_prefix, None)]
    assert prefix_completions == ["list"]

    # 4. Flag completion for "case list "
    doc_flags = Document("case list ")
    flag_completions = [c.text for c in shell.completer.get_completions(doc_flags, None)]
    assert "--status" in flag_completions
    assert "--search" in flag_completions

    # 5. Status enum values
    doc_status = Document("case list --status ")
    status_completions = [c.text for c in shell.completer.get_completions(doc_status, None)]
    assert "OPEN" in status_completions
    assert "CLOSED" in status_completions

    # 6. Candidate case number completion
    doc_show = Document("case show ")
    case_completions = [c.text for c in shell.completer.get_completions(doc_show, None)]
    assert "2026-SH-0002" in case_completions

    # 7. AutoSuggest
    from trace_core.cli.shell import TraceAutoSuggest

    suggester = TraceAutoSuggest(shell)
    sug_c = suggester.get_suggestion(None, Document("c"))
    assert sug_c is not None
    assert sug_c.text == "ase list"

    sug_case = suggester.get_suggestion(None, Document("case "))
    assert sug_case is not None
    assert sug_case.text == "list"


def test_shell_rejects_invalid_status_like_typer(service: CaseService, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify shell surfaces invalid --status instead of silently unfiltering."""
    from trace_core.cli.shell import InteractiveShell

    shell = InteractiveShell()
    shell.service = service
    shell.execute_line("case list --status BOGUS")
    assert "not valid" in capsys.readouterr().out


def test_shell_flag_values_are_not_identifiers(service: CaseService, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify `case show --output json` resolves the active case, not 'json'."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cli.shell import InteractiveShell

    service.create_case(CaseCreateDto(number="2026-FLAG-0001", title="Flag Value", lead_examiner="Ex"))
    shell = InteractiveShell()
    shell.service = service
    shell.execute_line("case select 2026-FLAG-0001")
    capsys.readouterr()
    shell.execute_line("case show --output json")
    assert "2026-FLAG-0001" in capsys.readouterr().out


def test_shell_audit_positional_case(service: CaseService, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify `audit show <number>` scopes to that case without --case."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cli.shell import InteractiveShell

    service.create_case(CaseCreateDto(number="2026-POS-0001", title="Positional", lead_examiner="Ex"))
    shell = InteractiveShell()
    shell.service = service
    shell.execute_line("audit show 2026-POS-0001")
    assert "2026-POS-0001" in capsys.readouterr().out


def test_shell_edit_clear_rules(service: CaseService, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify blank required fields keep values while blank optionals clear."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cli.shell import InteractiveShell

    service.create_case(
        CaseCreateDto(
            number="2026-CLR-0001",
            title="Keep Me",
            lead_examiner="Keep Ex",
            description="Drop Me",
            notes="Drop Notes",
            tags=["a"],
        )
    )
    shell = InteractiveShell()
    shell.service = service
    answers = iter(["   ", "   ", "", "", "", ""])
    monkeypatch.setattr("trace_core.cases.shell_handler.Prompt.ask", lambda *a, **k: next(answers))
    monkeypatch.setattr("trace_core.cases.shell_handler.prompt_optional", lambda *a, **k: "")
    monkeypatch.setattr("trace_core.cases.shell_handler.prompt_confirm", lambda *a, **k: True)
    shell.execute_line("case edit 2026-CLR-0001")

    updated = service.get_case("2026-CLR-0001")
    assert updated.title == "Keep Me"
    assert updated.lead_examiner == "Keep Ex"
    # Cleared optionals canonicalize to None (None == "" to the service).
    assert updated.description is None
    assert updated.notes is None
    assert updated.tags == []


def test_shell_list_limit_offset_recent_parity(service: CaseService, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify shell list honors --limit/--offset/--recent like the Typer CLI."""
    from datetime import UTC, datetime, timedelta

    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cli.shell import InteractiveShell
    from trace_core.core.clock import reset_clock, set_clock

    class _TickClock:
        def __init__(self) -> None:
            self.now_value = datetime(2026, 1, 1, tzinfo=UTC)

        def now(self) -> datetime:
            self.now_value += timedelta(seconds=1)
            return self.now_value

    set_clock(_TickClock())
    try:
        for i in range(1, 4):
            service.create_case(CaseCreateDto(number=f"2026-LIM-{i:04d}", title=f"Limit Case {i}", lead_examiner="Ex"))
    finally:
        reset_clock()
    shell = InteractiveShell()
    shell.service = service

    shell.execute_line("case list --limit 1")
    assert "2026-LIM-0003" in capsys.readouterr().out

    shell.execute_line("case list --limit 1 --offset 1")
    assert "2026-LIM-0002" in capsys.readouterr().out

    shell.execute_line("case list --recent")
    assert "2026-LIM-0003" in capsys.readouterr().out

    shell.execute_line("case list --limit x")
    assert "Invalid integer" in capsys.readouterr().out


def test_equals_flag_forms() -> None:
    """Shell flags accept `--flag value` and `--flag=value` identically."""
    from trace_core.core.cli.args import extract_flag_value, has_flag

    assert extract_flag_value(["--output=json"], "--output", "-o") == "json"
    assert extract_flag_value(["--output", "json"], "--output", "-o") == "json"
    assert extract_flag_value(["-o=json"], "--output", "-o") == "json"
    assert extract_flag_value(["--output"], "--output", "-o") is None
    assert has_flag(["--purge=true"], "--purge") is True
    assert has_flag(["--purge"], "--purge") is True
    assert has_flag(["--limit", "10"], "--limit") is True
    assert has_flag(["--limitless", "10"], "--limit") is False


def test_output_format_rejects_unknown() -> None:
    """Unknown --output values fail loudly instead of silently becoming table."""
    from trace_core.core.cli.output import parse_output_format
    from trace_core.core.errors import ValidationError

    assert parse_output_format(["--output", "json"]) == "json"
    assert parse_output_format(["-o=json"]) == "json"
    assert parse_output_format([]) == "table"
    with pytest.raises(ValidationError, match="Invalid output format"):
        parse_output_format(["--output", "xml"])


def test_ghost_suggestion_case_insensitive() -> None:
    """Ghost text matches case-insensitively like completions do."""
    from trace_core.cli.suggest import TraceAutoSuggest

    shell = InteractiveShell()
    suggested = TraceAutoSuggest(shell)._suggest_from_defaults("Case")
    assert suggested is not None
    assert suggested.text == " list"


def test_shell_unknown_suggests_correction(service: CaseService, capsys: pytest.CaptureFixture[str]) -> None:
    shell = InteractiveShell()
    shell.service = service
    shell.execute_line("udpate")
    assert "Did you mean `update`?" in capsys.readouterr().out
    shell.execute_line("xyzzy")
    assert "Type `help` for command list." in capsys.readouterr().out


def test_shell_help_shows_pending_update(
    service: CaseService, capsys: pytest.CaptureFixture[str], temp_storage_root
) -> None:
    from trace_core.updates import cache as check_cache

    _ = temp_storage_root
    check_cache.write_check_cache(
        {"manifest_path": "x", "channel": "stable", "payload": {"available": True, "target": "9.9.9"}}
    )
    shell = InteractiveShell()
    shell.service = service
    shell.execute_line("help")
    assert "Update 9.9.9 available" in capsys.readouterr().out


def test_uninstall_rejects_an_unknown_action() -> None:
    from trace_core.core.cli.uninstall_handler import UninstallShellCommandHandler

    assert UninstallShellCommandHandler().execute("frobnicate", [], None) is False


def test_uninstall_redirects_known_flags_to_standalone() -> None:
    from trace_core.core.cli.uninstall_handler import UninstallShellCommandHandler

    handler = UninstallShellCommandHandler()
    assert handler.execute("--purge-data", [], None) is True
    assert handler.execute("", [], None) is True


def test_the_root_completer_offers_every_registered_command() -> None:
    """Root completion is derived from the registry, so a new handler is reachable at once."""
    from trace_core.cli.shell import InteractiveShell
    from trace_core.cli.suggest import TraceShellCompleter

    shell = InteractiveShell()
    offered = {cmd for cmd, _ in TraceShellCompleter._root_options(shell)}
    assert {h.command_name for h in shell.registry.all_handlers()} <= offered
    for handler in shell.registry.all_handlers():
        for alias in handler.aliases:
            if " " not in alias:
                assert alias in offered


def test_every_console_command_is_reachable_as_a_suggestion() -> None:
    """`recent`/`recents`/`back`/`b` were accepted but absent from the suggestion list."""
    from trace_core.cli.shell import _CONSOLE_COMMANDS, _SHORT_ALIASES, InteractiveShell

    shell = InteractiveShell()
    known = set(shell.registry.known_words()) | set(_CONSOLE_COMMANDS) | set(_SHORT_ALIASES)
    assert {"recent", "recents", "back", "b", "ls", "sh", "ed"} <= known
    assert {"device", "audit", "case"} <= set(shell.registry.known_words())


def test_every_tab_detail_pane_gets_the_same_width_share() -> None:
    """`#device-right` was in the border and padding rules but absent from the width rule."""
    import re

    from trace_core.tui.app import TraceApp

    css = TraceApp.CSS
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    widthed = {sel.strip() for selectors, body in blocks if "width: 2fr" in body for sel in selectors.split(",")}
    padded = {sel.strip() for selectors, body in blocks if "padding: 1 2" in body for sel in selectors.split(",")}
    right_panes = {sel for sel in padded if sel.endswith("-right")}
    missing = right_panes - widthed
    assert not missing, f"detail panes with padding but no width: {missing}"
    assert {"#cases-right", "#device-right"} <= widthed


def test_a_multi_word_alias_is_owned_and_completable() -> None:
    """`owns_text` compared one word, so `list cases ` matched nothing and lost its completions."""
    from trace_core.cases.shell_handler import CaseShellCommandHandler
    from trace_core.core.cli.registry import ShellContext

    handler = CaseShellCommandHandler()
    assert handler.owns_text("list cases ") is True
    assert handler.owns_text("list cases") is True
    assert handler.owns_text("list ") is False
    assert handler.get_completions("list cases ", ShellContext())


def test_a_handler_ignores_a_line_it_does_not_own() -> None:
    from trace_core.audit.shell_handler import AuditShellCommandHandler
    from trace_core.core.cli.registry import ShellContext

    handler = AuditShellCommandHandler()
    assert handler.owns_text("audit show") is True
    assert handler.get_completions("auditor something", ShellContext()) == []


def test_the_anchor_notice_names_a_command_that_exists() -> None:
    """It pointed at an Integrity tab that was merged into Settings, so nobody could act on it."""
    import inspect as py_inspect
    import re

    from trace_core.cli.shell import InteractiveShell
    from trace_core.tui.screens.audit import AuditView

    source = py_inspect.getsource(AuditView.run_command)
    suggestions = re.findall(r"`([^`]+)`", source)
    assert suggestions, "the notice must name the real command"
    root, _, _ = suggestions[0].partition(" ")
    assert root in {h.command_name for h in InteractiveShell().registry.all_handlers()}


def test_repl_keeps_windows_device_nodes_verbatim() -> None:
    from trace_core.cli.shell import _split_line

    assert _split_line(r"device inspect \\.\PhysicalDrive0 --allow-real-hardware") == [
        "device",
        "inspect",
        r"\\.\PhysicalDrive0",
        "--allow-real-hardware",
    ]


def test_repl_split_still_honours_quotes_and_rejects_unbalanced() -> None:
    from trace_core.cli.shell import _split_line

    assert _split_line('case list --search "hello world"') == ["case", "list", "--search", "hello world"]
    with pytest.raises(ValueError, match="No closing quotation"):
        _split_line('say "unbalanced')


def test_repl_inspect_reaches_a_backslash_node_verbatim(
    service: CaseService, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The transcript that failed: backslashes must survive to the resolver."""
    from trace_core.devices import synthetic
    from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT

    root = tmp_path / "box"
    root.mkdir()
    synthetic.write_disk(root / "disk-a.dd", size=2048)
    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.setenv(ENV_DEVICE_ROOT, str(root))
    shell = InteractiveShell(service=service)
    shell.execute_line(rf"device inspect {root}\disk-a.dd --allow-real-hardware")
    assert "not in the current enumeration" not in capsys.readouterr().out
