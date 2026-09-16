"""Case-specific presentation and TUI formatting components."""

from typing import Any

from rich.text import Text

from trace_core.cases.dto import CaseResponseDto
from trace_core.core.ui.renderers import (
    COLUMN_CASE_NUMBER,
    breakpoint_width,
    format_india_datetime,
    format_india_table_time,
    format_utc_zulu,
    get_status_style_and_label,
    render_minimalist_table,
    render_output,
    rule_line,
)
from trace_core.core.ui.theme import THEME_TOKENS


def _case_table_columns(bp: str, term_w: int) -> list[tuple[str, dict[str, Any]]]:
    """Single source for case columns. XS 3-col, narrow MD 4-col, wide 5-col, XL 6-col."""
    from trace_core.core.ui.renderers import title_max_width

    if bp == "XS":
        return [
            (COLUMN_CASE_NUMBER, {"style": THEME_TOKENS["accent"], "no_wrap": True, "max_width": 16}),
            (
                "Title",
                {"style": THEME_TOKENS["value"], "overflow": "ellipsis", "max_width": title_max_width(bp, term_w)},
            ),
            ("Status", {"justify": "left", "no_wrap": True, "max_width": 10}),
        ]
    if bp in ("MD", "LG") and term_w < 100:
        return [
            (COLUMN_CASE_NUMBER, {"style": THEME_TOKENS["accent"], "no_wrap": True, "max_width": 16}),
            (
                "Title",
                {"style": THEME_TOKENS["value"], "overflow": "ellipsis", "max_width": title_max_width(bp, term_w)},
            ),
            ("Examiner", {"style": THEME_TOKENS["label"], "overflow": "ellipsis", "max_width": 14}),
            ("Status", {"justify": "left", "no_wrap": True, "max_width": 10}),
        ]
    if bp in ("MD", "LG"):
        return [
            (COLUMN_CASE_NUMBER, {"style": THEME_TOKENS["accent"], "no_wrap": True, "max_width": 16}),
            (
                "Title",
                {"style": THEME_TOKENS["value"], "overflow": "ellipsis", "max_width": title_max_width(bp, term_w)},
            ),
            ("Examiner", {"style": THEME_TOKENS["label"], "overflow": "ellipsis", "max_width": 14}),
            ("Status", {"justify": "left", "no_wrap": True, "max_width": 10}),
            ("Opened", {"style": THEME_TOKENS["muted"], "no_wrap": True, "max_width": 14}),
        ]
    return [
        (COLUMN_CASE_NUMBER, {"style": THEME_TOKENS["accent"], "no_wrap": True, "max_width": 16}),
        ("Title", {"style": THEME_TOKENS["value"], "overflow": "ellipsis"}),
        ("Examiner", {"style": THEME_TOKENS["label"], "overflow": "ellipsis", "max_width": 16}),
        ("Status", {"justify": "left", "no_wrap": True, "max_width": 10}),
        ("Opened", {"style": THEME_TOKENS["muted"], "no_wrap": True, "max_width": 14}),
        ("Tags", {"style": THEME_TOKENS["tag"], "overflow": "ellipsis", "max_width": 20}),
    ]


def _group_cases(cases: list[CaseResponseDto]) -> tuple[dict[str, list[CaseResponseDto]], list[str]]:
    """Group by middle code CR/NR/CLI, original order inside group, CR first then alphabetical."""
    from trace_core.core.cli.completion import number_group

    grouped: dict[str, list[CaseResponseDto]] = {}
    order: list[str] = []
    for c in cases:
        pref = number_group(c.number)
        if pref not in grouped:
            grouped[pref] = []
            order.append(pref)
        grouped[pref].append(c)
    order.sort(key=lambda p: (0 if p == "CR" else 1, p))
    return grouped, order


def _case_table_row(c: CaseResponseDto, bp: str, term_w: int, active_number: str | None) -> list[Any]:
    """One table row for a case. Breakpoint branches mirror _case_table_columns."""
    label, style, _ = get_status_style_and_label(c.status, c.is_deleted)
    prefix = "● " if active_number and c.number == active_number else "  "
    case_cell = Text(f"{prefix}{c.number}", style=THEME_TOKENS["accent"])
    if prefix == "● ":
        case_cell.stylize("bold")
    title = c.title or "Untitled"
    examiner = c.lead_examiner or "-"
    badge = Text(label, style=style)
    if bp == "XS":
        return [case_cell, title, badge]
    if bp == "XL":
        tags = " ".join(f"#{t}" for t in c.tags[:2]) if c.tags else "-"
        return [
            case_cell,
            title,
            examiner,
            badge,
            format_india_table_time(c.opened_at),
            Text(tags, style=THEME_TOKENS["tag"]),
        ]
    if bp in ("MD", "LG") and term_w < 100:
        return [case_cell, title, examiner, badge]
    return [case_cell, title, examiner, badge, format_india_table_time(c.opened_at)]


def render_case_table(cases: list[CaseResponseDto], active_number: str | None = None) -> None:
    """Render streamlined table grouped by middle code CR/NR/CLI with space between groups. Responsive XS-XL."""
    from trace_core.core.ui.renderers import breakpoint_width

    bp, term_w = breakpoint_width()
    columns = _case_table_columns(bp, term_w)
    grouped, order = _group_cases(cases)
    rows: list[list[Any]] = []
    for idx, pref in enumerate(order):
        if idx > 0:
            # blank separator — width matches columns
            rows.append(["" for _ in columns])  # type: ignore[list-item]
        for c in grouped[pref]:
            rows.append(_case_table_row(c, bp, term_w, active_number))

    render_minimalist_table(
        title="Forensic Cases",
        columns=columns,
        rows=rows,
        empty_message="No cases found. Run 'case create' to add one.",
        total=len(cases),
    )


def _case_dossier_fields(case: CaseResponseDto, opened: str) -> list[tuple[str, Any]]:
    """Metadata rows for the dossier grid. Optional closure/archive rows appended when present."""
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    tags = "  ".join(f"#{t}" for t in case.tags) if case.tags else "—"
    fields: list[tuple[str, Any]] = [
        ("Lead Examiner", case.lead_examiner or "None"),
        ("Tags", Text(tags, style=TOK["tag"] if case.tags else TOK["muted"])),
        ("", ""),
        ("Opened", opened),
        ("Updated", f"{format_india_datetime(case.updated_at)} ({format_utc_zulu(case.updated_at)})"),
        ("Closed", _closed_value(case)),
    ]
    if case.closed_by:
        fields.append(("Closed By", case.closed_by))
    if case.closure_reason:
        fields.append(("Closure Reason", case.closure_reason))
    if case.archived_at:
        fields.append(("Archived At", format_india_datetime(case.archived_at)))
    if case.archived_by:
        fields.append(("Archived By", case.archived_by))
    return fields


def _render_case_history(case: CaseResponseDto, events: list[Any] | None) -> None:
    """HISTORY proof block: newest 5 ledger events with a pointer to the full timeline."""
    if not events:
        return
    from trace_core.audit.renderers import short_action_label
    from trace_core.core.ui.renderers import console, format_ledger_time, render_section_title
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    count = f"{len(events)} event" + ("s" if len(events) != 1 else "")
    render_section_title(f"HISTORY · {count}")
    console.print("")
    for e in events[:5]:
        console.print(Text(f"  {format_ledger_time(e.ts)}  {short_action_label(e.action)} · {e.actor}"))
    if len(events) > 5:
        console.print(Text(f"  … and older in `audit show --case {case.number}`", style=TOK["muted"]))
    console.print("")


def render_case_detail(case: CaseResponseDto, events: list[Any] | None = None) -> None:
    """Forensic case dossier in the audit-detail language: identity block, grouped
    metadata, DESCRIPTION/NOTES sections, and a HISTORY proof block."""
    from trace_core.core.ui.renderers import (
        console,
        create_key_value_grid,
        kv_width,
        render_detail_header,
        render_raw_tip,
        render_section_title,
        table_padding,
    )
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    label, style, _ = get_status_style_and_label(case.status, case.is_deleted)
    opened = f"{format_india_datetime(case.opened_at)} ({format_utc_zulu(case.opened_at)})"

    render_detail_header(
        "CASE",
        case.number,
        case.title or "Untitled Case",
        Text.assemble((f"  {label} · ", style), (f"Opened {format_india_datetime(case.opened_at)}", TOK["muted"])),
    )

    fields = _case_dossier_fields(case, opened)
    bp, term_w = breakpoint_width()
    # Tight rhythm: dividers hug the content above; exactly one blank line below
    # every divider and every title, so sections stay easy to notice.
    divider = Text(rule_line(term_w), style=TOK["border"])
    console.print(divider)
    console.print("")

    console.print(create_key_value_grid(fields, width=max(kv_width(bp), 16), padding=table_padding(bp)))
    console.print(divider)
    console.print("")

    for section_title, section_body in (("DESCRIPTION", case.description), ("NOTES", case.notes)):
        if not (section_body and section_body.strip()):
            continue
        render_section_title(section_title)
        console.print("")
        console.print(Text(f"    {section_body.strip()}", style=TOK["value"]))
        console.print(divider)
        console.print("")

    _render_case_history(case, events)

    render_raw_tip(f"case show {case.number} --output json")


def _closed_value(case: CaseResponseDto) -> Any:
    """Closed timestamp with UTC, or an active marker. Single source for the dossier."""
    if not case.closed_at:
        return Text("—  (case is active)", style=THEME_TOKENS["muted"])
    return f"{format_india_datetime(case.closed_at)} ({format_utc_zulu(case.closed_at)})"


def render_case(case: CaseResponseDto, output: str = "table", events: list[Any] | None = None) -> None:
    """Render a single case in table dossier or raw JSON form."""
    render_output(output, case, lambda: render_case_detail(case, events))


def render_cases(cases: list[CaseResponseDto], output: str = "table", active_number: str | None = None) -> None:
    """Render a case collection in minimalist table or raw JSON form."""
    render_output(output, cases, lambda: render_case_table(cases, active_number=active_number))
