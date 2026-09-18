"""Isolated bundle exporter: streaming JSONL, no service logic."""

import json
from pathlib import Path

from sqlalchemy import select

from trace_core.audit.domain import CANONICAL_VERSION, HASH_ALGO, SPEC_VERSION
from trace_core.audit.models import AuditEventModel
from trace_core.core.canonical import canonical_ts
from trace_core.core.fs import atomic_write_lines


def _header() -> str:
    return (
        json.dumps(
            {"spec": SPEC_VERSION, "canonicalization": CANONICAL_VERSION, "hash_algo": HASH_ALGO}, ensure_ascii=False
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

    def _lines():  # type: ignore[no-untyped-def]
        yield _header()
        for m in session.scalars(stmt).yield_per(500):
            yield json.dumps(_record_dict(m), ensure_ascii=False) + "\n"

    return atomic_write_lines(out_path, _lines(), newline="\n")
