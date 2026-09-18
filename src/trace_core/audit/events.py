"""Audit event envelope: Subject + Context for long-term vocabulary growth."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Subject:
    """Who/what the event is about. V1: type=case, V2: evidence/report/device."""

    type: str  # case | evidence | report | device | system
    number: str  # human id, e.g. 2026-CR-0029
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
        return json.loads(payload_json).get("details", {})
    except Exception:
        return {}
