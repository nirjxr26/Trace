"""Typer CLI for audit ledger."""

import typer

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.exit_codes import EXIT_ERROR
from trace_core.core.cli.output import OUTPUT_HELP
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import render_error_card, render_output, render_success

audit_app = typer.Typer(name="audit", help="Inspect, verify, and export tamper-evident audit ledger.")


def _get_service(mgr: DatabaseSessionManager | None = None) -> AuditService:
    """Service factory. BaseService.__init__ already falls back to the global db_manager."""
    return AuditService(mgr)


def _parse_action(action: str | None):  # type: ignore[no-untyped-def]
    from trace_core.audit.domain import AuditAction
    from trace_core.core.domain import parse_enum_value

    act = parse_enum_value(AuditAction, action)
    if action and act is None:
        valid = ", ".join(a.value for a in AuditAction)
        render_error_card("Invalid Action", f"Unknown action '{action}'.", f"Valid actions: {valid}.")
        raise typer.Exit(EXIT_ERROR)
    return act


def _show_list(
    svc: AuditService,
    case_number: str | None,
    action: str | None,
    actor: str | None,
    search: str | None,
    limit: int,
    offset: int,
    before_seq: int | None,
    after_seq: int | None,
    output: str,
) -> None:

    act = _parse_action(action)
    f = AuditFilterDto(
        case_number=case_number,
        action=act,
        actor=actor,
        search=search,
        limit=limit,
        offset=offset,
        before_seq=before_seq,
        after_seq=after_seq,
    )
    from trace_core.audit.helpers import do_show_list

    do_show_list(svc, f, case_number, output, pager=True)


@audit_app.command("show")
def audit_show(
    case_number: str = typer.Option(None, "--case", help="Filter by case number"),
    action: str = typer.Option(None, "--action", help="Filter by action"),
    actor: str = typer.Option(None, "--actor", help="Filter by actor (substring)"),
    search: str = typer.Option(None, "--search", "-q", help="Search actor/action/case, or exact seq"),
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
    limit: int = typer.Option(50, "--limit", help="Max rows (1..500)"),
    offset: int = typer.Option(0, "--offset", help="Offset"),
    before_seq: int = typer.Option(None, "--before-seq", help="Only events older than seq (deep paging)"),
    after_seq: int = typer.Option(None, "--after-seq", help="Only events newer than seq (paging back)"),
    seq: int = typer.Option(None, "--seq", help="Show single event by seq (detailed 5W1H)"),
) -> None:
    with capture_cli_errors("Audit Show"):
        from trace_core.audit.helpers import show_seq_view

        svc = _get_service()
        if seq is not None:
            if not show_seq_view(svc, seq, output):
                raise typer.Exit(EXIT_ERROR)
            return
        _show_list(svc, case_number, action, actor, search, limit, offset, before_seq, after_seq, output)


@audit_app.command("verify")
def audit_verify(
    output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP),
    anchor: str = typer.Option(None, "--anchor", help="Anchor JSON file to verify tail against"),
) -> None:
    with capture_cli_errors("Audit Verify"):
        from trace_core.audit.helpers import do_verify

        do_verify(_get_service(), output, anchor)


@audit_app.command("export")
def audit_export(
    out: str = typer.Option(..., "--out", help="Output JSONL file path"),
    fmt: str = typer.Option("jsonl", "--format", help="jsonl only in V1"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing bundle file"),
    encrypt: bool = typer.Option(False, "--encrypt", help="Seal with a passphrase (env/prompt, never argv)"),
) -> None:
    with capture_cli_errors("Audit Export"):
        if fmt.lower() != "jsonl":
            render_error_card("Invalid Format", f"Unknown format '{fmt}'.", "Expected: jsonl.")
            raise typer.Exit(EXIT_ERROR)
        svc = _get_service()
        from trace_core.audit.helpers import (
            check_export_dest,
            do_export_encrypted,
            prompt_passphrase,
            report_written,
        )

        check_export_dest(out, force)
        if encrypt:
            path = do_export_encrypted(svc, out, prompt_passphrase(confirm=True))
        else:
            path = svc.export(out)
        report_written(path, "Audit bundle exported.")


@audit_app.command("decrypt")
def audit_decrypt(
    inp: str = typer.Option(..., "--in", help="Sealed bundle file path"),
    out: str = typer.Option(..., "--out", help="Output JSONL file path"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file"),
) -> None:
    with capture_cli_errors("Audit Decrypt"):
        from trace_core.audit.helpers import check_export_dest, do_decrypt, prompt_passphrase, report_written

        check_export_dest(out, force)
        path = do_decrypt(inp, out, prompt_passphrase())
        report_written(path, "Bundle decrypted.")


@audit_app.command("keys-init")
def audit_keys_init(
    label: str = typer.Option("default", "--label", help="Human label recorded beside the key id"),
) -> None:
    """Generate an Ed25519 ledger signing key (0600 keystore) and select it."""
    with capture_cli_errors("Key Initialization Failed"):
        from trace_core.audit.signing import init_key
        from trace_core.core.operators import require_admin

        with _get_service().session_manager.session() as session:
            require_admin(session, action="manage signing keys")
        key_id = init_key(label)
        render_success(f"Signing key {key_id} created and selected.")


@audit_app.command("keys-rotate")
def audit_keys_rotate(
    label: str = typer.Option("default", "--label", help="Human label recorded beside the key id"),
) -> None:
    """Generate a successor signing key. Retired keys keep verifying old events."""
    with capture_cli_errors("Key Rotation Failed"):
        from trace_core.audit.signing import rotate_keys
        from trace_core.core.operators import require_admin

        with _get_service().session_manager.session() as session:
            require_admin(session, action="manage signing keys")
        key_id = rotate_keys(label)
        render_success(f"Rotated to signing key {key_id}. Old events still verify.")


@audit_app.command("keys-list")
def audit_keys_list(output: str = typer.Option("table", "--output", "-o", help=OUTPUT_HELP)) -> None:
    """List keystore public keys. No private material is ever displayed."""
    with capture_cli_errors("Key Listing Failed"):
        from trace_core.audit.signing import list_keys
        from trace_core.core.ui.renderers import render_minimalist_table

        keys = list_keys()
        render_output(
            output,
            keys,
            lambda: render_minimalist_table(
                "Signing Keys",
                [
                    ("Key ID", {"style": "bold", "no_wrap": True}),
                    ("Status", {"no_wrap": True, "max_width": 10}),
                    ("Public Key", {"overflow": "ellipsis"}),
                ],
                [[k["key_id"], k["status"], k["public_key"]] for k in keys],
                empty_message="No signing keys. The HMAC envelope is active.",
            ),
        )
