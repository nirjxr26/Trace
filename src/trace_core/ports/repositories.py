"""Backward-compatible repository ports export."""

from trace_core.ports.repositories.base import BaseRepository
from trace_core.ports.repositories.case import CaseRepository

__all__ = ["BaseRepository", "CaseRepository"]
