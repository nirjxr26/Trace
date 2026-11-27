"""Lazy structured logging setup."""

from __future__ import annotations

import sys
from typing import Any


def configure_logging() -> None:
    import structlog

    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))


def get_logger() -> Any:
    configure_logging()
    import structlog

    return structlog.get_logger()


class _LazyLogger:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_logger(), name)


logger = _LazyLogger()
