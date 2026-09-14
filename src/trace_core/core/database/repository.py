"""Generic reusable SQLAlchemy repository implementation."""

from abc import ABC, abstractmethod
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from trace_core.core.domain import now_utc

ModelT = TypeVar("ModelT")
EntityT = TypeVar("EntityT")
IdT = TypeVar("IdT")


class SqlAlchemyBaseRepository[ModelT, EntityT, IdT](ABC):
    """
    Abstract base repository providing common CRUD operations.
    Subclasses define ORM-to-Domain mapping and entity-specific queries.
    """

    def __init__(self, session: Session, model_cls: type[ModelT]):
        self.session = session
        self.model_cls = model_cls

    @abstractmethod
    def _to_domain(self, model: ModelT) -> EntityT:
        """Convert ORM model to domain entity."""
        raise NotImplementedError

    @abstractmethod
    def _to_model(self, entity: EntityT) -> ModelT:
        """Convert domain entity to ORM model."""
        raise NotImplementedError

    @abstractmethod
    def _update_model(self, model: ModelT, entity: EntityT) -> None:
        """Apply mutable fields from entity onto ORM model."""
        raise NotImplementedError

    def create(self, entity: EntityT) -> EntityT:
        """Persist a new entity."""
        model = self._to_model(entity)
        self.session.add(model)
        self.session.flush()
        return self._to_domain(model)

    def get_by_id(self, entity_id: IdT) -> EntityT | None:
        """Fetch entity by primary key."""
        stmt = select(self.model_cls).where(getattr(self.model_cls, "id") == entity_id)
        model = self.session.scalar(stmt)
        return self._to_domain(model) if model else None

    def update(self, entity: EntityT) -> EntityT:
        """Update an existing entity."""
        entity_id = getattr(entity, "id", None)
        if entity_id is None:
            raise ValueError("Cannot update entity without an ID.")

        stmt = select(self.model_cls).where(getattr(self.model_cls, "id") == entity_id)
        model = self.session.scalar(stmt)
        if not model:
            raise ValueError(f"{self.model_cls.__name__} with id {entity_id} does not exist.")

        self._update_model(model, entity)
        if hasattr(model, "updated_at"):
            setattr(model, "updated_at", now_utc())

        self.session.flush()
        return self._to_domain(model)

    def delete(self, entity_id: IdT, purge: bool = False) -> bool:
        """Permanently delete a row by primary key.

        Forensic policy lives in feature repositories (e.g. soft-delete/archive).
        Do not add soft-delete magic here; callers must implement retention explicitly.
        """
        _ = purge
        stmt = select(self.model_cls).where(getattr(self.model_cls, "id") == entity_id)
        model = self.session.scalar(stmt)
        if not model:
            return False

        self.session.delete(model)
        self.session.flush()
        return True

    def exists(self, entity_id: IdT) -> bool:
        """Check if an entity exists by primary key without hydrating full entity."""
        stmt = select(getattr(self.model_cls, "id")).where(getattr(self.model_cls, "id") == entity_id)
        return self.session.scalar(stmt) is not None

    def count(self, include_deleted: bool = False) -> int:
        """Count total entities matching soft-delete criteria."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self.model_cls)
        if hasattr(self.model_cls, "is_deleted") and not include_deleted:
            stmt = stmt.where(getattr(self.model_cls, "is_deleted").is_(False))
        return self.session.scalar(stmt) or 0
