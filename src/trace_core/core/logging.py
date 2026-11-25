"""Lazy structured logging setup."""

from __future__ import annotations

import sys
from typing import Any

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    import structlog

    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    _configured = True


def get_logger() -> Any:
    configure_logging()
    import structlog

    return structlog.get_logger()
