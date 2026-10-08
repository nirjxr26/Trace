"""Shared audit CLI helpers: seq fetch + case header."""

from pathlib import Path

from rich.markup import escape

from trace_core.audit.dto import AuditEventSummaryDto, AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.core.errors import ApplicationError, ValidationError

_EMPTY_TIMELINE_HINT = "Try --action CASE_CREATED."


def _empty_timeline_notice(case_number: str) -> None:
    """Empty-ledger notice shared by list and timeline views."""
    from trace_core.core.ui.renderers import console

    console.print(f"[dim]No events for {escape(case_number)}. {_EMPTY_TIMELINE_HINT}[/dim]\n")


def check_export_dest(out: str, force: bool) -> Path:
    """Refuse to clobber an existing bundle without --force. Single source for CLI surfaces."""
    path = Path(out)
    if path.exists() and not force:
        raise ValidationError(f"Refusing to overwrite existing file: {out} (use --force)")
    return path


def prompt_passphrase(confirm: bool = False) -> str:
    """Passphrase from env (non-interactive) or hidden prompt. Never a CLI arg (process list)."""
    import os

    import typer

    env = os.environ.get("TRACE_EXPORT_PASSPHRASE", "")
    if env:
        return env
    value = typer.prompt("Export passphrase", hide_input=True, confirmation_prompt=confirm)
    if not value:
        raise ValidationError("A non-empty passphrase is required for encrypted export.")
    return value


def report_written(path: Path, message: str) -> None:
    """Success line plus the written path. Single source for the export/decrypt tails."""
    from trace_core.core.ui.renderers import console, render_success

    render_success(message)
    console.print(f"[dim]{path}[/dim]")


def do_export_encrypted(svc: AuditService, out: str, passphrase: str) -> Path:  # type: ignore[no-untyped-def]
    """Export, seal with the passphrase, and atomically replace the target. Temp never survives."""
    from trace_core.audit.vault import encrypt_bytes
    from trace_core.core.fs import atomic_write_lines

    tmp = Path(out).with_suffix(Path(out).suffix + ".plain-tmp")
    try:
        svc.export(str(tmp))
        sealed = encrypt_bytes(tmp.read_bytes(), passphrase)
        return atomic_write_lines(out, [sealed.decode("ascii")])
    finally:
        tmp.unlink(missing_ok=True)


def do_decrypt(in_path: str, out: str, passphrase: str) -> Path:  # type: ignore[no-untyped-def]
    """Open a sealed bundle to a file. Destination honors the clobber guard upstream."""
    from trace_core.audit.vault import decrypt_bytes
    from trace_core.core.fs import atomic_write_lines

    plain = decrypt_bytes(Path(in_path).read_bytes(), passphrase)
    return atomic_write_lines(out, [plain.decode("utf-8")])


_PAGE_PROMPT = "  [Enter] older  [b] back  [q] quit"


def _is_interactive() -> bool:
    from trace_core.core.cli.args import interactive_terminal

    return interactive_terminal()


def _page_choice() -> str:
    from trace_core.core.ui.renderers import console

    try:
        answer = console.input(f"[dim]{_PAGE_PROMPT}[/dim] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"
    return answer or "enter"


_QUIT_CHOICES = ("q", "quit", "n", "no")
_BACK_CHOICES = ("b", "back", "p", "up")


def _render_page(
    svc: AuditService, filt: AuditFilterDto, cursor: tuple[int | None, int | None]
) -> tuple[list[AuditEventSummaryDto], bool]:  # type: ignore[no-untyped-def]
    """Render one window and report whether the ledger continues past it."""
    from trace_core.audit.renderers import render_audit_table

    before, after = cursor
    page = filt.model_copy(update={"before_seq": before, "after_seq": after, "offset": 0, "limit": filt.limit + 1})
    fetched = svc.list_event_summaries(page)
    rows = fetched[: filt.limit]
    render_audit_table(rows)
    return rows, len(fetched) > filt.limit


def _next_page_hint(filt: AuditFilterDto, cursor: tuple[int | None, int | None], rows: list) -> str:  # type: ignore[no-untyped-def]
    before, _after = cursor
    if before is None:
        return f"More events: audit show --offset {filt.offset + filt.limit}"
    return f"More events: audit show --before-seq {rows[-1].seq}"


def _prompt_for_cursor(
    cursor: tuple[int | None, int | None],
    rows: list,  # type: ignore[no-untyped-def]
    visited: list[tuple[int | None, int | None]],
) -> tuple[int | None, int | None] | None:
    """Next cursor for the window to show, or None to stop. Re-prompts on a no-op."""
    from trace_core.core.ui.renderers import console

    while True:
        choice = _page_choice()
        if choice in _QUIT_CHOICES:
            return None
        if choice not in _BACK_CHOICES:
            visited.append(cursor)
            return rows[-1].seq, None
        if not visited:
            console.print("[dim]Already at the newest event.[/dim]")
            continue
        return visited.pop()


def _paged_list(svc: AuditService, filt: AuditFilterDto, interactive: bool) -> None:  # type: ignore[no-untyped-def]
    """Walk the ledger one fixed window at a time. Never holds more than one page."""
    from trace_core.core.ui.renderers import console

    interactive = interactive and _is_interactive()
    cursor: tuple[int | None, int | None] = (filt.before_seq, filt.after_seq)
    visited: list[tuple[int | None, int | None]] = []
    while True:
        rows, more = _render_page(svc, filt, cursor)
        if not more:
            return
        if not interactive:
            console.print(f"[dim]{_next_page_hint(filt, cursor, rows)}[/dim]\n")
            return
        nxt = _prompt_for_cursor(cursor, rows, visited)
        if nxt is None:
            return
        cursor = nxt


def do_show_list(
    svc: AuditService, filt: AuditFilterDto, case_number: str | None, output: str, pager: bool = False
) -> None:
    """List + timeline + render core shared by Typer and shell. Callers own capture/parse UI."""
    from trace_core.audit.renderers import render_events

    json_output = output.lower() == "json"
    if not case_number and not json_output:
        _paged_list(svc, filt, pager)
        return
    events = svc.list_events(filt)
    if render_case_timeline_view(svc, case_number, events, output):
        return
    if not events and case_number and not json_output:
        _empty_timeline_notice(case_number)
        return
    render_events(events, output)


def do_verify(svc: AuditService, output: str, anchor: str | None):  # type: ignore[no-untyped-def]
    """Verify + anchor + render core shared by Typer and shell. Enforces the Tamper policy itself.

    The policy lives here rather than in each surface because a caller that forgets to
    inspect the result reports a broken chain as valid, which is the one answer the
    ledger must never give.
    """
    from trace_core.audit.anchor import verify_against_anchor
    from trace_core.audit.renderers import render_verify
    from trace_core.core.errors import AuditTamperError

    res = svc.verify()
    verify_against_anchor(svc, res, anchor)
    render_verify(res, output, anchor)
    if not res.is_valid:
        raise AuditTamperError(f"Tamper detected at seq {res.first_mismatch_seq} ({res.mismatch_type})")
    return res


def fetch_case_with_history(case_svc, identifier: str, limit: int = 6):  # type: ignore[no-untyped-def]
    """Case + recent audit events shared by Typer show and shell show. Events None on ledger miss."""
    from trace_core.core.ui.renderers import console

    case = case_svc.get_case(identifier)
    try:
        events = AuditService(case_svc.session_manager).list_events(
            AuditFilterDto(case_number=case.number, limit=limit)
        )
    except ApplicationError as e:
        # Ledger down (e.g. "run trace db migrate") must not look like "no history";
        # the fetch owns the message. Domain bugs (TypeError etc.) still raise.
        console.print(f"[dim]Audit history unavailable — {e}[/dim]\n")
        events = None
    return case, events


def show_seq_view(svc: AuditService, seq: int, output: str) -> bool:  # type: ignore[no-untyped-def]
    from trace_core.audit.renderers import render_event
    from trace_core.core.ui.renderers import render_error_card

    e = svc.get_by_seq(seq)
    if not e:
        render_error_card("Not Found", f"Audit event seq {seq} does not exist.")
        return False
    render_event(e, output)
    return True


def render_case_timeline_view(svc: AuditService, case_number: str | None, events, output: str) -> bool:  # type: ignore[no-untyped-def]
    """Single source for per-case audit header + timeline. Returns True when handled."""
    if not case_number or output.lower() == "json":
        return False
    from trace_core.audit.renderers import render_audit_timeline, render_case_audit_header
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import NotFoundError

    try:
        case = CaseService(svc.session_manager).get_case(case_number)
    except NotFoundError:
        return False
    render_case_audit_header(case.number, case.title, case.status.value, events)
    if not events:
        _empty_timeline_notice(case_number)
        return True
    render_audit_timeline(events)
    return True
