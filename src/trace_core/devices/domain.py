"""Device identity, classification and write-protection value objects. No I/O.

Representation is frozen Pydantic throughout [D25]: these types land in signed,
hash-committed audit payloads, and a frozen dataclass does not serialise
identically to the canonical-JSON signing path.

[ObservedSerial] is the structural half of [D13]. A serial is hardware-supplied
data and bridges lie, so it is a distinct type rather than a bare ``str``. No
signature path accepts it where an authenticated identity is required; trust is
manufactured by Trace through canonical observation, audit event, hash chain and
Ed25519 signature.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trace_core.core.domain import InvariantViolationError, require_utc, strip_controls
from trace_core.core.errors import ApplicationError

MAX_DEVICE_STRING = 512
MAX_NODE_LENGTH = 4096


class DeviceInterface(StrEnum):
    USB = "USB"
    SATA = "SATA"
    NVME = "NVME"
    SCSI = "SCSI"
    VIRTUAL = "VIRTUAL"
    UNKNOWN = "UNKNOWN"


class WpVerdict(StrEnum):
    READ_ONLY = "READ_ONLY"
    WRITABLE = "WRITABLE"
    UNKNOWN = "UNKNOWN"


class DeviceKind(StrEnum):
    FILE = "FILE"
    OS = "OS"


class UnknownCause(StrEnum):
    EACCES = "EACCES"
    IOCTL_FAILURE = "IOCTL_FAILURE"
    SYSFS_DISAGREEMENT = "SYSFS_DISAGREEMENT"
    SMARTCTL_TIMEOUT = "SMARTCTL_TIMEOUT"
    SMARTCTL_MALFORMED = "SMARTCTL_MALFORMED"
    DEVICE_DISAPPEARED = "DEVICE_DISAPPEARED"
    TOOL_MISSING = "TOOL_MISSING"
    TOOL_TOO_OLD = "TOOL_TOO_OLD"
    UNKNOWN_OTHER = "UNKNOWN_OTHER"


class DeviceError(ApplicationError):
    """Base for device-domain failures."""


class DeviceNotFoundError(DeviceError):
    """Raised when a requested device node is not present."""


class DeviceGoneError(DeviceError):
    """Raised when a device disconnects mid-read."""


class DeviceAccessDeniedError(DeviceError):
    """Raised when the OS refuses a handle."""


class FingerprintMismatchError(DeviceError):
    """Raised when a resume guard sees a different device than the original capture."""


def _bounded(value: str, limit: int = MAX_DEVICE_STRING) -> str:
    """Strip control characters and truncate at the field level [D21].

    Truncation rather than rejection: a crafted USB device must not be able to
    OOM the tool, and a hostile MODEL string is still evidence worth recording.
    """
    return strip_controls(value)[:limit]


def _utc(value: datetime) -> datetime:
    """Require an aware UTC timestamp [D30]. Naive datetimes are forbidden."""
    stamped = require_utc(value)
    if stamped is None:
        raise InvariantViolationError("All timestamps must be timezone-aware UTC.")
    return stamped


class _DeviceModel(BaseModel):
    model_config = ConfigDict(frozen=True, validate_assignment=True)


class ObservedSerial(_DeviceModel):
    """Hardware-supplied serial. Untrusted observation, never authenticated identity."""

    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str) -> str:
        return _bounded(v)


class DeviceInfo(_DeviceModel):
    """OS-presented identity. Never trusted as truth on its own."""

    node: str
    kind: DeviceKind
    requires_real_hardware_opt_in: bool
    size_bytes: int | None = Field(default=None, ge=0)
    model_hint: str | None = None

    @field_validator("node")
    @classmethod
    def validate_node(cls, v: str) -> str:
        return _bounded(v, MAX_NODE_LENGTH)

    @field_validator("model_hint")
    @classmethod
    def validate_model_hint(cls, v: str | None) -> str | None:
        return None if v is None else _bounded(v)


class DeviceFingerprint(_DeviceModel):
    """An observed identity, immutable once captured [D13]."""

    serial: ObservedSerial
    model: str
    capacity_bytes: int = Field(..., ge=0)
    firmware: str | None = None
    interface: DeviceInterface
    wwn: str | None = None
    source: Literal["os", "smartctl", "synthetic"]

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        return _bounded(v)

    @field_validator("firmware", "wwn")
    @classmethod
    def validate_optional(cls, v: str | None) -> str | None:
        return None if v is None else _bounded(v)


class ProtectionCheck(_DeviceModel):
    """One probe step, structured [D12]."""

    name: str
    result: str
    detail: str | None = None

    @field_validator("name", "result", "detail")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        return None if v is None else _bounded(v)


class ProtectionEvidence(_DeviceModel):
    """The proof behind a verdict."""

    platform: Literal["linux", "windows", "fake"]
    checks: tuple[ProtectionCheck, ...]
    adapter_version: str
    checked_at: datetime
    unknown_cause: UnknownCause | None = None

    @field_validator("adapter_version")
    @classmethod
    def validate_adapter_version(cls, v: str) -> str:
        return _bounded(v)

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at(cls, v: datetime) -> datetime:
        return _utc(v)


class DeviceInspection(_DeviceModel):
    """Identity half: what was observed."""

    device: DeviceInfo
    fingerprint: DeviceFingerprint
    inspected_at: datetime

    @field_validator("inspected_at")
    @classmethod
    def validate_inspected_at(cls, v: datetime) -> datetime:
        return _utc(v)


class GateCheck(_DeviceModel):
    """Trust half: built only by the protection probe."""

    verdict: WpVerdict
    evidence: ProtectionEvidence
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at(cls, v: datetime) -> datetime:
        return _utc(v)

    @model_validator(mode="after")
    def require_cause_when_unknown(self) -> "GateCheck":
        """[D19] An UNKNOWN verdict without a cause is not a usable record.

        'We could not tell' and 'we could not tell and it was slow' must be
        distinguishable in the audit trail, so the cause is mandatory rather than
        defaulted to UNKNOWN_OTHER.
        """
        if self.verdict is WpVerdict.UNKNOWN and self.evidence.unknown_cause is None:
            raise InvariantViolationError("An UNKNOWN write-protection verdict requires an unknown_cause.")
        return self


class DevicePreflight(_DeviceModel):
    """Inspection plus gate, reserved for Subpart 4."""

    inspection: DeviceInspection
    gate: GateCheck


class WriteProtectionError(DeviceError):
    """Raised when the source is not write-protected.

    Carries the verdict and evidence so the CLI can map it to a semantic exit
    code without re-probing.
    """

    def __init__(self, message: str, verdict: WpVerdict, evidence: ProtectionEvidence) -> None:
        super().__init__(message)
        self.verdict = verdict
        self.evidence = evidence
