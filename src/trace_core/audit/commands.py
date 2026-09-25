"""Typer CLI for audit ledger."""

import typer

from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.database.session import DatabaseSessionManager, db_manager
from trace_core.core.errors import AuditTamperError
from trace_core.core.ui.renderers import console, render_error_card, render_success

audit_app = typer.Typer(name="audit", help="Inspect, verify, and export tamper-evident audit ledger.")


def _get_service(mgr: DatabaseSessionManager | None = None) -> AuditService:
    return AuditService(mgr or db_manager)


def _parse_action(action: str | None):  # type: ignore[no-untyped-def]
    from trace_core.audit.domain import AuditAction
    from trace_core.core.domain import parse_enum_value

    act = parse_enum_value(AuditAction, action)
    if action and act is None:
        valid = ", ".join(a.value for a in AuditAction)
        render_error_card("Invalid Action", f"Unknown action '{action}'.", f"Valid actions: {valid}.")
        raise typer.Exit(1)
    return act


def _show_list(
    svc: AuditService,
    case_number: str | None,
    action: str | None,
    actor: str | None,
    search: str | None,
    limit: int,
    offset: int,
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
    )
    from trace_core.audit.helpers import do_show_list

    do_show_list(svc, f, case_number, output)


@audit_app.command("show")
def audit_show(
    case_number: str = typer.Option(None, "--case", help="Filter by case number"),
    action: str = typer.Option(None, "--action", help="Filter by action"),
    actor: str = typer.Option(None, "--actor", help="Filter by actor (substring)"),
    search: str = typer.Option(None, "--search", "-q", help="Search actor/action/case"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    limit: int = typer.Option(50, "--limit", help="Max rows (1..500)"),
    offset: int = typer.Option(0, "--offset", help="Offset"),
    seq: int = typer.Option(None, "--seq", help="Show single event by seq (detailed 5W1H)"),
) -> None:
    with capture_cli_errors("Audit Show"):
        from trace_core.audit.helpers import show_seq_view

        svc = _get_service()
        if seq is not None:
            if not show_seq_view(svc, seq, output):
                raise typer.Exit(1)
            return
        _show_list(svc, case_number, action, actor, search, limit, offset, output)


@audit_app.command("verify")
def audit_verify(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
    anchor: str = typer.Option(None, "--anchor", help="Anchor JSON file to verify tail against"),
) -> None:
    with capture_cli_errors("Audit Verify"):
        from trace_core.audit.helpers import do_verify

        svc = _get_service()
        res = do_verify(svc, output, anchor)
        if not res.is_valid:
            raise AuditTamperError(f"Tamper detected at seq {res.first_mismatch_seq} ({res.mismatch_type})")


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
            raise typer.Exit(1)
        svc = _get_service()
        from trace_core.audit.helpers import check_export_dest, do_export, do_export_encrypted, prompt_passphrase

        check_export_dest(out, force)
        if encrypt:
            path = do_export_encrypted(svc, out, prompt_passphrase(confirm=True))
        else:
            path = do_export(svc, out)
        render_success("Audit bundle exported.")
        console.print(f"[dim]{path}[/dim]")


@audit_app.command("decrypt")
def audit_decrypt(
    inp: str = typer.Option(..., "--in", help="Sealed bundle file path"),
    out: str = typer.Option(..., "--out", help="Output JSONL file path"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file"),
) -> None:
    with capture_cli_errors("Audit Decrypt"):
        from trace_core.audit.helpers import check_export_dest, do_decrypt, prompt_passphrase

        check_export_dest(out, force)
        path = do_decrypt(inp, out, prompt_passphrase())
        render_success("Bundle decrypted.")
        console.print(f"[dim]{path}[/dim]")


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
def audit_keys_list(output: str = typer.Option("table", "--output", "-o", help="table|json")) -> None:
    """List keystore public keys. No private material is ever displayed."""
    with capture_cli_errors("Key Listing Failed"):
        from trace_core.audit.signing import list_keys
        from trace_core.core.ui.renderers import render_json, render_minimalist_table

        keys = list_keys()
        if output.lower() == "json":
            render_json(keys)
            return
        render_minimalist_table(
            "Signing Keys",
            [
                ("Key ID", {"style": "bold", "no_wrap": True}),
                ("Status", {"no_wrap": True, "max_width": 10}),
                ("Public Key", {"overflow": "ellipsis"}),
            ],
            [[k["key_id"], k["status"], k["public_key"]] for k in keys],
            empty_message="No signing keys. The HMAC envelope is active.",
        )
