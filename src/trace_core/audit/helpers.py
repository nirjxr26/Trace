"""Shared audit CLI helpers: seq fetch + case header."""

from pathlib import Path

from rich.markup import escape

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.core.errors import ValidationError

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


def do_export_encrypted(svc: AuditService, out: str, passphrase: str) -> Path:  # type: ignore[no-untyped-def]
    """Export, seal with the passphrase, and atomically replace the target. Temp never survives."""
    from trace_core.audit.vault import encrypt_bytes
    from trace_core.core.fs import atomic_write_lines

    tmp = Path(out).with_suffix(Path(out).suffix + ".plain-tmp")
    try:
        do_export(svc, str(tmp))
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


def do_show_list(svc: AuditService, filt: AuditFilterDto, case_number: str | None, output: str) -> None:
    """List + timeline + render core shared by Typer and shell. Callers own capture/parse UI."""
    from trace_core.audit.renderers import render_events

    events = svc.list_events(filt)
    if render_case_timeline_view(svc, case_number, events, output):
        return
    if not events and case_number and output.lower() != "json":
        _empty_timeline_notice(case_number)
        return
    render_events(events, output)


def do_verify(svc: AuditService, output: str, anchor: str | None):  # type: ignore[no-untyped-def]
    """Verify + anchor + render core shared by Typer and shell. Returns result; callers own Tamper policy."""
    from trace_core.audit.anchor import verify_against_anchor
    from trace_core.audit.renderers import render_verify

    res = svc.verify()
    verify_against_anchor(svc, res, anchor)
    render_verify(res, output, anchor)
    return res


def do_export(svc: AuditService, out: str):  # type: ignore[no-untyped-def]
    """Export core shared by Typer and shell. Returns path; callers own messaging."""
    return svc.export(out)


def fetch_case_with_history(case_svc, identifier: str, limit: int = 6):  # type: ignore[no-untyped-def]
    """Case + recent audit events shared by Typer show and shell show. Events None on ledger miss."""
    from trace_core.core.ui.renderers import console

    case = case_svc.get_case(identifier)
    try:
        events = AuditService(case_svc.session_manager).list_events(
            AuditFilterDto(case_number=case.number, limit=limit)
        )
    except Exception:
        # A ledger failure must not look like "no history": say so once, here,
        # where the fetch (not the renderer) owns the error.
        console.print("[dim]Audit history unavailable — ledger error; showing case without history.[/dim]\n")
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
