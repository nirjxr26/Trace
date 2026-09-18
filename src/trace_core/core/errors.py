"""Standard application and domain exception hierarchy."""


class TraceError(Exception):
    """Root exception for all Trace application errors."""


class ApplicationError(TraceError):
    """Base exception for application service execution failures."""


class NotFoundError(ApplicationError):
    """Raised when an entity or resource could not be found."""

    def __init__(self, resource_type: str, identifier: str) -> None:
        super().__init__(f"{resource_type} '{identifier}' does not exist.")
        self.resource_type = resource_type
        self.identifier = identifier


class ConflictError(ApplicationError):
    """Raised when a unique constraint or domain state conflict occurs."""

    def __init__(self, resource_type: str, field: str, value: str) -> None:
        super().__init__(f"{resource_type} with {field}='{value}' already exists.")
        self.resource_type = resource_type
        self.field = field
        self.value = value


class ConcurrencyConflictError(ConflictError):
    """Raised when an optimistic concurrency version conflict occurs."""

    def __init__(
        self,
        resource_type: str,
        identifier: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        super().__init__(
            resource_type=resource_type,
            field="version",
            value=f"expected {expected_version}, found {actual_version}",
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class StateTransitionError(ApplicationError):
    """Raised when an invalid state machine transition is attempted."""

    def __init__(self, current_state: str, target_state: str, reason: str = "") -> None:
        msg = f"Cannot transition from {current_state} to {target_state}."
        if reason:
            msg = f"{msg} Reason: {reason}"
        super().__init__(msg)
        self.current_state = current_state
        self.target_state = target_state


class ValidationError(ApplicationError):
    """Raised when input data fails business rule validation."""


class AuditTamperError(ApplicationError):
    """Raised when audit chain verification detects tampering."""

    def __init__(self, message: str):
        super().__init__(message)


class AuthorizationError(ApplicationError):
    """Raised when an operator lacks the role for an action."""
