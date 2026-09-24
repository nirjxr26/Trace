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



