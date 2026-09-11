"""Common application error hierarchy."""

from typing import Any


class ApplicationError(Exception):
    """Base exception for application services."""

    pass


class NotFoundError(ApplicationError):
    """Raised when an expected resource is not found."""

    def __init__(self, resource_type: str, identifier: Any):
        super().__init__(f"{resource_type} '{identifier}' not found.")
        self.resource_type = resource_type
        self.identifier = identifier


class ConflictError(ApplicationError):
    """Raised when a resource state conflicts with an operation (e.g. duplicate key)."""

    pass


class StateTransitionError(ApplicationError):
    """Raised when an operation violates lifecycle state transitions."""

    pass
