"""Standard CLI process exit codes."""

from typing import Final

EXIT_SUCCESS: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_VERIFY_FAILED: Final[int] = 11
EXIT_NOT_FOUND: Final[int] = 12
EXIT_CONFLICT: Final[int] = 13
EXIT_UPDATE_BLOCKED: Final[int] = 14
EXIT_RECOVERY_FAILED: Final[int] = 15
