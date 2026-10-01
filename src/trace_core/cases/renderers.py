"""Case-specific presentation and TUI formatting components."""

from typing import Any

from rich.text import Text

from trace_core.cases.domain import CaseStatus
from trace_core.cases.dto import CaseResponseDto
from trace_core.core.ui.renderers import (
    COLUMN_CASE_NUMBER,
    breakpoint_width,
    format_india_datetime,
    format_india_table_time,
    get_status_style_and_label,
    plural,
    render_minimalist_table,
    render_output,
    rule_line,
    safe_text,
    sanitize_terminal,
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
    from trace_core.core.cli.completion import group_by_prefix

    grouped, order = group_by_prefix(cases)
    order.sort(key=lambda p: (0 if p == "CR" else 1, p))
    return grouped, order


def _case_table_row(c: CaseResponseDto, bp: str, term_w: int, active_number: str | None) -> list[Any]:
    """One table row for a case. Breakpoint branches mirror _case_table_columns."""
    # Plain-string cells parse Rich markup: sanitize + escape. Text() cells: sanitize.
    label, style, _ = get_status_style_and_label(c.status, c.is_deleted)
    prefix = "● " if active_number and c.number == active_number else "  "
    case_cell = Text(f"{prefix}{sanitize_terminal(c.number)}", style=THEME_TOKENS["accent"])
    if prefix == "● ":
        case_cell.stylize("bold")
    title = safe_text(c.title or "Untitled")
    examiner = safe_text(c.lead_examiner or "-")
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
            Text(sanitize_terminal(tags), style=THEME_TOKENS["tag"]),
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


def _local_only(dt: Any) -> str:
    """Dossier timestamp: local time only, date and time separated by a middle dot.

    RULE 05 — the UTC duplicate told the examiner nothing they could act on, and every
    forensic timestamp arrived doubled. UTC is still the stored value (§14.4) and is still
    in `--output json`, which is where an examiner verifies a record rather than reads one.

    The separator is added here rather than in `format_india_datetime` because that
    formatter is shared with the audit dossier and both TUI screens; the owner asked for
    this in the case dossier only, so the shared formatter is left alone.
    """
    formatted = format_india_datetime(dt)
    if formatted == "-":
        return formatted
    date_part, _, time_part = formatted.partition(" ")
    return f"{date_part} · {time_part}"


def _case_dossier_fields(case: CaseResponseDto) -> list[tuple[str, Any]]:
    """Metadata rows for the dossier grid. Optional closure/archive rows appended when present."""
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    tags = "  ".join(f"#{t}" for t in case.tags) if case.tags else "—"
    fields: list[tuple[str, Any]] = [
        ("Lead Examiner", sanitize_terminal(case.lead_examiner or "None")),
        ("Opened", _local_only(case.opened_at)),
        ("Updated", _local_only(case.updated_at)),
        ("Closed", _closed_value(case)),
    ]
    if case.closed_by:
        fields.append(("Closed By", sanitize_terminal(case.closed_by)))
    if case.closure_reason:
        fields.append(("Closure Reason", sanitize_terminal(case.closure_reason)))
    if case.archived_at:
        fields.append(("Archived At", format_india_datetime(case.archived_at)))
    if case.archived_by:
        fields.append(("Archived By", sanitize_terminal(case.archived_by)))
    # RULE 04 — tags close the block; the blank separator before them was a group break
    # where there was only one group left.
    fields.append(("Tags", Text(sanitize_terminal(tags), style=TOK["tag"] if case.tags else TOK["muted"])))
    return fields


def _render_case_history(case: CaseResponseDto, events: list[Any] | None, divider: Text) -> None:
    """HISTORY proof block: newest 5 ledger events with a pointer to the full timeline."""
    if not events:
        return
    from trace_core.audit.renderers import short_action_label
    from trace_core.core.ui.renderers import console, format_ledger_time, render_section_title
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    count = plural(len(events), "event")
    render_section_title(f"HISTORY · {count}")
    console.print("")
    for e in events[:5]:
        console.print(
            Text(f"    {format_ledger_time(e.ts)}  {short_action_label(e.action)} · {sanitize_terminal(e.actor)}")
        )
    if len(events) > 5:
        console.print(
            Text(f"    … and older in `audit show --case {sanitize_terminal(case.number)}`", style=TOK["muted"])
        )
    console.print(divider)


def render_case_detail(case: CaseResponseDto, events: list[Any] | None = None) -> None:
    """Forensic case dossier in the audit-detail language: identity block, grouped
    metadata, DESCRIPTION/NOTES sections, and a HISTORY proof block."""
    from trace_core.core.ui.renderers import (
        console,
        create_key_value_grid,
        kv_width,
        render_detail_header,
        render_section_title,
        table_padding,
    )
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    label, style, _ = get_status_style_and_label(case.status, case.is_deleted)

    render_detail_header(
        "CASE",
        sanitize_terminal(case.number),
        sanitize_terminal(case.title or "Untitled Case"),
        Text.assemble((f"  {label} · ", style), (f"Opened {_local_only(case.opened_at)}", TOK["muted"])),
    )

    fields = _case_dossier_fields(case)
    bp, term_w = breakpoint_width()
    # One rhythm for the whole dossier: divider, section title, its rows, divider. The
    # blank line that used to sit between a divider and the title below it meant every
    # section started a row late, so the stack read as loose rather than grouped; the
    # divider alone already separates the sections, so the gap is redundant padding.
    divider = Text(rule_line(term_w), style=TOK["border"])
    console.print(divider)

    console.print(create_key_value_grid(fields, width=kv_width(bp, min_width=16), padding=table_padding(bp)))
    console.print(divider)

    for section_title, section_body in (("DESCRIPTION", case.description), ("NOTES", case.notes)):
        if not (section_body and section_body.strip()):
            continue
        render_section_title(section_title)
        console.print("")
        console.print(Text(f"    {sanitize_terminal(section_body.strip())}", style=TOK["value"]))
        console.print(divider)

    _render_case_history(case, events, divider)
    _render_case_next(case)


def _render_case_next(case: CaseResponseDto) -> None:
    """NEXT ACTIONS block: one copy-pasteable command per line, each legal for this case.

    RULE 10 — a dossier that ends in silence leaves the user guessing. But a next-step
    line is worse than silence if it advertises a command that raises: `update_case`
    rejects a CLOSED case outright and `_VALID_TRANSITIONS[CLOSED]` is empty (§14.3), so a
    sealed case gets the read-only evidence path only, never the mutation paths.

    Vertical rather than `a → b → c` on one line: the arrow chain ran past the right edge
    on a narrow pane and truncated mid-command, and stacking keeps each command intact and
    individually selectable. The `--output json` step moved here from the old `Tip:` line —
    it is the same class of command as the others, and splitting raw access into a separate
    dim sentence was what made the ending feel arbitrary.
    """
    from trace_core.core.ui.renderers import console, render_section_title
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    number = sanitize_terminal(case.number)
    read_steps = [f"audit show --case {number}", f"case show {number} --output json"]
    steps = (
        read_steps
        if case.status == CaseStatus.CLOSED
        else [f"case edit {number}", f"case close {number}", *read_steps]
    )

    render_section_title("NEXT ACTIONS")
    console.print("")
    for step in steps:
        console.print(Text(f"    → {step}", style=TOK["muted"]))
    console.print("")


def _closed_value(case: CaseResponseDto) -> Any:
    """Closed timestamp, or an active marker. Single source for the dossier."""
    if not case.closed_at:
        return Text("—  (case is active)", style=THEME_TOKENS["muted"])
    return _local_only(case.closed_at)


def render_case(case: CaseResponseDto, output: str = "table", events: list[Any] | None = None) -> None:
    """Render a single case in table dossier or raw JSON form."""
    render_output(output, case, lambda: render_case_detail(case, events))


def render_cases(cases: list[CaseResponseDto], output: str = "table", active_number: str | None = None) -> None:
    """Render a case collection in minimalist table or raw JSON form."""
    render_output(output, cases, lambda: render_case_table(cases, active_number=active_number))
