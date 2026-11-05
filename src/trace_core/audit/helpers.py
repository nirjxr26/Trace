"""Shared audit CLI helpers: seq fetch + case header."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from rich.markup import escape

from trace_core.audit.dto import AuditEventDto, AuditEventSummaryDto, AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.core.errors import ApplicationError, ValidationError

if TYPE_CHECKING:
    from trace_core.audit.renderers import DeviceAuditInfo

_EMPTY_TIMELINE_HINT = "Try --action CASE_CREATED."


def _empty_timeline_notice(case_number: str) -> None:
    """Empty-ledger notice shared by list and timeline views."""
    from trace_core.core.ui.renderers import console

    console.print(f"[dim]No events for {escape(case_number)}. {_EMPTY_TIMELINE_HINT}[/dim]\n")


SEALED_SUFFIX = ".sealed"


class BundleReceipt(NamedTuple):
    path: Path
    rows: int
    size_bytes: int
    sha256: str
    sealed: bool


def sealed_destination(out: str | Path) -> Path:
    path = Path(out)
    return path if path.name.endswith(SEALED_SUFFIX) else path.with_name(path.name + SEALED_SUFFIX)


def plain_destination(in_path: str | Path) -> Path:
    path = Path(in_path)
    if path.name.endswith(SEALED_SUFFIX):
        return path.with_name(path.name[: -len(SEALED_SUFFIX)])
    return path.with_name(path.name + ".jsonl")


def default_export_path(sealed: bool = False) -> Path:
    from datetime import UTC, datetime

    name = f"audit-{datetime.now(UTC).strftime('%Y-%m-%d-%H%M%S')}.jsonl"
    return sealed_destination(name) if sealed else Path(name)


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

    from trace_core.core.ui.renderers import console

    env = os.environ.get("TRACE_EXPORT_PASSPHRASE", "")
    if env:
        console.print("[dim]Using TRACE_EXPORT_PASSPHRASE[/dim]")
        return env
    value = typer.prompt("Export passphrase", hide_input=True, confirmation_prompt=confirm)
    if not value:
        raise ValidationError("A non-empty passphrase is required for encrypted export.")
    return value


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB"):
        value /= 1024.0
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"


def _bundle_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return max(sum(1 for line in handle if line.strip()) - 1, 0)


def _sha256(path: Path) -> str:
    import hashlib

    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _receipt(path: Path, *, sealed: bool, rows: int | None = None) -> BundleReceipt:
    return BundleReceipt(
        path=path,
        rows=_bundle_rows(path) if rows is None else rows,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
        sealed=sealed,
    )


def receipt_rows(receipt: BundleReceipt) -> list[tuple[str, str]]:
    return [
        ("File", str(receipt.path)),
        ("Size", _human_size(receipt.size_bytes)),
        ("Events", f"{receipt.rows:,}"),
        ("SHA-256", f"{receipt.sha256[:12]}…{receipt.sha256[-8:]}"),
        ("Sealed", "yes — passphrase required" if receipt.sealed else "no"),
    ]


def report_bundle(receipt: BundleReceipt, message: str, next_step: str = "") -> None:
    from trace_core.core.ui.renderers import console, render_success

    rows = receipt_rows(receipt)
    if next_step:
        rows.append(("Next", next_step))
    width = max(len(key) for key, _ in rows)
    render_success(message)
    for key, value in rows:
        console.print(f"[dim]{key:<{width}}[/dim]  {escape(value)}")
    console.print("")


def next_step_for(receipt: BundleReceipt) -> str:
    if receipt.sealed:
        return f"trace audit decrypt --in {receipt.path}"
    return "trace audit export --encrypt"


def do_export(svc: AuditService, out: str = "", passphrase: str | None = None, *, force: bool = False) -> BundleReceipt:  # type: ignore[no-untyped-def]
    from trace_core.audit.vault import encrypt_bytes
    from trace_core.core.fs import atomic_write_lines

    dest = out or str(default_export_path(bool(passphrase)))
    target = sealed_destination(dest) if passphrase else Path(dest)
    check_export_dest(str(target), force)

    if not passphrase:
        return _receipt(Path(svc.export(target)), sealed=False)

    tmp = target.with_name(target.name + ".plain-tmp")
    try:
        svc.export(str(tmp))
        rows = _bundle_rows(tmp)
        sealed = encrypt_bytes(tmp.read_bytes(), passphrase)
        atomic_write_lines(target, [sealed.decode("ascii")])
    finally:
        tmp.unlink(missing_ok=True)
    return _receipt(target, sealed=True, rows=rows)


def do_decrypt(in_path: str, out: str = "", passphrase: str = "", *, force: bool = False) -> BundleReceipt:
    """Open a sealed bundle to a file. Destination honors the clobber guard upstream."""
    from trace_core.audit.vault import decrypt_bytes
    from trace_core.core.fs import atomic_write_lines

    dest = out or str(plain_destination(in_path))
    check_export_dest(dest, force)
    plain = decrypt_bytes(Path(in_path).read_bytes(), passphrase)
    path = Path(atomic_write_lines(dest, [plain.decode("utf-8")]))
    return _receipt(path, sealed=False)


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


def enforce_verify_policy(res) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core.errors import ApplicationError, AuditTamperError

    if res.mismatch_type in ("signing_key", "insecure_key"):
        # The renderer already said this is a key problem, not tampering, and told the
        # operator not to restore from backup. Raising AuditTamperError here printed a
        # second card directly beneath it saying "Tamper detected... restore from
        # backup" — two adjacent conclusions, opposite advice, the destructive one last.
        if res.mismatch_type == "insecure_key":
            raise ApplicationError(
                "this ledger was signed with the shipped development key, so nothing can prove it was not edited"
            )
        raise ApplicationError("the signing key for this ledger isn't available, so signatures couldn't be checked")
    if not res.is_valid:
        raise AuditTamperError(f"Tamper detected at seq {res.first_mismatch_seq} ({res.mismatch_type})")


def _first_divergent_seq(head_seq: int, last_seq: int) -> int:
    if head_seq == last_seq:
        return head_seq
    return min(head_seq, last_seq) + 1


def bind_head_to_tail(session, res):  # type: ignore[no-untyped-def]
    """Cross-check the recorded chain head against the ledger tail and its signed tip."""
    if not res.is_valid:
        return res
    from sqlalchemy import select

    from trace_core.audit.domain import GENESIS_CHAIN
    from trace_core.audit.models import AuditChainStateModel, AuditEventModel
    from trace_core.audit.signing import verify_bytes
    from trace_core.core.canonical import canonical_json

    head = session.scalar(select(AuditChainStateModel).where(AuditChainStateModel.id == 1))
    head_seq = head.last_seq if head else 0
    head_chain = head.last_chain_hash if head else GENESIS_CHAIN
    last_seq = res.last_seq or 0
    tail_chain = GENESIS_CHAIN
    if last_seq:
        tail = session.get(AuditEventModel, last_seq)
        if tail is None:
            return res.model_copy(
                update={"is_valid": False, "mismatch_type": "chain_state", "first_mismatch_seq": last_seq}
            )
        tail_chain = tail.chain_hash
    if head_seq != last_seq or head_chain != tail_chain:
        first_bad = _first_divergent_seq(head_seq, last_seq)
        return res.model_copy(
            update={"is_valid": False, "mismatch_type": "chain_state", "first_mismatch_seq": first_bad}
        )
    if head is not None and head.tip_signature:
        message = canonical_json({"last_seq": head_seq, "last_chain": head_chain})
        if not verify_bytes(head.tip_key_id, message, head.tip_signature):
            return res.model_copy(
                update={"is_valid": False, "mismatch_type": "tip_signature", "first_mismatch_seq": head_seq}
            )
    return res


def do_verify(svc: AuditService, output: str, anchor: str | None):  # type: ignore[no-untyped-def]
    """Verify + anchor + render core shared by Typer and shell.

    The policy lives in `enforce_verify_policy` rather than in each surface because a
    caller that forgets to inspect the result reports a broken chain as valid, which is
    the one answer the ledger must never give.
    """
    from trace_core.audit.anchor import verify_against_anchor
    from trace_core.audit.renderers import render_verify

    res = svc.verify()
    verify_against_anchor(svc, res, anchor)
    render_verify(res, output, anchor)
    enforce_verify_policy(res)
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


def _device_identity(event: AuditEventDto, details: dict, record: Any) -> tuple[str, str | None]:
    from trace_core.devices.renderers import device_heading, display_node

    node = str(details["node"]) if details.get("node") else ""
    label = details.get("label")
    model = details.get("model") or (record.model if record is not None else None)
    capacity = details.get("capacity_bytes")
    if capacity is None and record is not None:
        capacity = record.capacity_bytes
    serial = details.get("serial") or event.subject_device_serial
    if serial is None and record is not None:
        serial = record.serial
    if label:
        name = str(label)
    elif node:
        name = device_heading(node, model, capacity) if (model or capacity) else display_node(node)
    elif serial:
        name = str(serial)
    else:
        name = ""
    return name, str(serial) if serial else None


def _node_link_context(
    svc: AuditService, event: AuditEventDto, node: str, cache: dict[str, list[Any]]
) -> tuple[str | None, str | None]:
    from trace_core.devices.helpers import do_node_links

    if not node:
        return None, event.subject_case_number
    if node not in cache:
        try:
            cache[node] = do_node_links(svc.session_manager, node)
        except ApplicationError:
            cache[node] = []
    links = cache[node]
    label = next((link.label for link in links if link.label), None)
    cases = ", ".join(link.case_number for link in links)
    return label, event.subject_case_number or (cases or None)


def device_audit_info(svc: AuditService, events: list[AuditEventDto]) -> dict[int, "DeviceAuditInfo"]:
    from trace_core.audit.events import parse_details
    from trace_core.audit.renderers import DeviceAuditInfo
    from trace_core.devices.helpers import do_observed_devices

    details_by_seq: dict[int, dict] = {}
    nodes: set[str] = set()
    for e in events:
        details = parse_details(e.payload_json)
        if not details:
            continue
        details_by_seq[e.seq] = details
        if details.get("node"):
            nodes.add(str(details["node"]))
    if not details_by_seq:
        return {}

    try:
        observed = do_observed_devices(svc.session_manager) if nodes else {}
    except ApplicationError:
        observed = {}

    links: dict[str, list[Any]] = {}
    info: dict[int, DeviceAuditInfo] = {}
    for e in events:
        details = details_by_seq.get(e.seq)
        if not details:
            continue
        node = str(details["node"]) if details.get("node") else ""
        name, serial = _device_identity(e, details, observed.get(node) if node else None)
        link_label, case_number = _node_link_context(svc, e, node, links)
        if link_label and not details.get("label"):
            name = str(link_label)
        if not name:
            continue
        info[e.seq] = DeviceAuditInfo(name=name, serial=serial, case_number=case_number)
    return info


def show_seq_view(svc: AuditService, seq: int, output: str) -> bool:  # type: ignore[no-untyped-def]
    from trace_core.audit.renderers import render_event
    from trace_core.core.ui.renderers import render_error_card

    e = svc.get_by_seq(seq)
    if not e:
        render_error_card("Not Found", f"Audit event seq {seq} does not exist.")
        return False
    render_event(e, output, device_audit_info(svc, [e]).get(e.seq))
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
    render_audit_timeline(events, device_audit_info(svc, events))
    return True
