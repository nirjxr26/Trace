"""Case-specific presentation and TUI formatting components."""

from typing import Any

from rich.text import Text

from trace_core.cases.dto import CaseResponseDto
from trace_core.core.ui.renderers import (
    format_india_datetime,
    format_india_table_time,
    format_status_badge,
    get_rule_char,
    get_status_style_and_label,
    render_dossier,
    render_minimalist_table,
)
from trace_core.core.ui.theme import THEME_TOKENS


def _create_case_status_badge(case: CaseResponseDto) -> Text:
    """Create a standardized status badge text for case dossier."""
    return format_status_badge(case.status, case.is_deleted)


def _format_closed_timestamp(case: CaseResponseDto, rule_char: str) -> str:
    """Format closed timestamp or active status indicator in IST."""
    if case.closed_at:
        return format_india_datetime(case.closed_at)
    if rule_char == "-":
        return "-  (case is active)"
    return "—  (case is active)"


def render_case_table(cases: list[CaseResponseDto]) -> None:
    """Render streamlined table of cases with a single clean header rule and spacious layout."""
    columns: list[tuple[str, dict[str, Any]]] = [
        ("  Case #", {"style": THEME_TOKENS["accent"], "no_wrap": True}),
        ("Title", {"style": THEME_TOKENS["value"]}),
        ("Examiner", {"style": THEME_TOKENS["label"]}),
        ("Status", {"justify": "left"}),
        ("Opened", {"style": THEME_TOKENS["muted"]}),
    ]

    rows = []
    for c in cases:
        label, style, _ = get_status_style_and_label(c.status, c.is_deleted)
        rows.append(
            [
                f"  {c.number}",
                c.title or "Untitled",
                c.lead_examiner or "-",
                Text(label, style=style),
                format_india_table_time(c.opened_at),
            ]
        )

    render_minimalist_table(
        title="Forensic Cases",
        columns=columns,
        rows=rows,
        empty_message="No cases found matching criteria.",
    )


def render_case_detail(case: CaseResponseDto) -> None:
    """Render streamlined forensic case dossier with whitespace, horizontal rules, and clear focal points."""
    badge = _create_case_status_badge(case)
    rule_char = get_rule_char()
    closed_str = _format_closed_timestamp(case, rule_char)
    tags_str = "  ".join(f"#{t}" for t in case.tags) if case.tags else "None"

    fields: list[tuple[str, Any]] = [
        ("Lead Examiner", case.lead_examiner or "None"),
        ("Tags", Text(tags_str, style=THEME_TOKENS["tag"] if case.tags else THEME_TOKENS["muted"])),
        ("", ""),
        ("Opened", format_india_datetime(case.opened_at)),
        ("Updated", format_india_datetime(case.updated_at)),
        ("Closed", Text(closed_str, style=THEME_TOKENS["value"] if case.closed_at else THEME_TOKENS["muted"])),
    ]

    if case.closed_by:
        fields.append(("Closed By", case.closed_by))
    if case.closure_reason:
        fields.append(("Closure Reason", case.closure_reason))
    if case.archived_at:
        fields.append(("Archived At", format_india_datetime(case.archived_at)))

    sections: list[tuple[str, str | None]] = [
        ("Description", case.description),
        ("Notes", case.notes),
    ]

    render_dossier(
        header_prefix="CASE",
        identifier=case.number,
        title=case.title or "Untitled Case",
        subtitle=f"UUID  {case.id}",
        status_badge=badge,
        fields=fields,
        sections=sections,
    )
