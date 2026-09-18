"""Audit repository: serialized global chain append, list, and streaming helpers."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from trace_core.audit.domain import GENESIS_CHAIN, AuditAction, AuditEvent, build_payload, chain_hash, payload_hash
from trace_core.audit.dto import AuditEventDto, AuditFilterDto
from trace_core.audit.models import AuditChainStateModel, AuditEventModel
from trace_core.cases.domain import normalize_number
from trace_core.core.database.repository import ilike_literal, paginate
from trace_core.core.domain import ensure_utc


def _base_fields(m: AuditEventModel) -> dict[str, Any]:
    return {
        "seq": m.seq,
        "ts": ensure_utc(m.ts) or m.ts,  # type: ignore[arg-type]
        "action": AuditAction(m.action),
        "actor": m.actor,
        "subject_case_number": m.subject_case_number,
        "subject_case_id": m.subject_case_id,
        "payload_json": m.payload_json,
        "payload_hash": m.payload_hash,
        "prev_chain": m.prev_chain,
        "chain_hash": m.chain_hash,
        "key_id": m.key_id,
        "signature": m.signature,
    }


def _model_to_domain(m: AuditEventModel) -> AuditEvent:
    return AuditEvent(**_base_fields(m))  # type: ignore[arg-type]


def _model_to_dto(m: AuditEventModel) -> AuditEventDto:
    return AuditEventDto(**_base_fields(m))  # type: ignore[arg-type]


def get_by_seq(session: Session, seq: int) -> AuditEventDto | None:
    row = session.get(AuditEventModel, seq)
    return _model_to_dto(row) if row else None


class SqlAlchemyAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def _ensure_head_locked(self) -> AuditChainStateModel:
        # SELECT FOR UPDATE on head row; create genesis if missing
        # ponytail: SQLite has single writer, skip FOR UPDATE; PG uses it to serialize chain
        dialect = getattr(getattr(self.session, "bind", None), "dialect", None)
        dialect_name = getattr(dialect, "name", "") if dialect else ""
        stmt = select(AuditChainStateModel).where(AuditChainStateModel.id == 1)
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update()
        head = self.session.scalar(stmt)
        if not head:
            head = AuditChainStateModel(id=1, last_seq=0, last_chain_hash=GENESIS_CHAIN)
            self.session.add(head)
            self.session.flush()
            if dialect_name == "postgresql":
                head = self.session.scalar(stmt) or head
        return head

    def append(
        self,
        action: AuditAction,
        actor: str,
        subject_case_number: str,
        subject_case_id: UUID | None,
        payload_details: dict[str, Any] | None = None,
    ) -> AuditEventDto:
        from trace_core.audit.signing import sign_bytes
        from trace_core.core.canonical import canonical_json_str
        from trace_core.core.clock import now_utc

        ts_val = now_utc()
        details = dict(payload_details or {})
        payload = build_payload(action, subject_case_number, actor, details, ts_val)
        payload_json_str = canonical_json_str(payload)
        p_hash = payload_hash(payload)
        key_id, signature = sign_bytes(payload_json_str.encode("utf-8"))

        head = self._ensure_head_locked()
        prev = head.last_chain_hash
        seq = head.last_seq + 1
        c_hash = chain_hash(prev, p_hash, seq)

        model = AuditEventModel(
            seq=seq,
            ts=ts_val,
            action=action.value,
            actor=actor,
            subject_case_number=subject_case_number,
            subject_case_id=subject_case_id,
            payload_json=payload_json_str,
            payload_hash=p_hash,
            prev_chain=prev,
            chain_hash=c_hash,
            key_id=key_id,
            signature=signature,
        )
        self.session.add(model)
        head.last_seq = seq
        head.last_chain_hash = c_hash
        self.session.flush()
        return _model_to_dto(model)

    def head(self) -> tuple[int, str]:
        """Ledger tip (seq, chain) in one indexed row. Single source for anchors + tail checks."""
        head = self.session.scalar(select(AuditChainStateModel).where(AuditChainStateModel.id == 1))
        if head is None:
            return 0, GENESIS_CHAIN
        return head.last_seq, head.last_chain_hash

    def list_events(self, f: AuditFilterDto | None = None) -> list[AuditEventDto]:
        """Newest-first. Contract: case_number exact, actor/action/search substring."""
        filt = f or AuditFilterDto()
        stmt = select(AuditEventModel)
        if filt.case_number:
            stmt = stmt.where(AuditEventModel.subject_case_number == normalize_number(filt.case_number))
        if filt.action:
            stmt = stmt.where(AuditEventModel.action == filt.action.value)
        if filt.actor:
            stmt = stmt.where(ilike_literal(AuditEventModel.actor, filt.actor.strip()))
        if filt.search and filt.search.strip():
            term = filt.search.strip()
            stmt = stmt.where(
                ilike_literal(AuditEventModel.subject_case_number, term)
                | ilike_literal(AuditEventModel.actor, term)
                | ilike_literal(AuditEventModel.action, term)
            )
        stmt = stmt.order_by(AuditEventModel.seq.desc())
        stmt = paginate(stmt, filt.limit, filt.offset)
        rows = self.session.scalars(stmt).all()
        return [_model_to_dto(m) for m in rows]
