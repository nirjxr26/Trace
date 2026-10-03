"""Audit domain: actions, hashing helpers, and invariants."""

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from trace_core.core.canonical import canonical_json, canonical_ts, is_naive
from trace_core.core.clock import now_utc
from trace_core.core.domain import InvariantViolationError

GENESIS_CHAIN: str = "0" * 64
_HASH_HEX_LENGTH: int = 64
SPEC_VERSION = "trace-audit-v1"
CANONICAL_VERSION = "trace-canonical-json-v1"
HASH_ALGO = "SHA-256"
_HASHERS: Final[dict[str, Any]] = {"SHA-256": hashlib.sha256}
AUDIT_LEDGER_NOT_INITIALIZED_MESSAGE = "Audit ledger not initialized. Run `trace db migrate`."


class AuditAction(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    CASE_UPDATED = "CASE_UPDATED"
    CASE_CLOSED = "CASE_CLOSED"
    CASE_ARCHIVED = "CASE_ARCHIVED"
    CASE_RESTORED = "CASE_RESTORED"
    CASE_PURGED = "CASE_PURGED"


ACTION_TITLES: Final[dict[str, str]] = {
    "CASE_CREATED": "Case created",
    "CASE_UPDATED": "Case details updated",
    "CASE_CLOSED": "Case closed",
    "CASE_ARCHIVED": "Case archived",
    "CASE_RESTORED": "Case restored",
    "CASE_PURGED": "Case purged",
}


def _hasher() -> Any:
    """Single source for the ledger hash. Resolves through HASH_ALGO so the declared
    algorithm and the one actually applied cannot drift apart."""
    return _HASHERS[HASH_ALGO]


def payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON payload."""
    return _hasher()(canonical_json(payload)).hexdigest()


def chain_hash(prev_chain: str, p_hash: str, seq: int) -> str:
    """Chain hash = SHA256(prev_chain · payload_hash · seq).

    Binding the previous head AND the sequence number means an attacker cannot
    reorder events or splice two valid chains together without breaking the link.
    """
    if len(prev_chain) != _HASH_HEX_LENGTH or len(p_hash) != _HASH_HEX_LENGTH:
        raise InvariantViolationError("chain hash inputs must both be 64-character SHA-256 hex digests")
    return _hasher()(f"{prev_chain}{p_hash}{seq}".encode()).hexdigest()


def build_payload(
    action: AuditAction,
    subject_case_number: str,
    actor: str,
    details: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """Build canonical payload dict for hashing."""
    ts_val = ts if ts is not None else now_utc()
    if is_naive(ts_val):
        raise InvariantViolationError("Audit ts must be timezone-aware UTC.")
    ts_utc = canonical_ts(ts_val)
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
