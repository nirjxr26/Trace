"""Unit tests for UI renderers and theme components."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rich.text import Text

from trace_core.cases.domain import CaseStatus
from trace_core.cases.dto import CaseResponseDto
from trace_core.cases.renderers import render_case_detail, render_case_table
from trace_core.core.cli.error_handler import _resolve_error_details, render_error_card
from trace_core.core.errors import ConflictError, NotFoundError, StateTransitionError
from trace_core.core.ui.renderers import (
    format_status_badge,
    get_arrow_char,
    get_error_icon,
    get_rule_char,
    get_success_icon,
    get_warning_icon,
    render_entity_panel,
    render_json,
    render_table,
)

pytestmark = pytest.mark.unit


def test_rule_char() -> None:
    char = get_rule_char()
    assert char in ("─", "-")


def test_format_status_badge() -> None:
    badge_open = format_status_badge(CaseStatus.OPEN)
    assert isinstance(badge_open, Text)
    assert "OPEN" in badge_open.plain

    badge_review = format_status_badge(CaseStatus.UNDER_REVIEW)
    assert "REVIEW" in badge_review.plain

    badge_closed = format_status_badge(CaseStatus.CLOSED)
    assert "CLOSED" in badge_closed.plain

    badge_archived = format_status_badge(CaseStatus.OPEN, is_deleted=True)
    assert "ARCHIVED" in badge_archived.plain

    badge_custom = format_status_badge("UNKNOWN_STATUS")
    assert "UNKNOWN STATUS" in badge_custom.plain


def test_render_table_and_json(sample_case: CaseResponseDto) -> None:
    # Test table render with content
    render_table(
        title="Active Evidence List",
        columns=[("Column A", {"style": "cyan"}), ("Column B", {"style": "white"})],
        rows=[["Row 1", "Value 1"], ["Row 2", "Value 2"]],
        caption="Sample Table Caption",
    )

    # Test table render empty
    render_table(
        title="Empty Table",
        columns=[("Col", {})],
        rows=[],
        empty_message="Custom empty message",
    )

    # Test JSON render
    render_json([sample_case])
    render_json({"key": "value", "count": 42})


def test_render_case_table(sample_cases_batch: list[CaseResponseDto]) -> None:
    # Render populated case table
    render_case_table(sample_cases_batch)

    # Render empty case table
    render_case_table([])


def test_render_case_detail_open_and_closed(sample_case: CaseResponseDto) -> None:
    render_case_detail(sample_case)

    # Test with closed case
    closed_case = CaseResponseDto(
        id=uuid4(),
        number="2026-CR-9999",
        title="Closed Investigation",
        description="Completed analysis",
        lead_examiner="Chief Investigator",
        status=CaseStatus.CLOSED,
        tags=["closed"],
        opened_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        closed_at=datetime.now(UTC),
        is_deleted=False,
    )
    render_case_detail(closed_case)

    # Test with deleted/archived case
    deleted_case = CaseResponseDto(
        id=uuid4(),
        number="2026-CR-0000",
        title="Deleted Case",
        description=None,
        lead_examiner="Investigator Archived",
        status=CaseStatus.OPEN,
        tags=[],
        opened_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        closed_at=None,
        is_deleted=True,
    )
    render_case_detail(deleted_case)


def test_render_case_detail_history_block(sample_case: CaseResponseDto, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify the dossier HISTORY block renders newest-first with a count heading."""
    from types import SimpleNamespace

    from trace_core.cases.renderers import render_case_detail

    events = [
        SimpleNamespace(action=SimpleNamespace(value="CASE_UPDATED"), ts=sample_case.updated_at, actor="Ex"),
        SimpleNamespace(action=SimpleNamespace(value="CASE_CREATED"), ts=sample_case.opened_at, actor="Ex"),
    ]
    for e in events:
        e.subject_case_number = sample_case.number
    render_case_detail(sample_case, events)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "HISTORY · 2 events" in out
    assert "Lead Examiner" in out
    assert "DESCRIPTION" in out


def test_render_entity_panel() -> None:
    render_entity_panel(
        title="Evidence Metadata",
        fields=[("Item", "Disk Image"), ("Size", "500 GB")],
        sections=[("Investigation Notes", "Disk imaged using write-blocker.")],
    )


def test_error_card_escapes_markup(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify reflected input cannot inject Rich markup into error cards."""
    render_error_card("Title", "Unknown action '[red]X[/red]'.")
    out = capsys.readouterr().out
    assert "[red]X[/red]" in out


def test_verify_warns_without_anchor(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify VALID output names the tail blind spot when no anchor was checked."""
    from trace_core.audit.dto import VerifyResultDto
    from trace_core.audit.renderers import render_verify_result

    render_verify_result(VerifyResultDto(is_valid=True, events_verified=3, first_seq=1, last_seq=3))
    assert "No anchor checked" in capsys.readouterr().out


def test_error_handlers() -> None:
    render_error_card(
        title="Integrity Fault",
        message="Evidence integrity verification failed",
        remediation="Recalculate SHA-256 hash against original container.",
    )
    render_error_card(
        title="General Fault",
        message="Unspecified database fault",
        remediation=None,
    )

    # Test _resolve_error_details
    nf = NotFoundError("Case", "2026-MISSING-001")
    title, msg, rem, code = _resolve_error_details(nf, None, None)
    assert title == "Case Not Found"
    assert "2026-MISSING-001" in msg
    assert code == 12

    cf = ConflictError("Case", "number", "2026-EXISTING")
    title, msg, rem, code = _resolve_error_details(cf, None, None)
    assert title == "Duplicate Record"

    st = StateTransitionError("OPEN", "ARCHIVED", "Direct transition disallowed")
    title, msg, rem, code = _resolve_error_details(st, None, None)
    assert title == "Invalid State Transition"


def test_core_ui_icons_and_tokens() -> None:
    assert get_arrow_char() in ("→", "->")
    assert get_error_icon() in ("✗", "[!]")
    assert get_success_icon() in ("✓", "[OK]")
    assert get_warning_icon() in ("⚠", "[!]")


def test_render_status_badge_panel() -> None:
    from trace_core.core.ui.renderers import render_status_badge_panel

    badge_open = render_status_badge_panel(CaseStatus.OPEN)
    assert badge_open is not None
    badge_archived = render_status_badge_panel(CaseStatus.OPEN, is_deleted=True)
    assert badge_archived is not None
    badge_review = render_status_badge_panel(CaseStatus.UNDER_REVIEW)
    assert badge_review is not None
    badge_closed = render_status_badge_panel(CaseStatus.CLOSED)
    assert badge_closed is not None
    badge_unknown = render_status_badge_panel("TEST_STATUS")
    assert badge_unknown is not None


def test_render_minimalist_table() -> None:
    from trace_core.core.ui.renderers import render_minimalist_table

    # Populated table
    render_minimalist_table(
        title="Evidence Targets",
        columns=[("Device ID", {}), ("Type", {})],
        rows=[["DEV-001", "USB Flash Drive"], ["DEV-002", "NVMe SSD"]],
    )
    # Empty table
    render_minimalist_table(
        title="Empty Devices",
        columns=[("Device ID", {})],
        rows=[],
        empty_message="No devices found",
    )


def test_render_dossier() -> None:
    from trace_core.core.ui.renderers import render_dossier, render_status_badge_panel

    badge = render_status_badge_panel(CaseStatus.OPEN)
    render_dossier(
        header_prefix="DEVICE",
        identifier="DEV-001",
        title="Seagate Barracuda 2TB",
        subtitle="Serial: S4Z1XXXX",
        status_badge=badge,
        fields=[("Capacity", "2000 GB"), ("", ""), ("Status", "Intact")],
        sections=[("Forensic Notes", "Write-blocked via hardware bridge.")],
    )


def test_render_key_value_grid() -> None:
    from trace_core.core.ui.renderers import render_key_value_grid

    render_key_value_grid(
        title="System Diagnostics",
        rows=[("Database", "SQLite In-Memory"), ("Status", "Healthy")],
    )
    render_key_value_grid(
        title=None,
        rows=[("Key", "Value")],
    )


def test_prompts_and_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.core.ui.renderers import (
        prompt_confirm,
        prompt_optional,
        prompt_required,
        render_wizard_header,
    )

    render_wizard_header("Device Registration Wizard", "all fields required")

    from rich.prompt import Confirm, Prompt

    # Test prompt_required
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: "Valid Input")
    res = prompt_required("Device Serial", "Must not be empty")
    assert res == "Valid Input"

    # Test prompt_optional
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: kwargs.get("default", ""))
    res_opt = prompt_optional("Notes", hint="optional", default="Default Note")
    assert res_opt == "Default Note"

    # Test prompt_confirm
    monkeypatch.setattr(Confirm, "ask", lambda *args, **kwargs: True)
    assert prompt_confirm("Proceed with disk write-block?") is True
    assert prompt_confirm("Permanent wipe?", is_danger=True) is True


def test_responsive_breakpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.core.ui.renderers import (
        breakpoint_width,
        create_dual_key_value_grid,
        get_breakpoint,
        is_compact_height,
    )

    assert get_breakpoint(60) == "XS"
    assert get_breakpoint(80) == "MD"
    assert get_breakpoint(120) == "LG"
    assert get_breakpoint(160) == "XL"

    assert breakpoint_width(60) == ("XS", 60)
    assert breakpoint_width(120) == ("LG", 120)

    assert is_compact_height(24) is True
    assert is_compact_height(20) is True
    assert is_compact_height(40) is False

    # Test create_dual_key_value_grid
    rows = [("Key1", "Val1"), ("Key2", "Val2"), ("Key3", "Val3")]
    dual_grid = create_dual_key_value_grid(rows)
    assert dual_grid is not None
    assert len(dual_grid.columns) == 4


def test_responsive_rendering_across_terminal_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.dto import AuditEventDto
    from trace_core.audit.renderers import render_audit_table, render_audit_timeline, render_case_audit_header
    from trace_core.cases.dto import CaseResponseDto
    from trace_core.cases.renderers import render_case_detail, render_case_table
    from trace_core.cli.shell import InteractiveShell
    from trace_core.core.ui.renderers import console

    case = CaseResponseDto(
        id=uuid4(),
        number="2026-CR-0001",
        title="Forensic Workstation Disk Inspection with Very Long Title For Testing",
        lead_examiner="Nirjar",
        status=CaseStatus.OPEN,
        tags=["laptop", "ssd", "forensic"],
        opened_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        is_deleted=False,
    )

    event = AuditEventDto(
        seq=1,
        action=AuditAction.CASE_CREATED,
        actor="nirjar",
        ts=datetime.now(UTC),
        subject_case_number="2026-CR-0001",
        payload_json='{"command": "case create", "title": "Inspection"}',
        payload_hash="a" * 64,
        prev_chain="GENESIS",
        chain_hash="b" * 64,
    )

    for width in (60, 80, 120, 160):
        monkeypatch.setattr(console, "width", width)
        for height in (20, 30):
            monkeypatch.setattr(console, "height", height)

            # Render case table and detail
            render_case_table([case])
            render_case_detail(case)

            # Render audit table, header, timeline
            render_audit_table([event])
            render_case_audit_header(case.number, case.title, "OPEN", [event])
            render_audit_timeline([event])

            # Shell banner
            shell = InteractiveShell()
            shell.print_banner()
