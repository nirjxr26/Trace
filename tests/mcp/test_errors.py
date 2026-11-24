from trace_core.core.errors import ApplicationError, AuthorizationError, ConflictError, NotFoundError
from trace_core.mcp.errors import map_error
from trace_core.updates.errors import UpdateInProgressError


def test_error_codes() -> None:
    assert map_error(AuthorizationError("no"), "cid")["code"] == "FORBIDDEN"
    assert map_error(NotFoundError("Case", "x"), "cid")["code"] == "NOT_FOUND"
    assert map_error(ConflictError("Case", "number", "x"), "cid")["code"] == "CONFLICT"
    assert map_error(UpdateInProgressError("wait"), "cid")["code"] == "UPDATE_IN_PROGRESS"
    assert (
        map_error(ApplicationError("constraint: cases_number_key"), "cid")["message"] != "constraint: cases_number_key"
    )


def test_unexpected_error_has_correlation_id() -> None:
    payload = map_error(RuntimeError("boom"), "abc123")
    assert payload["code"] == "INTERNAL"
    assert payload["correlation_id"] == "abc123"
    assert "boom" not in payload["message"]
