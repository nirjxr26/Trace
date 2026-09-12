"""Presentation error handling and user remediation components."""

from collections.abc import Generator
from contextlib import contextmanager

import typer

from trace_core.core.cli.exit_codes import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_VERIFY_FAILED
from trace_core.core.errors import (
    ApplicationError,
    AuditTamperError,
    ConcurrencyConflictError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
)
from trace_core.core.ui.renderers import render_error_card


def _resolve_unexpected_error(
    e: Exception, operation_title: str | None, default_remediation: str | None
) -> tuple[str, str, str | None, int]:
    from trace_core.core.settings import settings

    err_msg = (
        str(e)
        if settings.debug
        else "An unexpected operational error occurred. Run with TRACE_DEBUG=1 or inspect system logs for technical details."
    )

    return (
        operation_title or "Unexpected Error",
        err_msg,
        default_remediation or "Verify database connectivity or system configuration.",
        EXIT_ERROR,
    )


def _resolve_error_details(
    e: Exception, operation_title: str | None, default_remediation: str | None
) -> tuple[str, str, str | None, int]:
    if isinstance(e, NotFoundError):
        title = f"{e.resource_type} Not Found"
        remediation = default_remediation or f"Run 'list' to inspect available {e.resource_type.lower()} records."
        return title, str(e), remediation, EXIT_NOT_FOUND

    if isinstance(e, ConcurrencyConflictError):
        title = "Concurrency Conflict"
        remediation = (
            default_remediation or "Another process modified this record. Reload the latest state before modifying."
        )
        return title, str(e), remediation, EXIT_ERROR

    if isinstance(e, ConflictError):
        title = operation_title or "Duplicate Record"
        remediation = default_remediation or "Ensure the record number or unique field is unique."
        return title, str(e), remediation, EXIT_ERROR

    if isinstance(e, StateTransitionError):
        return operation_title or "Invalid State Transition", str(e), default_remediation, EXIT_ERROR

    if isinstance(e, AuditTamperError):
        return (
            operation_title or "Audit Verification Failed",
            str(e),
            default_remediation or "Inspect audit chain for tampered sequence and restore from backup.",
            EXIT_VERIFY_FAILED,
        )

    if isinstance(e, ApplicationError):
        return operation_title or "Application Error", str(e), default_remediation, EXIT_ERROR

    return _resolve_unexpected_error(e, operation_title, default_remediation)


@contextmanager
def capture_cli_errors(
    operation_title: str | None = None,
    *,
    exit_on_error: bool = True,
    default_remediation: str | None = None,
) -> Generator[None, None, None]:
    """
    Unified error boundary context manager for CLI commands and interactive shell.
    Standardizes error card rendering and exit code handling across the presentation layer.
    """
    try:
        yield
    except typer.Exit:
        raise
    except Exception as e:
        title, message, remediation, exit_code = _resolve_error_details(e, operation_title, default_remediation)
        render_error_card(title=title, message=message, remediation=remediation)
        if exit_on_error:
            raise typer.Exit(exit_code) from None
