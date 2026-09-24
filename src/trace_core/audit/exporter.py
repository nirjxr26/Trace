"""Isolated bundle exporter: streaming JSONL, no service logic."""

import json
from pathlib import Path

from sqlalchemy import select

from trace_core.audit.domain import CANONICAL_VERSION, GENESIS_CHAIN, HASH_ALGO, SPEC_VERSION
from trace_core.audit.models import AuditChainStateModel, AuditEventModel
from trace_core.core.canonical import canonical_ts
from trace_core.core.fs import atomic_write_lines


def _ledger_tip(session) -> tuple[int, str]:  # type: ignore[no-untyped-def]
    """Chain head for the bundle header. Missing head means an empty ledger."""
    row = session.scalar(select(AuditChainStateModel).where(AuditChainStateModel.id == 1))
    if row is None:
        return 0, GENESIS_CHAIN
    return row.last_seq, row.last_chain_hash


def _header(last_seq: int, last_chain: str) -> str:
    # last_* is advisory (read at export start): readers compare it against the
    # final data line to spot tail truncation without an external anchor.
    return (
        json.dumps(
            {
                "spec": SPEC_VERSION,
                "canonicalization": CANONICAL_VERSION,
                "hash_algo": HASH_ALGO,
                "last_seq": last_seq,
                "last_chain": last_chain,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def _record_dict(m) -> dict:  # type: ignore[no-untyped-def]
    try:
        ts_str = canonical_ts(m.ts)
    except Exception:
        ts_str = str(m.ts)
    return {
        "seq": m.seq,
        "ts": ts_str,
        "action": m.action,
        "actor": m.actor,
        "subject_case_number": m.subject_case_number,
        "subject_case_id": str(m.subject_case_id) if m.subject_case_id else None,
        "payload_json": m.payload_json,
        "payload_hash": m.payload_hash,
        "prev_chain": m.prev_chain,
        "chain_hash": m.chain_hash,
        "key_id": m.key_id,
        "signature": m.signature,
    }


def export_bundle(session, out_path: str | Path) -> Path:  # type: ignore[no-untyped-def]
    stmt = select(AuditEventModel).order_by(AuditEventModel.seq.asc())
    tip_seq, tip_chain = _ledger_tip(session)

    def _lines():  # type: ignore[no-untyped-def]
        yield _header(tip_seq, tip_chain)
        for m in session.scalars(stmt).yield_per(500):
            yield json.dumps(_record_dict(m), ensure_ascii=False) + "\n"

    return atomic_write_lines(out_path, _lines(), newline="\n")
