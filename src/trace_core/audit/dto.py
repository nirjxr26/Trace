"""Audit DTOs."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from trace_core.audit.domain import AuditAction
from trace_core.core.dto import BaseDto, BaseFilterDto


class AuditEventDto(BaseDto):
    seq: int
    ts: datetime
    action: AuditAction
    actor: str
    subject_case_number: str
    subject_case_id: UUID | None = None
    payload_json: str
    payload_hash: str
    prev_chain: str
    chain_hash: str


class AuditFilterDto(BaseFilterDto):
    case_number: str | None = None
    action: AuditAction | None = None
    actor: str | None = None


_OUTPUT_DESC = "Output table|json"

AUDIT_SHOW_FLAGS = [
    ("--seq", "Detailed 5W1H for seq"),
    ("--case", "Filter by case number"),
    ("--action", "Filter by action"),
    ("--actor", "Filter by actor"),
    ("--search", "Search actor/action/case"),
    ("-q", "Search actor/action/case"),
    ("--output", _OUTPUT_DESC),
    ("-o", _OUTPUT_DESC),
    ("--limit", "Max rows"),
    ("--offset", "Offset"),
]
AUDIT_VERIFY_FLAGS = [("--output", _OUTPUT_DESC), ("-o", _OUTPUT_DESC), ("--anchor", "Anchor JSON to check tail")]
AUDIT_EXPORT_FLAGS = [("--out", "Output file"), ("--format", "jsonl only")]
ACTION_CHOICES = [
    ("CASE_CREATED", "Case created"),
    ("CASE_UPDATED", "Case updated"),
    ("CASE_CLOSED", "Case closed"),
    ("CASE_ARCHIVED", "Case archived"),
    ("CASE_RESTORED", "Case restored"),
    ("CASE_PURGED", "Case purged"),
]


class VerifyResultDto(BaseDto):
    is_valid: bool
    events_verified: int
    first_seq: int | None = None
    last_seq: int | None = None
    first_mismatch_seq: int | None = None
    mismatch_type: str | None = None
    expected_payload_hash: str | None = None
    actual_payload_hash: str | None = None
    expected_chain_hash: str | None = None
    actual_chain_hash: str | None = None
    sequence_gaps: list[int] = Field(default_factory=list)
