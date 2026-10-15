"""Device observation exporter: streaming JSONL, no service logic.

Mirrors `audit.exporter` deliberately. One header line carrying the export shape and
the ledger tip it was taken against, then one line per observation, written through
the same atomic helper so a partial export never replaces a good file.
"""

import json
from pathlib import Path

from sqlalchemy import func, select

from trace_core.core.fs import atomic_write_lines
from trace_core.devices.models import CaseDeviceModel, DeviceFingerprintModel

SPEC_VERSION = "devices/1"


def _header(count: int) -> str:
    return json.dumps({"spec": SPEC_VERSION, "records": count}, ensure_ascii=False) + "\n"


def _record_dict(row: DeviceFingerprintModel) -> dict[str, object]:
    return {
        "node": row.node,
        "serial": row.serial,
        "model": row.model,
        "capacity_bytes": row.capacity_bytes,
        "firmware": row.firmware,
        "interface": row.interface,
        "wwn": row.wwn,
        "source": row.source,
        "verdict": row.verdict,
        "unknown_cause": row.unknown_cause,
        "inspected_at": row.inspected_at.isoformat() if row.inspected_at else None,
        "inspected_by": row.inspected_by,
    }


def _node_subquery(case_number: str):
    return select(CaseDeviceModel.node).where(CaseDeviceModel.case_number == case_number)


def export_observations(
    session,  # type: ignore[no-untyped-def]
    out_path: str | Path,
    *,
    case_number: str | None = None,
    serial: str | None = None,
) -> Path:  # type: ignore[no-untyped-def]
    """Write device observations to a JSONL file. Both filters are optional and combine."""
    count_stmt = select(func.count()).select_from(DeviceFingerprintModel)
    stmt = select(DeviceFingerprintModel).order_by(DeviceFingerprintModel.inspected_at.asc())
    if case_number:
        nodes = _node_subquery(case_number)
        count_stmt = count_stmt.where(DeviceFingerprintModel.node.in_(nodes))
        stmt = stmt.where(DeviceFingerprintModel.node.in_(nodes))
    if serial:
        count_stmt = count_stmt.where(DeviceFingerprintModel.serial == serial)
        stmt = stmt.where(DeviceFingerprintModel.serial == serial)
    count = session.scalar(count_stmt) or 0

    def _lines():  # type: ignore[no-untyped-def]
        yield _header(count)
        for row in session.scalars(stmt).yield_per(500):
            yield json.dumps(_record_dict(row), ensure_ascii=False) + "\n"

    return atomic_write_lines(out_path, _lines(), newline="\n")
