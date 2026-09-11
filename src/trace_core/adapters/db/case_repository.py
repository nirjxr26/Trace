"""Backward-compatible case repository export."""

from trace_core.adapters.db.repositories.case import SqlAlchemyCaseRepository

__all__ = ["SqlAlchemyCaseRepository"]
