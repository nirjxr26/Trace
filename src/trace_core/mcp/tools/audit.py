from typing import Annotated, Any

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from trace_core.audit.domain import AuditAction
from trace_core.audit.dto import AuditFilterDto
from trace_core.audit.service import AuditService
from trace_core.mcp import services
from trace_core.mcp.constants import (
    TOOL_AUDIT_DECRYPT,
    TOOL_AUDIT_EXPORT,
    TOOL_AUDIT_GET,
    TOOL_AUDIT_KEYS_INIT,
    TOOL_AUDIT_KEYS_LIST,
    TOOL_AUDIT_KEYS_ROTATE,
    TOOL_AUDIT_LIST,
    TOOL_AUDIT_VERIFY,
)
from trace_core.mcp.schemas import (
    AuditDecryptArgs,
    AuditExportArgs,
    KeyArgs,
    KeyRotateArgs,
    checked,
)
from trace_core.mcp.serialize import to_result
from trace_core.mcp.server import ServerContext, execute, mcp_tool
from trace_core.mcp.tools import DESTRUCTIVE, READ_ONLY, WRITE

Limit = Annotated[int, Field(ge=1, le=200)]
Offset = Annotated[int, Field(ge=0)]
Seq = Annotated[int, Field(ge=1)]
Detail = Annotated[str, Field(pattern="^(summary|full)$")]
ShortText = Annotated[str | None, Field(max_length=255)]
Search = Annotated[str | None, Field(max_length=200)]


def register(server: MCPServer, ctx: ServerContext) -> None:
    @mcp_tool(server, TOOL_AUDIT_LIST, annotations=READ_ONLY, description="List audit ledger events.")
    def trace_audit_list(
        case_number: ShortText = None,
        action: AuditAction | None = None,
        actor: ShortText = None,
        device_serial: ShortText = None,
        search: Search = None,
        before_seq: Seq | None = None,
        after_seq: Seq | None = None,
        detail: Detail = "summary",
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> dict:
        return execute(
            ctx,
            TOOL_AUDIT_LIST,
            lambda: _list(
                ctx,
                case_number,
                action,
                actor,
                device_serial,
                search,
                before_seq,
                after_seq,
                detail,
                limit,
                offset,
            ),
        )

    @mcp_tool(server, TOOL_AUDIT_GET, annotations=READ_ONLY, description="Get one audit event by sequence number.")
    def trace_audit_get(seq: Seq) -> dict:
        return execute(ctx, TOOL_AUDIT_GET, lambda: _get(ctx, seq))

    @mcp_tool(server, TOOL_AUDIT_VERIFY, annotations=READ_ONLY, description="Verify the audit ledger hash chain.")
    async def trace_audit_verify(mcp_ctx: Context) -> dict:
        await mcp_ctx.report_progress(0, None, "Scanning ledger")

        async def report(count: int) -> None:
            await mcp_ctx.report_progress(count, None, f"Verified {count} events")

        def progress(count: int) -> None:
            anyio.from_thread.run(report, count)

        def work() -> Any:
            return execute(ctx, TOOL_AUDIT_VERIFY, lambda: _verify(ctx, progress))

        payload = await anyio.to_thread.run_sync(work)
        message = "Verification failed" if payload.is_error else "Verified"
        await mcp_ctx.report_progress(payload.structured_content.get("events_verified", 0), None, message)
        return payload

    @mcp_tool(
        server,
        TOOL_AUDIT_EXPORT,
        annotations=WRITE,
        description="Export a signed JSONL ledger bundle to the configured export directory.",
    )
    def trace_audit_export(
        filename: Annotated[str, Field(min_length=1, max_length=128)],
        encrypt: bool = False,
        overwrite: bool = False,
        confirm: Annotated[str | None, Field(max_length=64)] = None,
    ) -> dict:
        return execute(ctx, TOOL_AUDIT_EXPORT, lambda: _export(ctx, filename, encrypt, overwrite, confirm))

    @mcp_tool(
        server,
        TOOL_AUDIT_DECRYPT,
        annotations=WRITE,
        description="Decrypt a sealed ledger bundle from the configured export directory.",
    )
    def trace_audit_decrypt(
        filename: Annotated[str, Field(min_length=1, max_length=128)],
        overwrite: bool = False,
        confirm: Annotated[str | None, Field(max_length=64)] = None,
    ) -> dict:
        return execute(ctx, TOOL_AUDIT_DECRYPT, lambda: _decrypt(ctx, filename, overwrite, confirm))

    @mcp_tool(
        server,
        TOOL_AUDIT_KEYS_INIT,
        annotations=DESTRUCTIVE,
        description="Create and activate an Ed25519 signing key. Admin only.",
    )
    def trace_audit_keys_init(label: Annotated[str, Field(min_length=1, max_length=64)] = "default") -> dict:
        return execute(ctx, TOOL_AUDIT_KEYS_INIT, lambda: _keys_init(ctx, label))

    @mcp_tool(
        server,
        TOOL_AUDIT_KEYS_ROTATE,
        annotations=DESTRUCTIVE,
        description="Rotate the signing key after confirming the active key id. Admin only.",
    )
    def trace_audit_keys_rotate(
        label: Annotated[str, Field(min_length=1, max_length=64)] = "default",
        confirm: Annotated[str, Field(min_length=1, max_length=128)] = "",
    ) -> dict:
        return execute(ctx, TOOL_AUDIT_KEYS_ROTATE, lambda: _keys_rotate(ctx, label, confirm))

    @mcp_tool(
        server, TOOL_AUDIT_KEYS_LIST, annotations=READ_ONLY, description="List public signing keys and their status."
    )
    def trace_audit_keys_list() -> dict:
        return execute(ctx, TOOL_AUDIT_KEYS_LIST, lambda: _keys_list())


def _list(
    ctx: ServerContext,
    case_number: str | None,
    action: AuditAction | None,
    actor: str | None,
    device_serial: str | None,
    search: str | None,
    before_seq: int | None,
    after_seq: int | None,
    detail: str,
    limit: int,
    offset: int,
) -> dict:
    filter_dto = AuditFilterDto(
        case_number=case_number,
        action=action,
        actor=actor,
        device_serial=device_serial,
        search=search,
        before_seq=before_seq,
        after_seq=after_seq,
        limit=limit,
        offset=offset,
    )
    service = AuditService(ctx.session_manager)
    items = service.list_events(filter_dto) if detail == "full" else service.list_event_summaries(filter_dto)
    return to_result(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "pagination": {"limit": limit, "offset": offset, "returned": len(items)},
        }
    )


def _get(ctx: ServerContext, seq: int) -> dict:
    return to_result(AuditService(ctx.session_manager).get_by_seq(seq).model_dump(mode="json"))


def _verify(ctx: ServerContext, on_progress=None) -> dict:  # type: ignore[no-untyped-def]
    return to_result(AuditService(ctx.session_manager).verify(on_progress=on_progress).model_dump(mode="json"))


def _export(ctx: ServerContext, filename: str, encrypt: bool, overwrite: bool, confirm: str | None) -> dict:
    checked(AuditExportArgs, {"filename": filename, "encrypt": encrypt, "overwrite": overwrite, "confirm": confirm})
    return to_result(services.export_bundle(ctx.session_manager, filename, encrypt, overwrite))


def _decrypt(ctx: ServerContext, filename: str, overwrite: bool, confirm: str | None) -> dict:
    checked(AuditDecryptArgs, {"filename": filename, "overwrite": overwrite, "confirm": confirm})
    return to_result(services.decrypt_bundle(filename, overwrite))


def _keys_init(ctx: ServerContext, label: str) -> dict:
    checked(KeyArgs, {"label": label})
    return to_result(services.keys_init(ctx.session_manager, label))


def _keys_rotate(ctx: ServerContext, label: str, confirm: str) -> dict:
    checked(KeyRotateArgs, {"label": label, "confirm": confirm})
    return to_result(services.keys_rotate(ctx.session_manager, label, confirm))


def _keys_list() -> dict:
    return to_result(services.keys_list())
