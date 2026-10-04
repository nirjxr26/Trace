"""Isolated bundle exporter: streaming JSONL, no service logic."""

import json
from pathlib import Path

from sqlalchemy import select

from trace_core.audit.domain import CANONICAL_VERSION, HASH_ALGO, SPEC_VERSION
from trace_core.audit.models import AuditEventModel
from trace_core.audit.repository import _common_fields
from trace_core.core.canonical import _coerce_utc_required, canonical_ts
from trace_core.core.fs import atomic_write_lines


def _ledger_tip(session) -> tuple[int, str]:  # type: ignore[no-untyped-def]
    """Chain head for the bundle header. Single source: the repository's indexed head row."""
    from trace_core.audit.repository import SqlAlchemyAuditRepository

    return SqlAlchemyAuditRepository(session).head()


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
    # coerce_utc assumes UTC for naive rows (SQLite storage); the old fallback
    # str(m.ts) wrote a non-canonical timestamp into the forensic bundle. The
    # column is non-nullable, so the ts is always present.
    return _common_fields(
        m,
        ts=canonical_ts(_coerce_utc_required(m.ts)),
        action=m.action,
        subject_case_id=str(m.subject_case_id) if m.subject_case_id else None,
    )


def export_bundle(session, out_path: str | Path) -> Path:  # type: ignore[no-untyped-def]
    stmt = select(AuditEventModel).order_by(AuditEventModel.seq.asc())
    tip_seq, tip_chain = _ledger_tip(session)

    def _lines():  # type: ignore[no-untyped-def]
        yield _header(tip_seq, tip_chain)
        for m in session.scalars(stmt).yield_per(500):
            yield json.dumps(_record_dict(m), ensure_ascii=False) + "\n"

    return atomic_write_lines(out_path, _lines(), newline="\n")
