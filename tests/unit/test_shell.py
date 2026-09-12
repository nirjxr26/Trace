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
