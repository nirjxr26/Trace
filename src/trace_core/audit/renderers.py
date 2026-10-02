"""Audit renderers."""

from typing import Any, Final

from rich.text import Text

from trace_core.audit.dto import AuditEventDto, VerifyResultDto
from trace_core.core.ui.renderers import (
    COLUMN_CASE_NUMBER,
    format_india_datetime,
    get_status_style_and_label,
    get_success_icon,
    plural,
    render_key_value_grid,
    render_minimalist_table,
    render_output,
    safe_text,
    sanitize_terminal,
    split_hash,
)
from trace_core.core.ui.theme import THEME_TOKENS


def _audit_table_columns(bp: str) -> list[tuple[str, dict[str, Any]]]:
    """Single source for audit columns. Actor/Command live in the detail view, never the list."""
    if bp == "XS":
        return [
            ("Seq", {"style": THEME_TOKENS["accent"], "no_wrap": True, "max_width": 6}),
            ("Action", {"style": THEME_TOKENS["value"], "no_wrap": True, "max_width": 14}),
            (COLUMN_CASE_NUMBER, {"style": THEME_TOKENS["label"], "no_wrap": True, "max_width": 16}),
        ]
    return [
        ("Seq", {"style": THEME_TOKENS["accent"], "no_wrap": True, "max_width": 6}),
        ("Action", {"style": THEME_TOKENS["value"], "no_wrap": True, "max_width": 14}),
        (COLUMN_CASE_NUMBER, {"style": THEME_TOKENS["label"], "no_wrap": True, "max_width": 16}),
        ("Time", {"style": THEME_TOKENS["muted"], "no_wrap": True, "max_width": 14}),
    ]


def render_audit_table(events: list[AuditEventDto]) -> None:
    from trace_core.core.ui.renderers import breakpoint_width, format_ledger_time

    bp, term_w = breakpoint_width()
    cols = _audit_table_columns(bp)

    rows: list[list[Any]] = []
    for e in events:
        _, style, _ = get_status_style_and_label(e.action, False)
        # Plain-string cells parse Rich markup: sanitize + escape. Text() cells: sanitize.
        number = safe_text(e.subject_case_number)
        if bp == "XS":
            rows.append(
                [
                    str(e.seq),
                    Text(e.action.value, style=style),
                    number,
                ]
            )
        else:
            rows.append(
                [
                    str(e.seq),
                    Text(e.action.value, style=style),
                    number,
                    format_ledger_time(e.ts),
                ]
            )
    render_minimalist_table(
        "Audit Ledger",
        cols,
        rows,
        empty_message="No audit events found. Create or edit a case to generate ledger entries.",
    )
    if events:
        from trace_core.core.ui.renderers import console

        cases = len({e.subject_case_number for e in events})
        actors = len({e.actor for e in events})
        if bp == "XS" and term_w < 60:
            console.print(f"[dim]Chain: {len(events)} events · run `trace audit verify` for integrity[/dim]\n")
        else:
            console.print(
                f"[dim]Chain: SHA-256 · {len(events)} events · {cases} cases, "
                f"{actors} actors · run `trace audit verify` for integrity[/dim]\n"
            )


def render_event(event: AuditEventDto, output: str = "table") -> None:
    """Render a single event as a 5W1H dossier or raw JSON. Mirrors render_case."""
    render_output(output, event, lambda: render_audit_detail(event))


def render_events(events: list[AuditEventDto], output: str = "table") -> None:
    """Render an event collection as a table or raw JSON. Mirrors render_cases."""
    render_output(output, events, lambda: render_audit_table(events))


def render_verify(res: VerifyResultDto, output: str = "table", anchor: str | None = None) -> None:
    """Render a verify result as a grid or raw JSON."""
    render_output(output, res, lambda: render_verify_result(res, anchor))


def render_case_audit_header(case_number: str, title: str, status: str, events: list[AuditEventDto]) -> None:
    """CASE HISTORY block: identity, then the created/updated pair as its own labelled rows.

    This replaced a single dense `Status: … Events: … Created: … Last: …` line. That line
    made the reader parse four unrelated facts out of one run of text, and the examiner's
    first question about a case is always "who touched this and when" — so state, count and
    the two lifecycle timestamps are now four separate lines, each labelled by what it is.
    """
    from trace_core.core.ui.renderers import (
        breakpoint_width,
        console,
        fit_text,
        format_history_clock,
        format_history_date,
        get_status_style_and_label,
        rule_line,
    )
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    _, term_w = breakpoint_width()
    console.print("")
    console.print(Text("  CASE HISTORY", style=TOK["title"]))
    heading = f"  {sanitize_terminal(case_number)}"
    if title:
        heading += f" · {fit_text(sanitize_terminal(title), max(20, term_w - len(case_number) - 6))}"
    console.print(Text(heading, style=TOK["accent"]))

    label, style, _ = get_status_style_and_label(status, False)
    if not events:
        console.print(Text(f"  {label} · no recorded actions", style=style))
        console.print(Text(f"  {rule_line(term_w).strip()}", style=TOK["border"]))
        console.print("")
        return

    count = plural(len(events), "recorded action")
    console.print(Text.assemble((f"  {label} · ", style), (count, TOK["muted"])))
    # Oldest first: the ledger arrives newest-first, so the last element is the creation.
    created, updated = events[-1], events[0]
    for name, event in (("Created", created), ("Updated", updated)):
        stamp = f"{format_history_date(event.ts)} · {format_history_clock(event.ts)}"
        console.print(Text(f"  {name:<9}{stamp}", style=TOK["muted"]))
    console.print(Text(f"  {rule_line(term_w).strip()}", style=TOK["border"]))
    console.print("")


# Past-tense phrases for the CASE ACTIVITY line. Kept beside the renderer rather than in
# `audit/domain.py` because `ACTION_TITLES` there feeds the per-event detail header, which
# reads as a noun phrase ("Case details updated"); this one is the opening of a sentence.
_ACTIVITY_PHRASES: Final[dict[str, str]] = {
    "CASE_CREATED": "Created case",
    "CASE_UPDATED": "Updated case",
    "CASE_CLOSED": "Closed case",
    "CASE_ARCHIVED": "Archived case",
    "CASE_RESTORED": "Restored case",
    "CASE_PURGED": "Purged case",
}


def _activity_phrase(action: Any) -> str:
    """Past-tense phrase for the CASE ACTIVITY line: `Updated case`, not `Updated`.

    `short_action_label` strips the `CASE_` prefix and titles the remainder, which gives a
    bare adjective (`Updated`). Read as the first words of a sentence it does not parse, so
    the subject word is restored. Unknown actions fall back to the bare label rather than
    inventing a phrase for an action this build has never seen.
    """
    value = getattr(action, "value", action)
    return _ACTIVITY_PHRASES.get(str(value), short_action_label(action))


def _activity_summary(e: AuditEventDto, details: dict, term_w: int) -> str:
    """The third line of an activity entry: what actually changed, labelled by field name.

    Field names are title-cased because they are read as prose here (`Changed: Title, Lead
    Examiner`), and a bare `title, lead_examiner` in the middle of a sentence looks like a
    bug rather than a list. The single-field case keeps before → after, now named, so a lone
    entry is still attributable.
    """
    from trace_core.core.ui.renderers import fit_text, format_field_name

    action = e.action.value
    if action == "CASE_CREATED":
        title = details.get("title", "")
        return f"Title: {sanitize_terminal(title)}" if title else ""
    if action == "CASE_UPDATED":
        changed = details.get("changed", [])
        before = details.get("before", {})
        after = details.get("after", {})
        if not changed:
            return ""
        names = [format_field_name(f) for f in changed]
        if len(changed) == 1 and changed[0] in before:
            old = sanitize_terminal(format_change_value(before[changed[0]]))
            new = sanitize_terminal(format_change_value(after[changed[0]]))
            return fit_text(f'{names[0]}: "{old}" → "{new}"', max(20, term_w - 16))
        return fit_text(f"Changed: {', '.join(names)}", max(20, term_w - 16))
    if action == "CASE_CLOSED":
        reason = details.get("reason", "")
        return f"Reason: {sanitize_terminal(reason)}" if reason else "└─ OPEN → CLOSED"
    return _timeline_summary(e, details)


def _timeline_summary(e: AuditEventDto, details: dict) -> str:
    action = e.action.value
    if action == "CASE_CREATED":
        return f'"{details.get("title", "")}"'
    if action == "CASE_UPDATED":
        changed = details.get("changed", [])
        before = details.get("before", {})
        after = details.get("after", {})
        if len(changed) == 1 and changed[0] in before:
            return f'"{before[changed[0]]}" → "{after[changed[0]]}"'
        if changed:
            return f"Changed: {', '.join(changed)}"
        return ""
    if action == "CASE_CLOSED":
        reason = details.get("reason", "")
        return f"Reason: {reason}" if reason else "└─ OPEN → CLOSED"
    if action == "CASE_ARCHIVED":
        return "Archived"
    if action == "CASE_RESTORED":
        return "Restored"
    if action == "CASE_PURGED":
        return "Purged"
    return ""


def render_audit_timeline(events: list[AuditEventDto]) -> None:
    """CASE ACTIVITY block: one entry per recorded action, newest first.

    Reached only through `render_case_timeline_view`, which requires a `--case` filter and
    a resolvable case — so `subject_case_number` is by construction the case already named
    in the header above this block. Repeating it on every row was pure noise and is gone;
    the actor and the sequence number took its place, since those differ per row.
    """
    from trace_core.audit.events import parse_details
    from trace_core.core.ui.renderers import (
        breakpoint_width,
        console,
        format_history_clock,
        render_section_title,
        rule_line,
    )
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    if not events:
        return
    _, term_w = breakpoint_width()
    render_section_title("CASE ACTIVITY")
    console.print("")

    # `format_history_clock` is always `hh:mm AM/PM` (9 chars), so the activity column is a
    # fixed width and the continuation lines can be aligned under the label by arithmetic
    # rather than by eyeballing the indent.
    body_indent = " " * (2 + 9 + 3)

    for e in events:
        details = parse_details(e.payload_json)
        clock = format_history_clock(e.ts)
        phrase = _activity_phrase(e.action)
        first = Text.assemble(
            (f"  {clock}   ", TOK["accent"]),
            (phrase, TOK["value"]),
            (f"  ·  #{e.seq}", TOK["muted"]),
        )
        console.print(first)
        console.print(Text(f"{body_indent}By {sanitize_terminal(e.actor)}", style=TOK["muted"]))
        summary = _activity_summary(e, details, term_w)
        if summary:
            console.print(Text(f"{body_indent}{summary}"))
        console.print("")

    console.print(Text(f"  {rule_line(term_w).strip()}", style=TOK["border"]))
    console.print(f"[dim] {plural(len(events), 'action')} shown · newest first[/dim]\n")


def action_title(action: str) -> str:
    """Human title for an audit action enum. Single source for detail headers."""
    from trace_core.audit.domain import ACTION_TITLES

    return ACTION_TITLES.get(action, action.replace("_", " ").title())


def short_action_label(action: Any) -> str:
    """Compact timeline label for an action enum or string. Single source."""
    value = getattr(action, "value", action)
    return str(value).replace("CASE_", "").title()


def format_change_value(value: Any) -> str:
    """Human empties shared by CLI + TUI change views: missing is Not set, blank is Empty."""
    import json

    if value is None:
        return "Not set"
    if value == "":
        return "Empty"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _integrity_rows(e: AuditEventDto, term_w: int) -> list[tuple[str, Any]]:
    """Categorized ledger hashes, split for narrow terminals."""
    return [
        ("Payload Hash", split_hash(e.payload_hash, term_w)),
        ("Previous Chain", split_hash(e.prev_chain, term_w)),
        ("Chain Hash", split_hash(e.chain_hash, term_w)),
    ]


def render_audit_detail(e: AuditEventDto) -> None:
    from trace_core.audit.events import parse_details
    from trace_core.core.ui.renderers import (
        breakpoint_width,
        console,
        create_key_value_grid,
        format_india_datetime,
        format_utc_zulu,
        get_arrow_char,
        kv_width,
        render_detail_header,
        render_minimalist_table,
        render_raw_tip,
        render_section_title,
        table_padding,
    )
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    details = parse_details(e.payload_json)
    utc_display = format_utc_zulu(e.ts)
    bp, term_w = breakpoint_width()

    render_detail_header(
        "AUDIT",
        f"#{e.seq}",
        action_title(e.action.value),
        f"{sanitize_terminal(e.subject_case_number)} · {format_india_datetime(e.ts)}",
    )
    console.print(
        create_key_value_grid(
            _detail_fields(e, details, utc_display), width=kv_width(bp, min_width=16), padding=table_padding(bp)
        )
    )

    changed = details.get("changed", [])
    before = details.get("before", {})
    after = details.get("after", {})
    if changed:
        arrow = get_arrow_char()
        old_vals = [sanitize_terminal(format_change_value(before.get(field))) for field in changed]
        new_vals = [sanitize_terminal(format_change_value(after.get(field))) for field in changed]

        def _fit(values: list[str], minimum: int = 12, maximum: int = 32) -> int:
            return min(maximum, max([minimum] + [len(v) for v in values]))

        field_w = _fit([f"  {f}" for f in changed], minimum=10, maximum=20)
        before_w = _fit(old_vals)
        after_w = _fit(new_vals)
        rows: list[list[Any]] = []
        for field, old, new in zip(changed, old_vals, new_vals):
            rows.append(
                [
                    Text(f"  {field}", style=TOK["muted"]),
                    Text(old, style=TOK["danger"]),
                    Text(arrow, style=TOK["muted"]),
                    Text(new, style=TOK["success"]),
                ]
            )
        count = plural(len(changed), "record")
        render_minimalist_table(
            f"CHANGES · {count}",
            [
                ("  Field", {"style": TOK["muted"], "no_wrap": True, "max_width": field_w}),
                ("Before", {"overflow": "fold", "max_width": before_w}),
                ("", {"no_wrap": True}),
                ("After", {"overflow": "fold", "max_width": after_w, "min_width": after_w + 4}),
            ],
            rows,
            show_count=False,
            tight=True,
        )

    from trace_core.audit.verifier import verify_event

    if not changed:
        console.print("")

    intact = verify_event(
        e.payload_json, e.payload_hash, e.prev_chain, e.chain_hash, e.seq, signature=e.signature, key_id=e.key_id
    )
    seal = "✓ VERIFIED" if intact else "✗ MISMATCH"
    render_section_title(f"INTEGRITY · {seal}", style=TOK["accent"] if intact else TOK["danger"])
    console.print(
        create_key_value_grid(_integrity_rows(e, term_w), width=kv_width(bp, min_width=16), padding=table_padding(bp))
    )
    console.print("")
    if not intact:
        console.print("[dim]Row failed its self-check — run `audit verify` for the full chain.[/dim]")
    render_raw_tip(f"audit show --seq {e.seq} --output json for the raw payload")


def _detail_fields(e: AuditEventDto, details: dict, utc_display: str) -> list[tuple[str, Any]]:
    host = details.get("host") or "-"
    reason = (details.get("reason") or "").strip()
    rows: list[tuple[str, Any]] = [
        ("Actor", f"{sanitize_terminal(e.actor)} @ {sanitize_terminal(host)}"),
        ("When", f"{format_india_datetime(e.ts)} ({utc_display})"),
        ("", ""),
        ("Event", e.action.value),
    ]
    if reason:
        rows.append(("Reason", sanitize_terminal(reason)))
    return rows


def _what_text(mismatch_type: str | None) -> str:
    if mismatch_type == "payload_hash":
        return "payload_json edited but payload_hash not updated"
    if mismatch_type == "prev_chain":
        return "prev_chain linkage broken"
    if mismatch_type == "signature":
        return "signature mismatch (event not signed by trusted key)"
    return "chain_hash mismatch"


def _render_valid(res: VerifyResultDto, anchor: str | None = None) -> None:
    from trace_core.core.ui.renderers import console

    gaps_str = ", ".join(str(g) for g in res.sequence_gaps) if res.sequence_gaps else "None"
    note = " (rolled-back, not tampering)" if res.sequence_gaps else ""
    rows: list[tuple[str, Any]] = [
        ("Chain", "trace-audit-v1 · SHA-256 · trace-canonical-json-v1"),
        (
            "Events",
            f"{res.events_verified} verified · seq {res.first_seq} → {res.last_seq}" if res.first_seq else "0",
        ),
        ("Range", f"{res.first_seq} → {res.last_seq}" if res.first_seq else "-"),
        ("Gaps", gaps_str + note),
        (
            "Checked",
            "payload_hash (SHA256 canonical) + chain_hash (prev‖hash‖seq) recomputed from payload_json",
        ),
    ]
    if anchor:
        rows.append(("Anchor", f"Tail matches {anchor}"))
    else:
        rows.append(
            (
                "Anchor",
                Text("No anchor checked — tail truncation is undetectable without one.", style=THEME_TOKENS["warning"]),
            )
        )
    rows.append(("Result", Text(f"{get_success_icon()} No tampering. Ledger intact.", style=THEME_TOKENS["success"])))
    render_key_value_grid("Audit Verify — ✓ VALID", rows)
    console.print("[dim]Tip: export with `audit export --out bundle.jsonl` to preserve chain.[/dim]")
    if res.events_verified > 0 and not res.sequence_gaps:
        console.print(
            "[dim]Note: Tail truncation (deleting last seq) is not detectable without external anchor — export header stores last_seq/last_chain for manual compare.[/dim]"
        )
        console.print("")
    else:
        console.print("")


def _render_tamper(res: VerifyResultDto) -> None:
    where = f"Seq {res.first_mismatch_seq} · {res.mismatch_type}"
    render_key_value_grid(
        "Audit Verify — ✗ TAMPER DETECTED",
        [
            ("Where", where),
            ("What", _what_text(res.mismatch_type)),
            ("Type", res.mismatch_type or "-"),
            (
                "Expected",
                (res.expected_signature or res.expected_payload_hash or res.expected_chain_hash or "-")[:64],
            ),
            (
                "Actual",
                (res.actual_signature or res.actual_payload_hash or res.actual_chain_hash or "-")[:64],
            ),
            ("Checked", f"{res.events_verified} events OK, failing at {res.first_mismatch_seq}"),
            ("Gaps", ", ".join(str(g) for g in res.sequence_gaps) if res.sequence_gaps else "None"),
            ("Result", Text("✗ Ledger broken. Do NOT trust events ≥ mismatch.", style=THEME_TOKENS["danger"])),
            (
                "Action",
                "→ Restore audit_events from backup. Run `audit export --out evidence.jsonl` to preserve chain.",
            ),
        ],
    )


def render_verify_result(res: VerifyResultDto, anchor: str | None = None) -> None:
    if res.is_valid:
        _render_valid(res, anchor)
        return
    _render_tamper(res)
