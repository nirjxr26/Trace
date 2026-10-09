"""Device observation persistence [D3], [D29].

One repository contract plus its SQLAlchemy implementation, matching the
`CaseRepository` shape. Comparison semantics stay out of SQL so the resume guard
in Subpart 5 has one testable home in the service.
"""

import uuid
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from trace_core.core.canonical import canonical_json
from trace_core.core.database.repository import SqlAlchemyBaseRepository
from trace_core.core.domain import bound_actor
from trace_core.devices.domain import (
    DeviceFingerprint,
    DeviceInspection,
    DeviceInterface,
    GateCheck,
    ObservedSerial,
    ProtectionEvidence,
    StoredObservation,
    UnknownCause,
    WpVerdict,
)
from trace_core.devices.models import DeviceFingerprintModel


class DeviceRepository(Protocol):
    def save_observation(self, inspection: DeviceInspection, actor: str, gate: GateCheck | None = None) -> None: ...

    def latest_for(self, serial: str) -> DeviceFingerprint | None: ...

    def history_for(self, serial: str, limit: int = 10) -> list[DeviceFingerprint]: ...

    def latest_observation(self, serial: str) -> StoredObservation | None:
        """The newest row for one identity, with its verdict and evidence intact."""
        ...

    def observation_history(self, serial: str, limit: int = 10) -> list[StoredObservation]:
        """Newest-first rows including the gate outcome of each."""
        ...


class SqlAlchemyDeviceRepository(
    SqlAlchemyBaseRepository[DeviceFingerprintModel, DeviceFingerprint, UUID], DeviceRepository
):
    """Append-only observation store. No upsert: history is the point [D3]."""

    def __init__(self, session: Session):
        super().__init__(session, DeviceFingerprintModel)

    def _to_domain(self, model: DeviceFingerprintModel) -> DeviceFingerprint:
        return DeviceFingerprint(
            serial=ObservedSerial(value=model.serial),
            model=model.model,
            capacity_bytes=model.capacity_bytes,
            firmware=model.firmware,
            interface=DeviceInterface(model.interface),
            wwn=model.wwn,
            source=cast(Literal["os", "smartctl", "synthetic"], model.source),
        )

    def _to_observation(self, model: DeviceFingerprintModel) -> StoredObservation:
        """Rebuild the full stored row, gate outcome included.

        The verdict, cause and evidence columns were written by `save_observation` and
        read by nothing; `_to_domain` cannot carry them because `DeviceFingerprint` has no
        field for them. This is the one read path that keeps them.
        """
        return StoredObservation(
            node=model.node,
            fingerprint=self._to_domain(model),
            inspected_at=model.inspected_at,
            inspected_by=model.inspected_by,
            verdict=None if model.verdict is None else WpVerdict(model.verdict),
            unknown_cause=None if model.unknown_cause is None else UnknownCause(model.unknown_cause),
            evidence=_evidence_from_json(model.evidence),
        )

    def _to_model(self, entity: DeviceFingerprint) -> DeviceFingerprintModel:
        raise NotImplementedError("observations are written through save_observation, never constructed from an entity")

    def _update_model(self, model: DeviceFingerprintModel, entity: DeviceFingerprint) -> None:
        raise NotImplementedError("observations are append-only; a re-inspection appends a new row [D3]")

    def save_observation(self, inspection: DeviceInspection, actor: str, gate: GateCheck | None = None) -> None:
        fp = inspection.fingerprint
        self.session.add(
            DeviceFingerprintModel(
                id=uuid.uuid4(),
                node=inspection.device.node,
                serial=fp.serial.value,
                model=fp.model,
                capacity_bytes=fp.capacity_bytes,
                firmware=fp.firmware,
                interface=str(fp.interface),
                wwn=fp.wwn,
                source=fp.source,
                verdict=None if gate is None else str(gate.verdict),
                unknown_cause=None
                if gate is None or gate.evidence.unknown_cause is None
                else str(gate.evidence.unknown_cause),
                evidence=None if gate is None else canonical_json(gate.evidence.model_dump(mode="json")),
                inspected_at=inspection.inspected_at,
                inspected_by=bound_actor(actor),
            )
        )

    def _observations(self, serial: str, limit: int) -> Select[tuple[DeviceFingerprintModel]]:
        """Newest-first rows for one identity. Single source for latest and history reads."""
        return (
            select(DeviceFingerprintModel)
            .where(DeviceFingerprintModel.serial == serial)
            .order_by(DeviceFingerprintModel.inspected_at.desc())
            .limit(limit)
        )

    def latest_for(self, serial: str) -> DeviceFingerprint | None:
        row = self.session.scalars(self._observations(serial, 1)).first()
        return None if row is None else self._to_domain(row)

    def history_for(self, serial: str, limit: int = 10) -> list[DeviceFingerprint]:
        if limit <= 0:
            return []
        return [self._to_domain(row) for row in self.session.scalars(self._observations(serial, limit)).all()]

    def latest_observation(self, serial: str) -> StoredObservation | None:
        row = self.session.scalars(self._observations(serial, 1)).first()
        return None if row is None else self._to_observation(row)

    def observation_history(self, serial: str, limit: int = 10) -> list[StoredObservation]:
        if limit <= 0:
            return []
        return [self._to_observation(row) for row in self.session.scalars(self._observations(serial, limit)).all()]


def _evidence_from_json(raw: str | None) -> ProtectionEvidence | None:
    """Parse a stored evidence payload back into the value object.

    Returns None for anything unparseable rather than raising: a row written by an older
    adapter, or truncated, must not make the whole history unreadable.
    """
    if not raw:
        return None
    try:
        return ProtectionEvidence.model_validate_json(raw)
    except ValueError:
        return None
