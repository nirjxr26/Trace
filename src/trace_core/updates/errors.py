from trace_core.core.errors import ApplicationError


class UpdateError(ApplicationError):
    pass


class UpdateVerificationError(UpdateError):
    pass


class UpdatePolicyBlockedError(UpdateError):
    pass


class UpdateNotAvailableError(UpdateError):
    pass


class UpdateNetworkError(UpdateError):
    """Transport failure fetching manifests. Distinct from trust failures for UX routing."""

    pass


class UpdateInProgressError(UpdateError):
    pass


class MigrationCompatibilityError(UpdateError):
    pass


class RecoveryError(UpdateError):
    pass


class RecoveryBlockedError(RecoveryError):
    pass
