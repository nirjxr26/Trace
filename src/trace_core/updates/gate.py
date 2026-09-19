from enum import StrEnum


class GateDecision(StrEnum):
    ALLOWED = "ALLOWED"
    ACTIVE_OPERATION = "ACTIVE_OPERATION"
    UNKNOWN = "UNKNOWN"


class ForensicOperationGate:
    def can_install_update(self) -> GateDecision:
        return GateDecision.ALLOWED
