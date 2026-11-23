import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from trace_core.mcp import MAX_RESPONSE_BYTES
from trace_core.mcp.errors import ToolFailure


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return json_safe(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ToolFailure("INTERNAL", "A naive datetime reached the MCP serialization boundary.")
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [json_safe(item) for item in value]
    return value


def size_guard(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ToolFailure(
            "RESPONSE_TOO_LARGE",
            "The result exceeds the 256 KiB MCP limit. Narrow the query with filters or pagination.",
        )
    return payload


def to_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return size_guard(json_safe(value))
    return size_guard({"items": json_safe(value)})
