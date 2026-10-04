"""Audit event envelope: Subject + Context for long-term vocabulary growth."""

import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

SUBJECT_TYPE_CASE: Final[str] = "case"
SUBJECT_TYPE_EVIDENCE: Final[str] = "evidence"
SUBJECT_TYPE_REPORT: Final[str] = "report"
SUBJECT_TYPE_DEVICE: Final[str] = "device"
SUBJECT_TYPE_SYSTEM: Final[str] = "system"
SUBJECT_TYPES: Final[frozenset[str]] = frozenset(
    {
        SUBJECT_TYPE_CASE,
        SUBJECT_TYPE_EVIDENCE,
        SUBJECT_TYPE_REPORT,
        SUBJECT_TYPE_DEVICE,
        SUBJECT_TYPE_SYSTEM,
    }
)


@dataclass(frozen=True, slots=True)
class Subject:
    """Who/what the event is about. V1: type=case, V2: evidence/report/device."""

    type: str  # case | evidence | report | device | system
    number: str | None = None  # human id, e.g. 2026-CR-0029; None when type != case
    id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Context:
    """Where/how the event happened. Kept inside payload.details to avoid DB change."""

    host: str
    trace_version: str
    command: str
    os_user: str = "unknown"
    session_id: str = ""


def parse_details(payload_json: str) -> dict[str, Any]:
    """Extract details dict from canonical payload_json. Shared by renderers."""
    try:
        details = json.loads(payload_json).get("details", {})
    except Exception:
        return {}
    # A tampered row may carry a non-dict (e.g. null); callers expect a dict.
    return details if isinstance(details, dict) else {}
