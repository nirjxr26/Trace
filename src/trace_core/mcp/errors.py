import json
from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import DBAPIError, OperationalError

from trace_core.core.domain import DomainError
from trace_core.core.errors import (
    ApplicationError,
    AuditTamperError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
    TraceError,
    ValidationError,
)
from trace_core.devices.domain import DeviceEnumerationError, DeviceError
from trace_core.updates.errors import UpdateError, UpdateInProgressError


class ToolFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def envelope(code: str, message: str, correlation_id: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
        "correlation_id": correlation_id,
    }


def _safe_message(exc: Exception) -> str:
    if isinstance(exc, PydanticValidationError):
        return "The tool arguments are invalid."
    if isinstance(exc, ValidationError | DomainError | ToolFailure):
        return str(exc)
    return "The operation was refused. No further details are available."


def map_error(exc: Exception, correlation_id: str) -> dict[str, Any]:
    if isinstance(exc, ToolFailure):
        return envelope(exc.code, exc.message, correlation_id, retryable=exc.retryable)
    if isinstance(exc, AuthorizationError):
        return envelope("FORBIDDEN", str(exc), correlation_id)
    if isinstance(exc, NotFoundError):
        return envelope("NOT_FOUND", str(exc), correlation_id)
    if isinstance(exc, ConflictError):
        return envelope("CONFLICT", str(exc), correlation_id)
    if isinstance(exc, StateTransitionError):
        return envelope("INVALID_STATE", str(exc), correlation_id)
    if isinstance(exc, ValidationError | DomainError | PydanticValidationError):
        return envelope("VALIDATION", _safe_message(exc), correlation_id)
    if isinstance(exc, DeviceEnumerationError | DeviceError):
        return envelope("DEVICE_ERROR", str(exc), correlation_id, retryable=True)
    if isinstance(exc, UpdateInProgressError):
        return envelope("UPDATE_IN_PROGRESS", str(exc), correlation_id)
    if isinstance(exc, UpdateError):
        return envelope("UPDATE_FAILED", _safe_message(exc), correlation_id)
    if isinstance(exc, AuditTamperError):
        return envelope(
            "AUDIT_TAMPER",
            "Ledger verification failed. Run `trace audit verify` for details on this workstation.",
            correlation_id,
        )
    if isinstance(exc, OperationalError | DBAPIError):
        return envelope("DB_UNAVAILABLE", "The database could not be reached.", correlation_id, retryable=True)
    if isinstance(exc, ApplicationError | TraceError):
        return envelope("APPLICATION_ERROR", _safe_message(exc), correlation_id)
    return envelope("INTERNAL", "An unexpected error occurred.", correlation_id)


def result(payload: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=is_error,
    )


def failure(exc: Exception, correlation_id: str) -> CallToolResult:
    return result(map_error(exc, correlation_id), is_error=True)
