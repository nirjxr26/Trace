"""Presentation error handling and user remediation components."""

from collections.abc import Generator
from contextlib import contextmanager

import typer
from pydantic import ValidationError as PydanticValidationError

from trace_core.core.cli.exit_codes import EXIT_CONFLICT, EXIT_ERROR, EXIT_NOT_FOUND, EXIT_USAGE, EXIT_VERIFY_FAILED
from trace_core.core.domain import DomainError
from trace_core.core.errors import (
    ApplicationError,
    AuditTamperError,
    ConcurrencyConflictError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
)
from trace_core.core.ui.renderers import render_error_card


def _format_pydantic_error(e: PydanticValidationError) -> str:
    """Flatten pydantic's error list into one line; the card renderer takes a single message."""
    parts = []
    for err in e.errors()[:5]:
        loc = ".".join(str(item) for item in err["loc"]) or "input"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


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


def _device_error(e: Exception, operation_title: str | None, default_remediation: str | None):  # type: ignore[no-untyped-def]
    """Map a device-domain failure to its semantic exit code [D4], [D16].

    §14.10 is the constraint that matters: `EXIT_UNKNOWN` (9) is the device preflight
    UNKNOWN outcome and nothing else. A malformed config, a database failure or an
    unexpected exception must never be laundered into it, so the mapping keys on the
    verdict the error carries, not on the exception class alone.
    """
    from trace_core.core.cli.exit_codes import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_SOURCE_WRITABLE, EXIT_UNKNOWN
    from trace_core.devices.domain import DeviceAccessDeniedError, DeviceNotFoundError, WriteProtectionError

    if isinstance(e, DeviceNotFoundError):
        return (
            operation_title or "Device Not Found",
            str(e),
            default_remediation or "Run 'device list' and use a node exactly as reported.",
            EXIT_NOT_FOUND,
        )
    if isinstance(e, DeviceAccessDeniedError):
        return (
            operation_title or "Device Access Denied",
            str(e),
            default_remediation or "Re-run from an elevated Administrator shell.",
            EXIT_ERROR,
        )
    if not isinstance(e, WriteProtectionError):
        return None
    if e.verdict.value == "WRITABLE":
        return (
            operation_title or "Source Is Writable",
            str(e),
            default_remediation
            or "Set the hardware write-protect switch or read-only flag, or use a write-protected source.",
            EXIT_SOURCE_WRITABLE,
        )
    return (
        operation_title or "Write Protection Unknown",
        str(e),
        default_remediation or _cause_remediation(e.evidence),
        EXIT_UNKNOWN,
    )


def _cause_remediation(evidence: object) -> str:
    from trace_core.devices.domain import ProtectionEvidence, UnknownCause

    if not isinstance(evidence, ProtectionEvidence):
        return "Re-establish write protection before imaging, or acknowledge the unverified source."
    cause = evidence.unknown_cause
    if cause is UnknownCause.EACCES:
        return "Access was denied. Re-run from an elevated shell."
    if cause is UnknownCause.SMARTCTL_TIMEOUT:
        return "The probe tool timed out. Retry, or exclude it and use the OS-native path."
    if cause in (UnknownCause.SMARTCTL_MALFORMED, UnknownCause.TOOL_TOO_OLD, UnknownCause.TOOL_MISSING):
        return "The probe tool could not be used. Check its version and availability."
    if cause is UnknownCause.SYSFS_DISAGREEMENT:
        return "Two sources disagreed about write protection. Resolve the conflict before imaging."
    if cause is UnknownCause.IOCTL_FAILURE:
        return "The kernel refused the write-protection query. Check device state and retry."
    if cause is UnknownCause.DEVICE_DISAPPEARED:
        return "The device disconnected during the check. Reconnect it and retry."
    return "Re-establish write protection before imaging, or acknowledge the unverified source."


def _update_error(e: Exception, operation_title: str | None, default_remediation: str | None):  # type: ignore[no-untyped-def]
    try:
        from trace_core.core.cli.exit_codes import (
            EXIT_ERROR,
            EXIT_RECOVERY_FAILED,
            EXIT_RECOVERY_RETRY,
            EXIT_UPDATE_BLOCKED,
        )
        from trace_core.updates.errors import (
            RecoveryBlockedError,
            RecoveryError,
            UpdateNetworkError,
            UpdatePolicyBlockedError,
            UpdateVerificationError,
        )

        specs = (
            (
                UpdateVerificationError,
                "Update Verification Failed",
                "Update rejected — verification failed. Installation not performed.",
                EXIT_VERIFY_FAILED,
            ),
            (
                UpdatePolicyBlockedError,
                "Update Blocked",
                "Update deferred by policy. See block reason.",
                EXIT_UPDATE_BLOCKED,
            ),
            (
                UpdateNetworkError,
                "Update Check Failed",
                "Check network connectivity and manifest URL, then retry.",
                EXIT_ERROR,
            ),
            (
                RecoveryBlockedError,
                "Recovery Blocked",
                "A live updater owns migration. Retry after it finishes.",
                EXIT_RECOVERY_RETRY,
            ),
            (
                RecoveryError,
                "Recovery Failed",
                "Recovery could not restore a bootable release. Inspect diagnostics.",
                EXIT_RECOVERY_FAILED,
            ),
        )
        for err_cls, title, remed, code in specs:
            if isinstance(e, err_cls):
                return (
                    operation_title or title,
                    str(e),
                    default_remediation or remed,
                    code,
                )
    except Exception:
        pass
    return None


def _match_typed(
    e: Exception,
    err_cls: type,
    title: str,
    remediation: str,
    code: int,
    operation_title: str | None,
    default_remediation: str | None,
    message: str | None = None,
):  # type: ignore[no-untyped-def]
    if isinstance(e, err_cls):
        return (
            operation_title or title,
            message if message is not None else str(e),
            default_remediation or remediation,
            code,
        )
    return None


def _typed_error(e: Exception, operation_title: str | None, default_remediation: str | None):  # type: ignore[no-untyped-def]
    if isinstance(e, NotFoundError):
        return (
            f"{e.resource_type} Not Found",
            str(e),
            default_remediation or f"Run 'list' to inspect available {e.resource_type.lower()} records.",
            EXIT_NOT_FOUND,
        )
    specs = (
        (
            ConcurrencyConflictError,
            "Concurrency Conflict",
            "Another process modified this record. Reload the latest state before modifying.",
            EXIT_CONFLICT,
        ),
        (ConflictError, "Duplicate Record", "Ensure the record number or unique field is unique.", EXIT_ERROR),
        (
            StateTransitionError,
            "Invalid State Transition",
            "Check the record's current state; retry from a state that allows this change.",
            EXIT_ERROR,
        ),
        (DomainError, "Invalid Input", "Correct the highlighted field and retry.", EXIT_USAGE),
        (
            AuditTamperError,
            "Audit Verification Failed",
            "Inspect audit chain for tampered sequence and restore from backup.",
            EXIT_VERIFY_FAILED,
        ),
    )
    for err_cls, title, remed, code in specs:
        # Checked before ConflictError: it is a subclass, and a version conflict is a
        # retry-after-reload condition, not a duplicate record. Both used to report
        # EXIT_ERROR, which left EXIT_CONFLICT declared but unreachable.
        if (r := _match_typed(e, err_cls, title, remed, code, operation_title, default_remediation)) is not None:
            return r
    if isinstance(e, PydanticValidationError):
        return (
            operation_title or "Invalid Input",
            _format_pydantic_error(e),
            default_remediation or "Correct the highlighted field and retry.",
            EXIT_USAGE,
        )
    if (r := _device_error(e, operation_title, default_remediation)) is not None:
        return r
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
