import re
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trace_core.cases.domain import CaseStatus
from trace_core.core.domain import DomainError, require_utc


class ImagingState(StrEnum):
    PREPARING = "PREPARING"
    ACQUIRING = "ACQUIRING"
    VERIFYING = "VERIFYING"
    BYTE_VERIFIED = "BYTE_VERIFIED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class ImagingSourceKind(StrEnum):
    FILE = "FILE"
    OS = "OS"


class ImagingFailure(StrEnum):
    INTERRUPTED = "INTERRUPTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    DESTINATION_UNAVAILABLE = "DESTINATION_UNAVAILABLE"
    DESTINATION_EXISTS = "DESTINATION_EXISTS"
    DESTINATION_WRITE_FAILED = "DESTINATION_WRITE_FAILED"
    READBACK_MISMATCH = "READBACK_MISMATCH"
    MANIFEST_FAILED = "MANIFEST_FAILED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ImagingTransitionError(DomainError):
    pass


class ImagingSourceUnsupportedError(DomainError):
    pass


class ImagingAcquisitionError(DomainError):
    pass


class ImagingSourceUnavailableError(ImagingAcquisitionError):
    pass


class ImagingSourceChangedError(ImagingAcquisitionError):
    pass


class ImagingSourceReadError(ImagingAcquisitionError):
    pass


class ImagingInterruptedError(ImagingAcquisitionError):
    pass


class ImagingDestinationError(ImagingAcquisitionError):
    pass


class ImagingDestinationExistsError(ImagingDestinationError):
    pass


class ImagingReadbackError(ImagingAcquisitionError):
    pass


class ImagingPublishError(ImagingAcquisitionError):
    pass


class ImagingBadRegion(BaseModel):
    model_config = ConfigDict(frozen=True)

    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    cause: str


class ImagingPiecewise(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithm: Literal["SHA-256"] = "SHA-256"
    chunk_size: int = Field(gt=0)
    count: int = Field(ge=0)
    hashes: tuple[str, ...] = ()


class ImagingEncryption(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithm: Literal["AES-256-GCM/PBKDF2-SHA256-600k"]
    sealed_relpath: str
    plaintext_sha256: str
    sealed_size_bytes: int = Field(ge=0)


class ImagingSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    node: str
    kind: ImagingSourceKind
    serial: str
    model: str
    size_bytes: int = Field(ge=0)
    protection: str
    adapter: str
    synthetic: bool
    inspected_at: datetime

    @field_validator("inspected_at")
    @classmethod
    def validate_inspected_at(cls, value: datetime) -> datetime:
        result = require_utc(value)
        if result is None:
            raise ImagingTransitionError("A source inspection requires a UTC timestamp.")
        return result


class ImagingOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    case_id: UUID
    case_number: str
    state: ImagingState
    created_at: datetime
    created_by: str
    updated_at: datetime | None = None
    source_node: str | None = None
    source_kind: ImagingSourceKind | None = None
    source_serial: str | None = None
    source_model: str | None = None
    source_size_bytes: int | None = None
    source_protection: str | None = None
    source_adapter: str | None = None
    source_inspected_at: datetime | None = None
    expected_bytes: int | None = None
    copied_bytes: int | None = None
    acquisition_sha256: str | None = None
    readback_sha256: str | None = None
    image_relpath: str | None = None
    manifest_relpath: str | None = None
    failure_category: ImagingFailure | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @field_validator("created_at", "updated_at", "source_inspected_at", "started_at", "finished_at")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        result = require_utc(value)
        if result is None:
            raise ImagingTransitionError("An imaging operation requires UTC timestamps.")
        return result


class ImagingManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_version: Literal["trace-imaging-manifest-v1"] = "trace-imaging-manifest-v1"
    format: Literal["RAW"] = "RAW"
    operation_id: UUID
    case_id: UUID
    case_number: str
    source: ImagingSource
    expected_bytes: int = Field(ge=0)
    copied_bytes: int = Field(ge=0)
    acquisition_sha256: str
    readback_sha256: str
    image_relpath: str
    piecewise: ImagingPiecewise
    bad_regions: tuple[ImagingBadRegion, ...] = ()
    encryption: ImagingEncryption | None = None
    created_at: datetime
    finished_at: datetime
    tool_version: str
    byte_integrity: Literal["verified"] = "verified"
    limitations: tuple[str, ...] = (
        "Byte verification proves only that the destination matches the bytes returned by the source reader.",
        "It does not prove source authenticity, source stability, physical write protection, or admissibility.",
        "This manifest is not a custody record and is not a substitute for an approved write blocker.",
        "If bad_regions is non-empty, unreadable source regions were zero-filled; their original bytes were not recovered.",
    )

    @field_validator("created_at", "finished_at")
    @classmethod
    def validate_manifest_utc(cls, value: datetime) -> datetime:
        result = require_utc(value)
        if result is None:
            raise ImagingTransitionError("An imaging manifest requires UTC timestamps.")
        return result


def require_eligible_case(status: CaseStatus, is_deleted: bool) -> None:
    if is_deleted or status not in {CaseStatus.OPEN, CaseStatus.UNDER_REVIEW}:
        raise ImagingTransitionError("Imaging requires an open or under-review, non-archived case.")


def require_fixture_source(kind: ImagingSourceKind) -> None:
    if kind is not ImagingSourceKind.FILE:
        raise ImagingSourceUnsupportedError(
            "Physical device acquisition is not enabled. This build acquires fixture files only."
        )


_VALID_TRANSITIONS: dict[ImagingState, set[ImagingState]] = {
    ImagingState.PREPARING: {ImagingState.ACQUIRING, ImagingState.INTERRUPTED, ImagingState.FAILED},
    ImagingState.ACQUIRING: {ImagingState.VERIFYING, ImagingState.INTERRUPTED, ImagingState.FAILED},
    ImagingState.VERIFYING: {
        ImagingState.BYTE_VERIFIED,
        ImagingState.INTERRUPTED,
        ImagingState.FAILED,
        ImagingState.QUARANTINED,
    },
    ImagingState.BYTE_VERIFIED: set(),
    ImagingState.INTERRUPTED: {ImagingState.ACQUIRING},
    ImagingState.FAILED: set(),
    ImagingState.QUARANTINED: set(),
}


def can_transition(current: ImagingState, target: ImagingState) -> bool:
    return (
        isinstance(current, ImagingState) and isinstance(target, ImagingState) and target in _VALID_TRANSITIONS[current]
    )


def require_transition(
    current: ImagingState,
    target: ImagingState,
    *,
    expected_bytes: int | None = None,
    copied_bytes: int | None = None,
    readback_bytes: int | None = None,
    acquisition_sha256: str | None = None,
    readback_sha256: str | None = None,
) -> None:
    if not isinstance(current, ImagingState) or not isinstance(target, ImagingState):
        raise ImagingTransitionError("Imaging states must be ImagingState values.")
    if not can_transition(current, target):
        raise ImagingTransitionError(f"Illegal imaging transition from {current.value} to {target.value}")
    if target is ImagingState.BYTE_VERIFIED and (
        expected_bytes is None
        or expected_bytes < 0
        or copied_bytes != expected_bytes
        or readback_bytes != expected_bytes
        or acquisition_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", acquisition_sha256) is None
        or readback_sha256 != acquisition_sha256
    ):
        raise ImagingTransitionError("Byte verification requires matching lengths and SHA-256 digests.")
