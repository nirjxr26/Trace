"""Single source for audit anchor files: schema, write on close, verify on demand."""

import json
from pathlib import Path
from typing import Any

from trace_core.audit.domain import SPEC_VERSION
from trace_core.core.canonical import canonical_ts, parse_trailing_seq
from trace_core.core.clock import now_utc
from trace_core.core.fs import atomic_write_lines, check_contained
from trace_core.core.settings import settings


def anchor_path(case_number: str, seq: int) -> Path:
    """Filesystem location for a close-anchor. Single naming source."""
    base = Path(settings.storage_root) / "anchors"
    # Backstop even for validated numbers: never write outside storage.
    return check_contained(base / f"anchor-{case_number}-{seq}.json", base, what="anchor path")


def write_anchor(case_number: str, seq: int, chain_hash: str) -> Path:
    """Persist an anchor record for the ledger head. Returns the written path."""
    payload = {
        "case": case_number,
        "last_seq": seq,
        "last_chain": chain_hash,
        "anchored_at": canonical_ts(now_utc()),
        "spec": SPEC_VERSION,
    }
    path = anchor_path(case_number, seq)
    atomic_write_lines(path, [json.dumps(payload, indent=2)])
    return path


def read_anchor(anchor: str | Path) -> dict[str, Any]:
    """Load and parse an anchor file. Raises on unreadable content."""
    return json.loads(Path(anchor).read_text(encoding="utf-8"))


def latest_anchor_for(case_number: str) -> Path | None:
    """Newest anchor file for a case, if any. Single source for close output."""
    from trace_core.cases.domain import normalize_number

    base = Path(settings.storage_root) / "anchors"
    name = normalize_number(case_number)

    def _seq_of(path: Path) -> int:
        return parse_trailing_seq(path.stem) or -1

    def _kept(path: Path) -> bool:
        # Literal prefix match defeats glob metacharacters; containment defeats traversal.
        if not path.stem.startswith(f"anchor-{name}-"):
            return False
        try:
            check_contained(path, base, what="anchor lookup")
        except ValueError:
            return False
        return True

    try:
        matches = [p for p in base.glob(f"anchor-{name}-*.json") if _kept(p)]
    except Exception:
        return None
    return max(matches, key=_seq_of) if matches else None


def check_anchor_match(res, data: dict, latest_chain: str) -> None:  # type: ignore[no-untyped-def]
    """Pure anchor comparison. Raises AuditTamperError; performs no printing or exiting."""
    from trace_core.core.errors import AuditTamperError

    exp_seq = data.get("last_seq")
    exp_chain = data.get("last_chain")
    if res.is_valid and res.last_seq != exp_seq:
        raise AuditTamperError(f"Anchor tail mismatch: DB last_seq {res.last_seq} != anchor {exp_seq}")
    if res.is_valid and exp_chain and latest_chain != exp_chain:
        raise AuditTamperError("Anchor chain mismatch")
    if res.is_valid and data.get("signature") and data.get("key_id"):
        from trace_core.audit.signing import verify_bytes
        from trace_core.core.canonical import canonical_json

        unsigned = {k: v for k, v in data.items() if k not in ("key_id", "signature")}
        if not verify_bytes(data["key_id"], canonical_json(unsigned), data["signature"]):
            raise AuditTamperError("Anchor signature invalid")


def verify_against_anchor(svc, res, anchor: str | None) -> None:  # type: ignore[no-untyped-def]
    """Compare a verify result against an anchor file. Raises typed errors, never exits."""
    if not anchor:
        return
    from trace_core.core.errors import ValidationError

    try:
        data = read_anchor(anchor)
    except Exception as e:
        raise ValidationError(f"Unreadable anchor file: {anchor} ({e})") from e
    _, latest = svc.head()
    check_anchor_match(res, data, latest)


def record_anchor_intent(session, case_number: str, case_id, seq: int, chain_hash: str) -> None:  # type: ignore[no-untyped-def]
    """Durable outbox row in the caller's transaction. The publisher confirms later."""
    from trace_core.audit.models import INTENT_PENDING, AnchorIntentModel

    session.add(
        AnchorIntentModel(
            case_id=case_id, case_number=case_number, seq=seq, chain_hash=chain_hash, status=INTENT_PENDING
        )
    )
    session.flush()


def describe_anchor(manager, case_number: str) -> str | None:  # type: ignore[no-untyped-def]
    """One-line anchor state for close outputs. Single source for Typer/shell surfaces."""
    with manager.session() as session:
        state = latest_intent_status(session, case_number)
    anchor = latest_anchor_for(case_number)
    if anchor is not None:
        return f"Anchor: {anchor} [{state}] (copy off-host; verify with `audit verify --anchor FILE`)"
    if state != "CONFIRMED":
        return f"Anchor state: {state or 'UNKNOWN'} — copy off-host once confirmed."
    return None


def latest_intent_status(session, case_number: str) -> str | None:  # type: ignore[no-untyped-def]
    """Newest intent state for a case (CONFIRMED/PENDING/FAILED...), or None if never closed."""
    from sqlalchemy import select

    from trace_core.audit.models import INTENT_CONFIRMED, INTENT_FAILED, AnchorIntentModel

    row = session.scalar(
        select(AnchorIntentModel)
        .where(AnchorIntentModel.case_number == case_number)
        .order_by(AnchorIntentModel.created_at.desc(), AnchorIntentModel.seq.desc())
    )
    if row is None:
        return None
    if row.status == INTENT_FAILED:
        return f"FAILED ({row.failure_code or 'unknown'})"
    if row.status == INTENT_CONFIRMED:
        return "CONFIRMED"
    return f"PENDING (attempts={row.attempt_count})"


def _publish_one(session, intent, extra_sinks: list[str] | None) -> None:  # type: ignore[no-untyped-def]
    """Sign, write locally, fan out to sinks. Marks CONFIRMED only when all land."""
    from trace_core.audit.models import INTENT_CONFIRMED, INTENT_FAILED
    from trace_core.audit.signing import sign_bytes
    from trace_core.core.canonical import canonical_json
    from trace_core.core.clock import now_utc
    from trace_core.core.fs import ensure_dir

    intent.attempt_count += 1
    intent.last_attempt_at = now_utc()
    session.flush()
    payload = {
        "case": intent.case_number,
        "last_seq": intent.seq,
        "last_chain": intent.chain_hash,
        "anchored_at": canonical_ts(now_utc()),
        "spec": SPEC_VERSION,
    }
    key_id, signature = sign_bytes(canonical_json(payload))
    envelope = {**payload, "key_id": key_id, "signature": signature}
    body = json.dumps(envelope, indent=2)
    try:
        path = anchor_path(intent.case_number, intent.seq)
        atomic_write_lines(path, [body])
        for sink in extra_sinks or []:
            sink_path = ensure_dir(sink) / path.name
            atomic_write_lines(sink_path, [body])
    except Exception as exc:
        intent.status = INTENT_FAILED
        intent.failure_code = f"{type(exc).__name__}: {exc}"[:255]
        session.flush()
        return
    intent.status = INTENT_CONFIRMED
    intent.confirmed_at = now_utc()
    intent.failure_code = None
    session.flush()


_FAILED_RETRY_COOLDOWN_HOURS = 24


def _failed_retry_due(intent) -> bool:  # type: ignore[no-untyped-def]
    """Failed intents retry at most once per cooldown window.

    Unwritable disks used to cost a full write attempt on every close, forever.
    The cooldown bounds that cost while preserving self-healing: fix the disk
    and the next close past the window confirms the intent.
    """
    from datetime import timedelta

    from trace_core.audit.models import INTENT_FAILED
    from trace_core.core.canonical import coerce_utc
    from trace_core.core.clock import now_utc

    if intent.status != INTENT_FAILED:
        return True
    if intent.last_attempt_at is None:
        return True
    last = coerce_utc(intent.last_attempt_at)
    if last is None:
        return True
    return now_utc() - last >= timedelta(hours=_FAILED_RETRY_COOLDOWN_HOURS)


def publish_pending_anchors(manager, extra_sinks: list[str] | None = None) -> int:  # type: ignore[no-untyped-def]
    """Publish every pending intent. Returns confirmed count. Never raises."""
    from sqlalchemy import select

    from trace_core.audit.models import INTENT_CONFIRMED, AnchorIntentModel

    confirmed = 0
    try:
        with manager.session() as session:
            pending = session.scalars(
                select(AnchorIntentModel)
                .where(AnchorIntentModel.status != INTENT_CONFIRMED)
                .order_by(AnchorIntentModel.created_at.asc())
            ).all()
            ids = [row.id for row in pending]
        for row_id in ids:
            try:
                with manager.session() as session:
                    intent = session.get(AnchorIntentModel, row_id)
                    if intent is None or intent.status == INTENT_CONFIRMED:
                        continue
                    if not _failed_retry_due(intent):
                        continue
                    _publish_one(session, intent, extra_sinks)
                    session.commit()
                    if intent.status == INTENT_CONFIRMED:
                        confirmed += 1
            except Exception as exc:
                import structlog

                structlog.get_logger().warning("Anchor publish failed", error=str(exc))
    except Exception as exc:
        import structlog

        structlog.get_logger().warning("Anchor publisher unavailable", error=str(exc))
    return confirmed
