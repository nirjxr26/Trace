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


_MAX_GAPS = 10_000


def _collect_gaps(prev_seq: int | None, cur_seq: int, gaps: list[int]) -> None:
    if prev_seq is None or cur_seq == prev_seq + 1:
        return
    # Bounded: an absurd jump (tampered seq) must not OOM the detector by
    # materializing billions of ints. Detection itself never depends on this
    # list — the next row's prev_chain check fails closed regardless.
    remaining = _MAX_GAPS - len(gaps)
    if remaining <= 0:
        return
    gaps.extend(range(prev_seq + 1, min(cur_seq, prev_seq + 1 + remaining)))


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
    is_signature = mismatch_type == "signature"
    return VerifyResultDto(
        is_valid=False,
        events_verified=events_verified,
        first_seq=first_seq,
        last_seq=last_seq,
        first_mismatch_seq=m.seq,
        mismatch_type=mismatch_type,
        expected_payload_hash=expected if is_payload else None,
        actual_payload_hash=actual if is_payload else None,
        expected_chain_hash=None if (is_payload or is_signature) else expected,
        actual_chain_hash=None if (is_payload or is_signature) else actual,
        expected_signature=expected if is_signature else None,
        actual_signature=actual if is_signature else None,
        sequence_gaps=list(gaps),
    )


def verify_event(
    payload_json: str,
    payload_hash: str,
    prev_chain: str,
    chain_hash_str: str,
    seq: int,
    *,
    signature: str | None = None,
    key_id: str | None = None,
) -> bool:
    """Row self-check: recompute hashes and envelope for one stored event.

    True means this row is intact. Cannot detect deletion — that needs a full
    verify or an external anchor. Legacy rows without a signature skip the check.
    """
    from trace_core.audit.signing import verify_bytes

    if _expected_payload_hash(payload_json) != payload_hash:
        return False
    if chain_hash(prev_chain, payload_hash, seq) != chain_hash_str:
        return False
    if signature is not None and not verify_bytes(key_id, payload_json.encode("utf-8"), signature):
        return False
    return True


def _signature_mismatch(m: AuditEventModel) -> tuple[str, str] | None:
    if m.signature is None:
        return None
    from trace_core.audit.signing import expected_signature, verify_bytes

    raw = m.payload_json.encode("utf-8")
    if verify_bytes(m.key_id, raw, m.signature):
        return None
    return expected_signature(m.key_id, raw) or f"key:{m.key_id}", m.signature


def _row_mismatch(m: AuditEventModel, prev_chain: str) -> tuple[str, str, str] | None:
    expected_p = _expected_payload_hash(m.payload_json)
    if expected_p != m.payload_hash:
        return "payload_hash", expected_p, m.payload_hash
    if m.prev_chain != prev_chain:
        return "prev_chain", prev_chain, m.prev_chain
    expected_c = chain_hash(m.prev_chain, m.payload_hash, m.seq)
    if expected_c != m.chain_hash:
        return "chain_hash", expected_c, m.chain_hash
    signature = _signature_mismatch(m)
    if signature is not None:
        expected_s, actual_s = signature
        return "signature", expected_s, actual_s
    return None


def _retain_first(first_seq: int | None, seq: int) -> int:
    """First observed seq wins. Single source for ledger range tracking."""
    return seq if first_seq is None else first_seq


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
        first_seq = _retain_first(first_seq, m.seq)
        last_seq = m.seq
        _collect_gaps(prev_seq, m.seq, gaps)
        mismatch = _row_mismatch(m, prev_chain)
        if mismatch is not None:
            mismatch_type, expected, actual = mismatch
            return _mismatch(m, idx, first_seq, last_seq, gaps, mismatch_type, expected, actual)  # type: ignore[arg-type]
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
