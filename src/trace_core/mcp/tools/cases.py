from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from trace_core.cases.domain import CaseStatus
from trace_core.cases.dto import CaseCreateDto, CaseFilterDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.mcp.constants import (
    TOOL_CASE_ARCHIVE,
    TOOL_CASE_CLOSE,
    TOOL_CASE_CREATE,
    TOOL_CASE_GET,
    TOOL_CASE_LIST,
    TOOL_CASE_PURGE,
    TOOL_CASE_RESTORE,
    TOOL_CASE_REVIEW,
    TOOL_CASE_UPDATE,
)
from trace_core.mcp.schemas import (
    CaseCloseArgs,
    CaseCreateArgs,
    CaseDeleteArgs,
    CaseReviewArgs,
    CaseUpdateArgs,
    checked,
)
from trace_core.mcp.serialize import to_result
from trace_core.mcp.server import ServerContext, execute, mcp_tool
from trace_core.mcp.tools import DESTRUCTIVE, READ_ONLY, WRITE

Limit = Annotated[int, Field(ge=1, le=200)]
Offset = Annotated[int, Field(ge=0)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str | None, Field(max_length=255)]
Search = Annotated[str | None, Field(max_length=200)]
Reason = Annotated[str, Field(max_length=2000)]
Tags = Annotated[list[str] | None, Field(max_length=50)]


def register(server: MCPServer, ctx: ServerContext) -> None:
    @mcp_tool(server, TOOL_CASE_GET, annotations=READ_ONLY, description="Get one case by number or UUID.")
    def trace_case_get(identifier: Identifier) -> dict:
        return execute(ctx, TOOL_CASE_GET, lambda: _get(ctx, identifier))

    @mcp_tool(server, TOOL_CASE_LIST, annotations=READ_ONLY, description="List cases with filters and pagination.")
    def trace_case_list(
        status: CaseStatus | None = None,
        search: Search = None,
        include_deleted: bool = False,
        deleted_only: bool = False,
        recent: bool = False,
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> dict:
        return execute(
            ctx,
            TOOL_CASE_LIST,
            lambda: _list(ctx, status, search, include_deleted, deleted_only, recent, limit, offset),
        )

    @mcp_tool(server, TOOL_CASE_CREATE, annotations=WRITE, description="Create a case. Number is optional.")
    def trace_case_create(
        title: Identifier,
        lead_examiner: Identifier,
        number: ShortText = None,
        description: Annotated[str | None, Field(max_length=10000)] = None,
        notes: Annotated[str | None, Field(max_length=50000)] = None,
        tags: Tags = None,
        confirm: ShortText = None,
    ) -> dict:
        return execute(
            ctx,
            TOOL_CASE_CREATE,
            lambda: _create(ctx, title, lead_examiner, number, description, notes, tags, confirm),
        )

    @mcp_tool(server, TOOL_CASE_UPDATE, annotations=WRITE, description="Update mutable fields of an open case.")
    def trace_case_update(
        identifier: Identifier,
        title: ShortText = None,
        lead_examiner: ShortText = None,
        description: Annotated[str | None, Field(max_length=10000)] = None,
        notes: Annotated[str | None, Field(max_length=50000)] = None,
        tags: Tags = None,
        reason: Reason = "",
    ) -> dict:
        return execute(
            ctx,
            TOOL_CASE_UPDATE,
            lambda: _update(ctx, identifier, title, lead_examiner, description, notes, tags, reason),
        )

    @mcp_tool(server, TOOL_CASE_REVIEW, annotations=WRITE, description="Move a case under review or resume it.")
    def trace_case_review(identifier: Identifier, resume: bool = False, reason: Reason = "") -> dict:
        return execute(ctx, TOOL_CASE_REVIEW, lambda: _review(ctx, identifier, resume, reason))

    @mcp_tool(
        server,
        TOOL_CASE_CLOSE,
        annotations=DESTRUCTIVE,
        description="Permanently seal a case. Confirm by repeating the case identifier.",
    )
    def trace_case_close(
        identifier: Identifier, reason: Annotated[str, Field(min_length=1, max_length=2000)], confirm: Identifier
    ) -> dict:
        return execute(ctx, TOOL_CASE_CLOSE, lambda: _close(ctx, identifier, reason, confirm))

    @mcp_tool(
        server,
        TOOL_CASE_ARCHIVE,
        annotations=DESTRUCTIVE,
        description="Archive a case (soft delete). Confirm by repeating the case identifier.",
    )
    def trace_case_archive(identifier: Identifier, confirm: Identifier) -> dict:
        return execute(ctx, TOOL_CASE_ARCHIVE, lambda: _archive(ctx, identifier, confirm))

    @mcp_tool(
        server,
        TOOL_CASE_RESTORE,
        annotations=WRITE,
        description="Restore an archived case. Confirm by repeating the case identifier.",
    )
    def trace_case_restore(identifier: Identifier, confirm: Identifier) -> dict:
        return execute(ctx, TOOL_CASE_RESTORE, lambda: _restore(ctx, identifier, confirm))

    @mcp_tool(
        server,
        TOOL_CASE_PURGE,
        annotations=DESTRUCTIVE,
        description="Permanently purge an archived case. Admin only. Confirm by repeating the case identifier.",
    )
    def trace_case_purge(identifier: Identifier, confirm: Identifier) -> dict:
        return execute(ctx, TOOL_CASE_PURGE, lambda: _purge(ctx, identifier, confirm))


def _get(ctx: ServerContext, identifier: str) -> dict:
    dto = CaseService(ctx.session_manager).get_case(identifier)
    return to_result(dto.model_dump(mode="json"))


def _list(
    ctx: ServerContext,
    status: CaseStatus | None,
    search: str | None,
    include_deleted: bool,
    deleted_only: bool,
    recent: bool,
    limit: int,
    offset: int,
) -> dict:
    filter_dto = CaseFilterDto(
        status=status,
        search=search,
        include_deleted=include_deleted,
        deleted_only=deleted_only,
        recent=recent,
        limit=limit,
        offset=offset,
    )
    if recent:
        filter_dto = filter_dto.with_recent()
    items = CaseService(ctx.session_manager).list_cases(filter_dto)
    return to_result(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "pagination": {"limit": filter_dto.limit, "offset": filter_dto.offset, "returned": len(items)},
        }
    )


def _create(
    ctx: ServerContext,
    title: str,
    lead_examiner: str,
    number: str | None,
    description: str | None,
    notes: str | None,
    tags: list[str] | None,
    confirm: str | None,
) -> dict:
    args = checked(
        CaseCreateArgs,
        {
            "title": title,
            "lead_examiner": lead_examiner,
            "number": number,
            "description": description,
            "notes": notes,
            "tags": tags or [],
            "confirm": confirm,
        },
    )
    dto = CaseCreateDto(
        title=args.title,
        lead_examiner=args.lead_examiner,
        number=args.number,
        description=args.description,
        notes=args.notes,
        tags=args.tags,
    )
    created = CaseService(ctx.session_manager).create_case(dto)
    return to_result(created.model_dump(mode="json"))


def _update(
    ctx: ServerContext,
    identifier: str,
    title: str | None,
    lead_examiner: str | None,
    description: str | None,
    notes: str | None,
    tags: list[str] | None,
    reason: str,
) -> dict:
    checked(
        CaseUpdateArgs,
        {
            "identifier": identifier,
            "title": title,
            "lead_examiner": lead_examiner,
            "description": description,
            "notes": notes,
            "tags": tags,
            "reason": reason,
        },
    )
    dto = CaseUpdateDto(
        title=title,
        lead_examiner=lead_examiner,
        description=description,
        notes=notes,
        tags=tags,
    )
    updated = CaseService(ctx.session_manager).update_case(identifier, dto, reason=reason)
    return to_result(updated.model_dump(mode="json"))


def _review(ctx: ServerContext, identifier: str, resume: bool, reason: str) -> dict:
    checked(CaseReviewArgs, {"identifier": identifier, "resume": resume, "reason": reason})
    updated = CaseService(ctx.session_manager).review_case(identifier, resume=resume, reason=reason)
    return to_result(updated.model_dump(mode="json"))


def _close(ctx: ServerContext, identifier: str, reason: str, confirm: str) -> dict:
    checked(CaseCloseArgs, {"identifier": identifier, "reason": reason, "confirm": confirm})
    updated = CaseService(ctx.session_manager).close_case(identifier, reason=reason)
    return to_result(updated.model_dump(mode="json"))


def _archive(ctx: ServerContext, identifier: str, confirm: str) -> dict:
    checked(CaseDeleteArgs, {"identifier": identifier, "confirm": confirm})
    CaseService(ctx.session_manager).delete_case(identifier, purge=False)
    return to_result({"identifier": identifier, "archived": True})


def _restore(ctx: ServerContext, identifier: str, confirm: str) -> dict:
    checked(CaseDeleteArgs, {"identifier": identifier, "confirm": confirm})
    restored = CaseService(ctx.session_manager).restore_case(identifier)
    return to_result(restored.model_dump(mode="json"))


def _purge(ctx: ServerContext, identifier: str, confirm: str) -> dict:
    checked(CaseDeleteArgs, {"identifier": identifier, "confirm": confirm})
    CaseService(ctx.session_manager).delete_case(identifier, purge=True)
    return to_result({"identifier": identifier, "purged": True})
