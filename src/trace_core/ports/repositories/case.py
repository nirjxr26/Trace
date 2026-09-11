"""Case repository port interface."""

import uuid
from typing import Protocol

from trace_core.domain.models.case import Case, CaseStatus
from trace_core.ports.repositories.base import BaseRepository


class CaseRepository(BaseRepository[Case, uuid.UUID], Protocol):
    """Protocol for Case persistence operations."""

    def get_by_number(self, number: str) -> Case | None:
        """Fetch a case by its human-readable case number."""
        ...

    def list_cases(
        self,
        status: CaseStatus | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ) -> list[Case]:
        """List cases with optional status filter and search query."""
        ...

    def resolve(self, identifier: str) -> Case | None:
        """Dual-key lookup: resolve by UUID or human-readable case number."""
        ...

    def soft_delete(self, case_id: uuid.UUID) -> bool:
        """Mark a case as deleted/archived."""
        ...

    def purge(self, case_id: uuid.UUID) -> bool:
        """Permanently remove a case record."""
        ...

    def get_next_sequence_number(self, year: int | None = None) -> str:
        """Generate next monotonic case sequence number."""
        ...
