"""Trace — Forensic Case Management & Device Inspection Tool."""

import sys

import structlog

__version__ = "0.5.0"

structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
