"""Isolated ledger verifier: pure audit-event data, no ORM/CLI knowledge."""

import hashlib
import json
from collections.abc import Iterable

from trace_core.audit.domain import GENESIS_CHAIN, chain_hash, payload_hash
from trace_core.audit.dto import VerifyResultDto
from trace_core.audit.models import AuditEventModel


def _expected_payload_hash(payload_json: str) -> str:
    try:
        obj = json.loads(payload_json)
        return payload_hash(obj)
    except Exception:
        return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _collect_gaps(prev_seq: int | None, cur_seq: int, gaps: list[int]) -> None:
    if prev_seq is not None and cur_seq != prev_seq + 1:
        gaps.extend(range(prev_seq + 1, cur_seq))


def _mismatch(
    m: AuditEventModel,
    events_verified: int,
    first_seq: int,
    last_seq: int,
    gaps: list[int],
    mismatch_type: str,
    expected: str,
    actual: str,
) -> VerifyResultDto:
    is_payload = mismatch_type == "payload_hash"
    return VerifyResultDto(
        is_valid=False,
        events_verified=events_verified,
        first_seq=first_seq,
        last_seq=last_seq,
        first_mismatch_seq=m.seq,
        mismatch_type=mismatch_type,
        expected_payload_hash=expected if is_payload else None,
        actual_payload_hash=actual if is_payload else None,
        expected_chain_hash=None if is_payload else expected,
        actual_chain_hash=None if is_payload else actual,
        sequence_gaps=list(gaps),
    )


def verify_event(payload_json: str, payload_hash: str, prev_chain: str, chain_hash_str: str, seq: int) -> bool:
    """Row self-check: recompute both hashes for one stored event.

    True means this row is intact. Cannot detect deletion — that needs a full
    verify or an external anchor.
    """
    if _expected_payload_hash(payload_json) != payload_hash:
        return False
    return chain_hash(prev_chain, payload_hash, seq) == chain_hash_str


def verify_rows(rows: Iterable[AuditEventModel]) -> VerifyResultDto:
    """Recompute every link from stored payloads. Policy: hash/prev_chain mismatch =
    tamper (fail fast at first seq); missing seqs = gaps (warning — a middle delete
    already fails as prev_chain mismatch at the next row, while a pure tail delete
    is invisible here and needs an external anchor)."""
    first_seq: int | None = None
    last_seq: int | None = None
    gaps: list[int] = []
    prev_chain = GENESIS_CHAIN
    prev_seq: int | None = None
    idx = -1
    has_rows = False
    for idx, m in enumerate(rows):
        has_rows = True
        if first_seq is None:
            first_seq = m.seq
        last_seq = m.seq
        _collect_gaps(prev_seq, m.seq, gaps)
        expected_p = _expected_payload_hash(m.payload_json)
        if expected_p != m.payload_hash:
            # first_seq is not None here because we have at least one row
            return _mismatch(m, idx, first_seq, last_seq, gaps, "payload_hash", expected_p, m.payload_hash)  # type: ignore[arg-type]
        if m.prev_chain != prev_chain:
            return _mismatch(m, idx, first_seq, last_seq, gaps, "prev_chain", prev_chain, m.prev_chain)  # type: ignore[arg-type]
        expected_c = chain_hash(m.prev_chain, m.payload_hash, m.seq)
        if expected_c != m.chain_hash:
            return _mismatch(m, idx, first_seq, last_seq, gaps, "chain_hash", expected_c, m.chain_hash)  # type: ignore[arg-type]
        prev_chain = m.chain_hash
        prev_seq = m.seq
    if not has_rows:
        return VerifyResultDto(is_valid=True, events_verified=0)
    return VerifyResultDto(
        is_valid=True,
        events_verified=idx + 1,
        first_seq=first_seq,
        last_seq=last_seq,
        sequence_gaps=gaps,
    )
