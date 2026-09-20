from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class GateDecision(StrEnum):
    ALLOWED = "ALLOWED"
    ACTIVE_OPERATION = "ACTIVE_OPERATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class UpdateGateContext:
    target_version: str | None = None
    transaction_id: str | None = None


ActiveProbe = Callable[[UpdateGateContext | None], bool | None]


class ForensicOperationGate:
    def __init__(self, active_probe: ActiveProbe | None = None) -> None:
        self._probe = active_probe

    def can_install_update(self, context: UpdateGateContext | None = None) -> GateDecision:
        if self._probe is None:
            return GateDecision.ALLOWED
        try:
            result = self._probe(context)
        except Exception:
            return GateDecision.UNKNOWN
        if result is True:
            return GateDecision.ACTIVE_OPERATION
        if result is None:
            return GateDecision.UNKNOWN
        return GateDecision.ALLOWED
