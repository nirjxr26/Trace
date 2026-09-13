"""Isolated bundle exporter: streaming JSONL, no service logic."""

import json
import os
from pathlib import Path

from sqlalchemy import select

from trace_core.audit.domain import CANONICAL_VERSION, HASH_ALGO, SPEC_VERSION
from trace_core.audit.models import AuditEventModel


def _header() -> str:
    return (
        json.dumps(
            {"spec": SPEC_VERSION, "canonicalization": CANONICAL_VERSION, "hash_algo": HASH_ALGO}, ensure_ascii=False
        )
        + "\n"
    )


def _record_dict(m) -> dict:  # type: ignore[no-untyped-def]
    return {
        "seq": m.seq,
        "ts": m.ts.isoformat().replace("+00:00", "Z") if hasattr(m.ts, "isoformat") else str(m.ts),
        "action": m.action,
        "actor": m.actor,
        "subject_case_number": m.subject_case_number,
        "subject_case_id": str(m.subject_case_id) if m.subject_case_id else None,
        "payload_json": m.payload_json,
        "payload_hash": m.payload_hash,
        "prev_chain": m.prev_chain,
        "chain_hash": m.chain_hash,
    }


def export_bundle(session, out_path: str | Path) -> Path:  # type: ignore[no-untyped-def]
    out = Path(out_path)
    tmp = out.with_suffix(out.suffix + ".tmp")
    out.parent.mkdir(parents=True, exist_ok=True)
    stmt = select(AuditEventModel).order_by(AuditEventModel.seq.asc())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(_header())
        for m in session.scalars(stmt).yield_per(500):
            f.write(json.dumps(_record_dict(m), ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp, out)
    return out
