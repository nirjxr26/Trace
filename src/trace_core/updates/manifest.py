import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ManifestArtifact(BaseModel):
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=1)
    signature: str | None = None
    signing_key_id: str | None = None
    platform: str | None = None
    arch: str | None = None


class ReleaseManifest(BaseModel):
    schema_: int = Field(alias="schema", ge=1)
    product: str
    channel: str
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9._-]*$")
    release_id: str
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

        if value not in (UpdateChannel.STABLE, UpdateChannel.BETA):
            raise ValueError(f"unknown release channel {value!r}")
        return value


def _validate(data: dict[str, Any]) -> ReleaseManifest:
    from pydantic import ValidationError as PydanticValidationError

    from trace_core.updates.errors import UpdateVerificationError

    try:
        return ReleaseManifest.model_validate(data)
    except PydanticValidationError as e:
        raise UpdateVerificationError(f"invalid manifest: {e.errors()[0]['msg']}") from e


def load_manifest(path: str | Path) -> ReleaseManifest:
    from trace_core.updates.errors import UpdateVerificationError

    p = Path(path)
    try:
        if p.stat().st_size > 1_048_576:
            raise UpdateVerificationError("manifest too large")
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UpdateVerificationError(f"unreadable manifest: {e}") from e
    return _validate(data)


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
