"""Audit domain: actions, hashing helpers, and invariants."""

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from trace_core.core.canonical import canonical_json
from trace_core.core.clock import now_utc
from trace_core.core.domain import InvariantViolationError

GENESIS_CHAIN: str = "0" * 64
SPEC_VERSION = "trace-audit-v1"
CANONICAL_VERSION = "trace-canonical-json-v1"
HASH_ALGO = "SHA-256"
AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE = "Audit ledger not initialized. Run 'trace db migrate'."


class AuditAction(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    CASE_UPDATED = "CASE_UPDATED"
    CASE_CLOSED = "CASE_CLOSED"
    CASE_ARCHIVED = "CASE_ARCHIVED"
    CASE_RESTORED = "CASE_RESTORED"
    CASE_PURGED = "CASE_PURGED"


def payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON payload."""
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def chain_hash(prev_chain: str, p_hash: str, seq: int) -> str:
    """Chain hash = SHA256(prev_chain ‖ payload_hash ‖ seq)."""
    return hashlib.sha256(f"{prev_chain}{p_hash}{seq}".encode()).hexdigest()


class AuditEvent(BaseModel):
    """Domain entity for tamper-evident audit ledger row (immutable)."""

    seq: int = Field(ge=1)
    ts: datetime
    action: AuditAction
    actor: str = Field(min_length=1, max_length=255)
    subject_case_number: str = Field(min_length=1, max_length=100)
    subject_case_id: UUID | None = None
    payload_json: str
    payload_hash: str = Field(min_length=64, max_length=64)
    prev_chain: str = Field(min_length=64, max_length=64)
    chain_hash_str: str = Field(min_length=64, max_length=64, alias="chain_hash")

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    @property
    def chain_hash(self) -> str:
        return self.chain_hash_str


def build_payload(
    action: AuditAction,
    subject_case_number: str,
    actor: str,
    details: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """Build canonical payload dict for hashing."""
    ts_val = ts or now_utc()
    if ts_val.tzinfo is None or ts_val.tzinfo.utcoffset(ts_val) is None:
        raise InvariantViolationError("Audit ts must be timezone-aware UTC.")
    ts_utc = ts_val.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "action": action.value,
        "actor": actor,
        "subject_case_number": subject_case_number,
        "ts": ts_utc,
        "spec": SPEC_VERSION,
        "canonicalization": CANONICAL_VERSION,
        "hash_algo": HASH_ALGO,
        "details": details or {},
    }
