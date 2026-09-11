from typing import Protocol


class BaseRepository[EntityT, IdT](Protocol):
    """Generic structural repository interface."""

    def create(self, entity: EntityT) -> EntityT:
        """Persist a new entity."""
        ...

    def get_by_id(self, entity_id: IdT) -> EntityT | None:
        """Fetch an entity by its unique ID."""
        ...

    def list_all(self, include_deleted: bool = False) -> list[EntityT]:
        """List all entities."""
        ...

    def update(self, entity: EntityT) -> EntityT:
        """Update an existing entity."""
        ...

    def delete(self, entity_id: IdT, purge: bool = False) -> bool:
        """Delete an entity (soft-delete or purge)."""
        ...
