"""Unit tests for interactive console shell dispatching."""

from trace_core.adapters.db.session import DatabaseSessionManager
from trace_core.application.cases import CaseService
from trace_core.application.dto import CaseCreateDto
from trace_core.cli.shell import InteractiveShell


def test_shell_line_execution_and_aliases() -> None:
    session_mgr = DatabaseSessionManager("sqlite:///:memory:")
    session_mgr.init_schema()
    service = CaseService(session_mgr)

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
