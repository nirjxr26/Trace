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
    render_json,
    render_minimalist_table,
)
from trace_core.core.ui.theme import THEME_TOKENS


def _create_case_status_badge(case: CaseResponseDto) -> Text:
    """Create a standardized status badge text for case dossier."""
    return format_status_badge(case.status, case.is_deleted)


def _format_closed_timestamp(case: CaseResponseDto, rule_char: str) -> str:
    """Format closed timestamp with IST + UTC for forensic clarity."""
    if case.closed_at:
        try:
            from datetime import UTC

            utc = case.closed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            return f"{format_india_datetime(case.closed_at)} ({utc})"
        except Exception:
            return format_india_datetime(case.closed_at)
    if rule_char == "-":
        return "-  (case is active)"
    return "—  (case is active)"


def _case_prefix(number: str) -> str:
    try:
        return number.split("-")[1] if "-" in number else "OTHER"
    except Exception:
        return "OTHER"


def render_case_table(cases: list[CaseResponseDto], active_number: str | None = None) -> None:
    """Render streamlined table grouped by middle code CR/NR/CLI with space between groups."""
    columns: list[tuple[str, dict[str, Any]]] = [
        ("  Case #", {"style": THEME_TOKENS["accent"], "no_wrap": True}),
        ("Title", {"style": THEME_TOKENS["value"]}),
        ("Examiner", {"style": THEME_TOKENS["label"]}),
        ("Status", {"justify": "left"}),
        ("Opened", {"style": THEME_TOKENS["muted"]}),
    ]

    # group by middle code like CR/NR/CLI, keep original order inside group, groups sorted alphabetically but CR first
    grouped: dict[str, list[CaseResponseDto]] = {}
    order: list[str] = []
    for c in cases:
        pref = _case_prefix(c.number)
        if pref not in grouped:
            grouped[pref] = []
            order.append(pref)
        grouped[pref].append(c)
    # prefer CR first, then others alphabetically
    order.sort(key=lambda p: (0 if p == "CR" else 1, p))
    rows: list[list[Any]] = []
    for idx, pref in enumerate(order):
        if idx > 0:
            rows.append(["", "", "", "", ""])  # type: ignore[list-item]  # blank separator between groups
        for c in grouped[pref]:
            label, style, _ = get_status_style_and_label(c.status, c.is_deleted)
            prefix = "● " if active_number and c.number == active_number else "  "
            case_cell = Text(
                f"{prefix}{c.number}", style=THEME_TOKENS["accent"] if prefix == "● " else THEME_TOKENS["accent"]
            )
            if prefix == "● ":
                case_cell.stylize("bold")
            rows.append(
                [
                    case_cell,
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
        empty_message="No cases found. Run 'case create' to add one.",
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
    if case.archived_by:
        fields.append(("Archived By", case.archived_by))

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
    from trace_core.core.ui.renderers import console

    console.print("[dim]Tip: double-click number/UUID to copy · [c] Copy[/dim]\n")


def render_case(case: CaseResponseDto, output: str = "table") -> None:
    """Render a single case in table dossier or raw JSON form."""
    if output.lower() == "json":
        render_json(case)
    else:
        render_case_detail(case)


def render_cases(cases: list[CaseResponseDto], output: str = "table", active_number: str | None = None) -> None:
    """Render a case collection in minimalist table or raw JSON form."""
    if output.lower() == "json":
        render_json(cases)
    else:
        render_case_table(cases, active_number=active_number)
