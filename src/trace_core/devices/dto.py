"""Device DTOs: presentation contracts over the frozen value objects [D25].

The domain objects are already validated, frozen and canonical-serialisable, so these
add no validation of their own. They exist so the CLI, shell and TUI share one shape,
and `BaseDto.extra = forbid` means a typo in a payload field is rejected rather than
silently dropped.
"""

from datetime import datetime

from pydantic import Field

from trace_core.core.dto import BaseDto
from trace_core.devices.domain import (
    DeviceFingerprint,
    DeviceInfo,
    DeviceInspection,
    DeviceInterface,
    DeviceKind,
    GateCheck,
    ProtectionCheck,
    WpVerdict,
)


class DeviceInfoDto(BaseDto):
    node: str
    kind: DeviceKind
    requires_real_hardware_opt_in: bool
    size_bytes: int | None = None
    model_hint: str | None = None

    @classmethod
    def from_domain(cls, device: DeviceInfo) -> "DeviceInfoDto":
        return cls(
            node=device.node,
            kind=device.kind,
            requires_real_hardware_opt_in=device.requires_real_hardware_opt_in,
            size_bytes=device.size_bytes,
            model_hint=device.model_hint,
        )


class FingerprintDto(BaseDto):
    serial: str
    model: str
    capacity_bytes: int
    firmware: str | None = None
    interface: DeviceInterface
    wwn: str | None = None
    source: str

    @classmethod
    def from_domain(cls, fingerprint: DeviceFingerprint) -> "FingerprintDto":
        return cls(
            serial=fingerprint.serial.value,
            model=fingerprint.model,
            capacity_bytes=fingerprint.capacity_bytes,
            firmware=fingerprint.firmware,
            interface=fingerprint.interface,
            wwn=fingerprint.wwn,
            source=fingerprint.source,
        )


class InspectionDto(BaseDto):
    """A capture, not a stored record.

    Deliberately not `BaseResponseDto`: a `DeviceInspection` carries no database
    identity, and inheriting that base would oblige the caller to invent a UUID that
    matches no persisted row. The observation's own reference is its ledger event.
    """

    device: DeviceInfoDto
    fingerprint: FingerprintDto
    inspected_at: datetime

    @classmethod
    def from_domain(cls, inspection: DeviceInspection) -> "InspectionDto":
        return cls(
            device=DeviceInfoDto.from_domain(inspection.device),
            fingerprint=FingerprintDto.from_domain(inspection.fingerprint),
            inspected_at=inspection.inspected_at,
        )


class ProtectionCheckDto(BaseDto):
    name: str
    result: str
    detail: str | None = None

    @classmethod
    def from_domain(cls, check: ProtectionCheck) -> "ProtectionCheckDto":
        return cls(name=check.name, result=check.result, detail=check.detail)


class WpCheckDto(BaseDto):
    verdict: WpVerdict
    platform: str
    adapter_version: str
    checked_at: datetime
    unknown_cause: str | None = None
    checks: list[ProtectionCheckDto] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, gate: GateCheck) -> "WpCheckDto":
        cause = gate.evidence.unknown_cause
        return cls(
            verdict=gate.verdict,
            platform=gate.evidence.platform,
            adapter_version=gate.evidence.adapter_version,
            checked_at=gate.checked_at,
            unknown_cause=None if cause is None else cause.value,
            checks=[ProtectionCheckDto.from_domain(check) for check in gate.evidence.checks],
        )
