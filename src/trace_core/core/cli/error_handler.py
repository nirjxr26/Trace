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


def _update_error(e: Exception, operation_title: str | None, default_remediation: str | None):  # type: ignore[no-untyped-def]
    try:
        from trace_core.core.cli.exit_codes import EXIT_RECOVERY_FAILED, EXIT_UPDATE_BLOCKED
        from trace_core.updates.errors import (
            RecoveryError,
            UpdatePolicyBlockedError,
            UpdateVerificationError,
        )

        if isinstance(e, UpdateVerificationError):
            return (
                operation_title or "Update Verification Failed",
                str(e),
                default_remediation or "Update rejected — verification failed. Installation not performed.",
                EXIT_VERIFY_FAILED,
            )
        if isinstance(e, UpdatePolicyBlockedError):
            return (
                operation_title or "Update Blocked",
                str(e),
                default_remediation or "Update deferred by policy. See block reason.",
                EXIT_UPDATE_BLOCKED,
            )
        if isinstance(e, RecoveryError):
            return (
                operation_title or "Recovery Failed",
                str(e),
                default_remediation or "Recovery could not restore a bootable release. Inspect diagnostics.",
                EXIT_RECOVERY_FAILED,
            )
    except Exception:
        pass
    return None


def _typed_error(e: Exception, operation_title: str | None, default_remediation: str | None):  # type: ignore[no-untyped-def]
    if isinstance(e, NotFoundError):
        return (
            f"{e.resource_type} Not Found",
            str(e),
            default_remediation or f"Run 'list' to inspect available {e.resource_type.lower()} records.",
            EXIT_NOT_FOUND,
        )
    if isinstance(e, ConcurrencyConflictError):
        return (
            "Concurrency Conflict",
            str(e),
            default_remediation or "Another process modified this record. Reload the latest state before modifying.",
            EXIT_ERROR,
        )
    if isinstance(e, ConflictError):
        return (
            operation_title or "Duplicate Record",
            str(e),
            default_remediation or "Ensure the record number or unique field is unique.",
            EXIT_ERROR,
        )
    if isinstance(e, StateTransitionError):
        return operation_title or "Invalid State Transition", str(e), default_remediation, EXIT_ERROR
    if isinstance(e, AuditTamperError):
        return (
            operation_title or "Audit Verification Failed",
            str(e),
            default_remediation or "Inspect audit chain for tampered sequence and restore from backup.",
            EXIT_VERIFY_FAILED,
        )
    if (r := _update_error(e, operation_title, default_remediation)) is not None:
        return r
    return None


def _resolve_error_details(
    e: Exception, operation_title: str | None, default_remediation: str | None
) -> tuple[str, str, str | None, int]:
    if (res := _typed_error(e, operation_title, default_remediation)) is not None:
        return res
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
