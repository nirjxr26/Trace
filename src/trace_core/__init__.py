"""Trace — Forensic Data Imaging & Retrieval Tool."""

import sys

import structlog

__version__ = "0.3.2"

structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
