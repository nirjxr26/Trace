from trace_core.core.errors import ApplicationError


class UpdateError(ApplicationError):
    pass


class UpdateVerificationError(UpdateError):
    pass


class UpdatePolicyBlockedError(UpdateError):
    pass


class UpdateNotAvailableError(UpdateError):
    pass


class UpdateInProgressError(UpdateError):
    pass


class MigrationCompatibilityError(UpdateError):
    pass


class RecoveryError(UpdateError):
    pass
