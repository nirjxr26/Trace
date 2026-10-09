"""Standard CLI process exit codes."""

from typing import Final

EXIT_SUCCESS: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_UNKNOWN: Final[int] = 9
EXIT_SOURCE_WRITABLE: Final[int] = 10
# Trust failure of the update artifact itself. Distinct from EXIT_LEDGER_BROKEN, which is a
# trust failure of recorded evidence: both used to be 11, so a script could not tell a bad
# download from a broken ledger.
EXIT_VERIFY_FAILED: Final[int] = 11
# The audit ledger did not verify. Additive, so no existing code changes meaning.
EXIT_LEDGER_BROKEN: Final[int] = 17
EXIT_NOT_FOUND: Final[int] = 12
EXIT_CONFLICT: Final[int] = 13
EXIT_UPDATE_BLOCKED: Final[int] = 14
EXIT_RECOVERY_FAILED: Final[int] = 15
EXIT_RECOVERY_RETRY: Final[int] = 16
