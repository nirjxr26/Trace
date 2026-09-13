"""Audit renderers."""

from typing import Any

from rich.text import Text

from trace_core.audit.dto import AuditEventDto, VerifyResultDto
from trace_core.core.ui.renderers import (
    format_india_datetime,
    get_status_style_and_label,
    render_key_value_grid,
    render_minimalist_table,
)
from trace_core.core.ui.theme import THEME_TOKENS


def _time_compact(ts: Any) -> str:
    from trace_core.core.ui.renderers import format_india_table_time

    try:
        return format_india_table_time(ts)  # type: ignore[arg-type]
    except Exception:
        return format_india_datetime(ts)  # type: ignore[arg-type]


def render_audit_table(events: list[AuditEventDto]) -> None:
    cols: list[tuple[str, dict[str, Any]]] = [
        ("  Seq", {"style": THEME_TOKENS["accent"], "no_wrap": True}),
        ("Action", {"style": THEME_TOKENS["value"], "no_wrap": True}),
        ("Case #", {"style": THEME_TOKENS["label"], "no_wrap": True}),
        ("Actor", {"style": THEME_TOKENS["muted"], "no_wrap": True}),
        ("Time", {"style": THEME_TOKENS["muted"], "no_wrap": True}),
    ]
    rows: list[list[Any]] = []
    for e in events:
        _, style, _ = get_status_style_and_label(e.action, False)
        rows.append(
            [
                f"  {e.seq}",
                Text(e.action.value, style=style),
                e.subject_case_number,
                e.actor,
                _time_compact(e.ts),
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
        console.print(f"[dim]Chain: ✓ VALID · SHA-256 · {len(events)} events · {cases} cases, {actors} actors[/dim]\n")


def render_case_audit_header(case_number: str, title: str, status: str, events: list[AuditEventDto]) -> None:
    if not events:
        return
    from trace_core.core.ui.renderers import console, get_rule_char
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    rule = get_rule_char() * 66
    console.print("")
    console.print(Text(f"  CASE {case_number}", style=TOK["title"]))
    if title:
        console.print(Text(f"  {title}", style=TOK["value"]))
    created = _time_compact(events[-1].ts)
    last = _time_compact(events[0].ts)
    console.print(
        Text(f"  Status: {status} · Events: {len(events)} · Created: {created} · Last: {last}", style=TOK["muted"])
    )
    console.print(Text("  Chain ✓ VALID", style=TOK["success"]))
    console.print(Text(f"  {rule}", style=TOK["border"]))
    console.print("")


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
    from trace_core.audit.events import parse_details
    from trace_core.core.ui.renderers import console, get_rule_char
    from trace_core.core.ui.theme import THEME_TOKENS as TOK

    if not events:
        return
    rule = get_rule_char() * 66
    console.print(Text(f"  {rule}", style=TOK["border"]))
    for e in events:
        details = parse_details(e.payload_json)
        time_str = _time_compact(e.ts)
        label = e.action.value.replace("CASE_", "").title()
        summary = _timeline_summary(e, details)
        console.print(f"  {time_str}  {label}")
        console.print(f"           {e.subject_case_number} · {e.actor}")
        if summary:
            console.print(f"           {summary}")
        console.print("")
    console.print(Text(f"  {rule}", style=TOK["border"]))
    console.print(f"[dim] {len(events)} shown · newest first[/dim]\n")


def render_audit_detail(e: AuditEventDto) -> None:

    from trace_core.audit.events import parse_details
    from trace_core.core.ui.renderers import render_dossier

    details = parse_details(e.payload_json)
    how = _how_text(details)
    utc_display = _utc_display(e.ts)
    fields = _detail_fields(e, details, utc_display, how)
    sections = _detail_sections(e, details)
    render_dossier(
        header_prefix="AUDIT",
        identifier=f"#{e.seq}",
        title=e.action.value,
        subtitle=f"{e.subject_case_number} · {format_india_datetime(e.ts)}",
        status_badge=None,
        fields=fields,
        sections=sections,
    )
    from trace_core.core.ui.renderers import console

    console.print("[dim]Tip: double-click seq/hash to copy · [c] Copy[/dim]\n")


def _how_text(details: dict) -> str:
    cmd = details.get("command") or "-"
    ver = details.get("trace_version") or "-"
    if ver == "-":
        return cmd
    if cmd != "-":
        return f"{cmd} · v{ver}"
    return f"v{ver}"


def _utc_display(ts: Any) -> str:
    try:
        from datetime import UTC

        return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ts)


def _detail_fields(e: AuditEventDto, details: dict, utc_display: str, how: str) -> list[tuple[str, Any]]:
    host = details.get("host") or "-"
    reason = details.get("reason", "")
    changed = details.get("changed", [])
    return [
        ("Who", f"{e.actor} @ {host}"),
        ("When", f"{format_india_datetime(e.ts)} ({utc_display})"),
        ("Where", f"{e.subject_case_number}" + (f" ({e.subject_case_id})" if e.subject_case_id else "")),
        ("What", f"{e.action.value}" + (f" · changed: {', '.join(changed)}" if changed else "")),
        ("Why", reason or "—"),
        ("How", how),
    ]


def _detail_sections(e: AuditEventDto, details: dict) -> list[tuple[str, str | None]]:
    import json

    before = details.get("before", {})
    after = details.get("after", {})
    sections: list[tuple[str, str | None]] = []
    if before or after:
        sections.append(("Before", json.dumps(before, indent=2, ensure_ascii=False) if before else None))
        sections.append(("After", json.dumps(after, indent=2, ensure_ascii=False) if after else None))
    sections.append(("Payload Hash", e.payload_hash))
    sections.append(("Prev Chain", e.prev_chain))
    sections.append(("Chain Hash", e.chain_hash))
    return sections


def _what_text(mismatch_type: str | None) -> str:
    if mismatch_type == "payload_hash":
        return "payload_json edited but payload_hash not updated"
    if mismatch_type == "prev_chain":
        return "prev_chain linkage broken"
    return "chain_hash mismatch"


def _render_valid(res: VerifyResultDto) -> None:
    from trace_core.core.ui.renderers import console

    gaps_str = ", ".join(str(g) for g in res.sequence_gaps) if res.sequence_gaps else "None"
    note = " (rolled-back, not tampering)" if res.sequence_gaps else ""
    render_key_value_grid(
        "Audit Verify — ✓ VALID",
        [
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
            ("Result", Text("✓ No tampering. Ledger intact.", style=THEME_TOKENS["success"])),
        ],
    )
    console.print("[dim]Tip: export with `audit export --out bundle.jsonl` to preserve chain.[/dim]")
    if res.events_verified > 0 and not res.sequence_gaps:
        console.print(
            "[dim]Note: Tail truncation (deleting last seq) is not detectable without external anchor — export header stores last_seq/last_chain for manual compare.[/dim]\n"
        )
    else:
        console.print()


def _render_tamper(res: VerifyResultDto) -> None:
    where = f"Seq {res.first_mismatch_seq} · {res.mismatch_type}"
    render_key_value_grid(
        "Audit Verify — ✗ TAMPER DETECTED",
        [
            ("Where", where),
            ("What", _what_text(res.mismatch_type)),
            ("Type", res.mismatch_type or "-"),
            ("Expected", (res.expected_payload_hash or res.expected_chain_hash or "-")[:64]),
            ("Actual", (res.actual_payload_hash or res.actual_chain_hash or "-")[:64]),
            ("Checked", f"{res.events_verified} events OK, failing at {res.first_mismatch_seq}"),
            ("Gaps", ", ".join(str(g) for g in res.sequence_gaps) if res.sequence_gaps else "None"),
            ("Result", Text("✗ Ledger broken. Do NOT trust events ≥ mismatch.", style=THEME_TOKENS["danger"])),
            (
                "Action",
                "→ Restore audit_events from backup. Run `audit export --out evidence.jsonl` to preserve chain.",
            ),
        ],
    )


def render_verify_result(res: VerifyResultDto) -> None:
    if res.is_valid:
        _render_valid(res)
        return
    _render_tamper(res)
