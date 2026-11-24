import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from trace_core.audit.domain import AuditAction
from trace_core.cases.domain import CaseStatus
from trace_core.core.dto import DEFAULT_PAGE_SIZE
from trace_core.mcp.constants import (
    CONFIRM_MIGRATE,
    CONFIRM_OVERWRITE,
    CONFIRM_RECOVERY,
    CONFIRM_UNINSTALL,
)
from trace_core.mcp.errors import ToolFailure

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusArgs(StrictModel):
    pass


class IdentifierArgs(StrictModel):
    identifier: str = Field(min_length=1, max_length=200)


class CaseListArgs(StrictModel):
    status: CaseStatus | None = None
    search: str | None = Field(default=None, max_length=200)
    include_deleted: bool = False
    deleted_only: bool = False
    recent: bool = False
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AuditListArgs(StrictModel):
    case_number: str | None = Field(default=None, max_length=100)
    action: AuditAction | None = None
    actor: str | None = Field(default=None, max_length=255)
    device_serial: str | None = Field(default=None, max_length=255)
    search: str | None = Field(default=None, max_length=200)
    before_seq: int | None = Field(default=None, ge=1)
    after_seq: int | None = Field(default=None, ge=1)
    detail: str = Field(default="summary", pattern="^(summary|full)$")
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SeqArgs(StrictModel):
    seq: int = Field(ge=1)


class DeviceListArgs(StrictModel):
    kind: str = Field(default="all", pattern="^(all|FILE|OS)$")


class DeviceHistoryArgs(StrictModel):
    serial: str = Field(min_length=1, max_length=255)
    limit: int = Field(default=10, ge=1, le=50)


class DeviceLinksArgs(StrictModel):
    case_number: str | None = Field(default=None, max_length=100)
    node: str | None = Field(default=None, max_length=4096)
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def exactly_one(self) -> "DeviceLinksArgs":
        if (self.case_number is None) == (self.node is None):
            raise ValueError("Provide exactly one of case_number or node.")
        return self


class CaseCreateArgs(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    lead_examiner: str = Field(min_length=1, max_length=255)
    number: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    confirm: str | None = None

    @model_validator(mode="after")
    def confirm_number(self) -> "CaseCreateArgs":
        if self.number is not None and self.confirm != self.number:
            raise ValueError("confirm must repeat the requested case number.")
        return self


class CaseUpdateArgs(StrictModel):
    identifier: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    lead_examiner: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = Field(default=None, max_length=50)
    reason: str = Field(default="", max_length=2000)


class CaseReviewArgs(StrictModel):
    identifier: str = Field(min_length=1, max_length=200)
    resume: bool = False
    reason: str = Field(default="", max_length=2000)


class CaseCloseArgs(StrictModel):
    identifier: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def confirm_identifier(self) -> "CaseCloseArgs":
        if self.confirm != self.identifier:
            raise ValueError("confirm must repeat the case number or UUID.")
        return self


class CaseDeleteArgs(StrictModel):
    identifier: str = Field(min_length=1, max_length=200)
    confirm: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def confirm_identifier(self) -> "CaseDeleteArgs":
        if self.confirm != self.identifier:
            raise ValueError("confirm must repeat the case number or UUID.")
        return self


class DeviceMutationArgs(StrictModel):
    node: str = Field(min_length=1, max_length=4096)
    case_number: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=255)
    confirm: str | None = None

    @model_validator(mode="after")
    def confirm_case(self) -> "DeviceMutationArgs":
        if self.confirm != self.case_number:
            raise ValueError("confirm must repeat the case number.")
        return self


class BundleArgs(StrictModel):
    filename: str = Field(min_length=1, max_length=128)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if not _FILENAME_RE.fullmatch(value) or value in {".", ".."} or value.endswith(".."):
            raise ValueError("filename must be a simple file name without separators or traversal.")
        return value


class AuditExportArgs(BundleArgs):
    encrypt: bool = False
    overwrite: bool = False
    confirm: str | None = None

    @model_validator(mode="after")
    def confirm_overwrite(self) -> "AuditExportArgs":
        if self.overwrite and self.confirm != CONFIRM_OVERWRITE:
            raise ValueError(f"confirm must be '{CONFIRM_OVERWRITE}' when overwrite is true.")
        return self


class AuditDecryptArgs(BundleArgs):
    overwrite: bool = False
    confirm: str | None = None

    @model_validator(mode="after")
    def confirm_overwrite(self) -> "AuditDecryptArgs":
        if self.overwrite and self.confirm != CONFIRM_OVERWRITE:
            raise ValueError(f"confirm must be '{CONFIRM_OVERWRITE}' when overwrite is true.")
        return self


class KeyArgs(StrictModel):
    label: str = Field(default="default", min_length=1, max_length=64)
    confirm: str | None = None


class KeyRotateArgs(KeyArgs):
    confirm: str = Field(min_length=1, max_length=128)


class UpdateInstallArgs(StrictModel):
    target_version: str = Field(min_length=1, max_length=64)
    confirm: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def confirm_target(self) -> "UpdateInstallArgs":
        if self.confirm != self.target_version:
            raise ValueError("confirm must repeat target_version.")
        return self


class ConfirmArgs(StrictModel):
    confirm: str = Field(min_length=1, max_length=64)


class UninstallArgs(ConfirmArgs):
    @field_validator("confirm")
    @classmethod
    def check(cls, value: str) -> str:
        if value != CONFIRM_UNINSTALL:
            raise ValueError(f"confirm must be '{CONFIRM_UNINSTALL}'.")
        return value


class RecoveryArgs(ConfirmArgs):
    @field_validator("confirm")
    @classmethod
    def check(cls, value: str) -> str:
        if value != CONFIRM_RECOVERY:
            raise ValueError(f"confirm must be '{CONFIRM_RECOVERY}'.")
        return value


class DbMigrateArgs(ConfirmArgs):
    @field_validator("confirm")
    @classmethod
    def check(cls, value: str) -> str:
        if value != CONFIRM_MIGRATE:
            raise ValueError(f"confirm must be '{CONFIRM_MIGRATE}'.")
        return value


def checked[StrictT: StrictModel](model: type[StrictT], values: dict[str, Any]) -> StrictT:
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise ToolFailure("VALIDATION", "The tool arguments are invalid.") from exc
