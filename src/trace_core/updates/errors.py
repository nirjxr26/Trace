"""Update-pipeline error taxonomy.

Every subclass below is a failure class the CLI routes on. `_update_error` in
`core/cli/error_handler.py` maps them to distinct exit codes and remediation text, so
which class a caller raises is a UX decision, not a stylistic one. That mapping was
undocumented, which is how a mistyped channel ended up rendered as "Update Verification
Failed" (H-24) and a failed migration ended up filed as a health failure (H-13).

Rules for adding one:
- Transport or fetch failures -> UpdateNetworkError (exit 1). A network fault
  is never a trust failure, and a trust failure is never a network fault.
- Trust or authenticity failure -> UpdateVerificationError (exit 11). Never a network
  error: the operator must not be told to retry a URL that was just refused.
- Policy or platform refusal, not a fault -> UpdatePolicyBlockedError (exit 14).
- Recoverable-state problems -> RecoveryError; unrecoverable -> RecoveryBlockedError.
- Only MigrationCompatibilityError may mean the database schema is incompatible.
"""

from trace_core.core.errors import ApplicationError


class UpdateError(ApplicationError):
    """Base for every update-pipeline failure."""


class UpdateVerificationError(UpdateError):
    """Signature, hash, or trust-anchor failure. Installation refused."""


class UpdatePolicyBlockedError(UpdateError):
    """Refused by policy: wrong channel, unsupported platform, deferred, or bypassed."""


class UpdateNotAvailableError(UpdateError):
    """No newer release than the installed one. Not a fault."""


class UpdateNetworkError(UpdateError):
    """Transport failure fetching manifests. Distinct from trust failures for UX routing."""


class UpdateInProgressError(UpdateError):
    """Another update transaction owns migration, or the marker is unreadable."""


class MigrationCompatibilityError(UpdateError):
    """Database schema is outside the release's declared min/target bounds."""


class RecoveryError(UpdateError):
    """A recoverable failed-update state was found and could not be cleared as-is."""


class RecoveryBlockedError(RecoveryError):
    """Recovery needs operator action; retrying automatically cannot clear it."""
