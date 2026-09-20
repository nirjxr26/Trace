import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ManifestArtifact(BaseModel):
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=1, le=10_737_418_240)
    signature: str | None = None
    signing_key_id: str | None = None
    platform: str | None = Field(default=None, pattern=r"^(windows|linux|macos)$")
    arch: str | None = Field(default=None, pattern=r"^(x64|arm64)$")


class ReleaseManifest(BaseModel):
    schema_: int = Field(alias="schema", ge=1)
    product: str = Field(min_length=1, max_length=64)
    channel: str
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+([._-][a-zA-Z0-9]+)*$", max_length=64)
    release_id: str = Field(min_length=1, max_length=64)
    published_at: str | None = None
    minimum_supported_version: str | None = None
    security_update: bool
    restart_required: bool
    notes: str | None = None
    manifest_signature: str
    signing_key_id: str
    schema_min: int | None = None
    schema_target: int | None = None
    backup_required: bool = False
    backup_waiver: str | None = None
    artifacts: dict[str, ManifestArtifact]

    model_config = {"populate_by_name": True}

    @field_validator("channel")
    @classmethod
    def _channel_known(cls, value: str) -> str:
        from trace_core.updates.domain import UpdateChannel

        if not UpdateChannel.contains(value):
            raise ValueError(f"unknown release channel {value!r}")
        return value

    @model_validator(mode="after")
    def _schema_range_both_or_neither(self) -> "ReleaseManifest":
        if (self.schema_min is None) != (self.schema_target is None):
            raise ValueError("schema_min and schema_target must both be declared or both absent")
        return self


def _validate(data: dict[str, Any]) -> ReleaseManifest:
    from pydantic import ValidationError as PydanticValidationError

    from trace_core.updates.errors import UpdateVerificationError

    try:
        return ReleaseManifest.model_validate(data)
    except PydanticValidationError as e:
        details = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise UpdateVerificationError(f"invalid manifest: {details}") from e


def load_manifest(path: str | Path) -> ReleaseManifest:
    from trace_core.updates.errors import UpdateVerificationError

    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise UpdateVerificationError(f"unreadable manifest: {e}") from e
    return load_manifest_bytes(data)


def load_manifest_dict(data: dict[str, Any]) -> ReleaseManifest:
    return _validate(data)


def load_manifest_bytes(data: bytes) -> ReleaseManifest:
    from trace_core.updates.errors import UpdateVerificationError

    if len(data) > 1_048_576:
        raise UpdateVerificationError("manifest too large")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise UpdateVerificationError(f"unreadable manifest: {e}") from e
    return _validate(parsed)
