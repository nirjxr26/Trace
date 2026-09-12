"""Generic reusable SQLAlchemy repository implementation."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from trace_core.core.domain import ensure_utc, now_utc

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

    def list_all(self, include_deleted: bool = False) -> list[EntityT]:
        """Fetch all entities with soft-delete filter."""
        stmt = select(self.model_cls)
        if hasattr(self.model_cls, "is_deleted") and not include_deleted:
            stmt = stmt.where(getattr(self.model_cls, "is_deleted").is_(False))

        if hasattr(self.model_cls, "opened_at"):
            stmt = stmt.order_by(getattr(self.model_cls, "opened_at").desc())

        models = self.session.scalars(stmt).all()
        return [self._to_domain(m) for m in models]

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
        """Delete an entity. If purge=False and model has is_deleted, soft-deletes."""
        stmt = select(self.model_cls).where(getattr(self.model_cls, "id") == entity_id)
        model = self.session.scalar(stmt)
        if not model:
            return False

        if purge or not hasattr(model, "is_deleted"):
            self.session.delete(model)
        else:
            setattr(model, "is_deleted", True)
            if hasattr(model, "updated_at"):
                setattr(model, "updated_at", now_utc())

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

    @staticmethod
    def ensure_utc(dt: Any) -> Any:
        """Helper for subclass timestamp handling."""
        return ensure_utc(dt)
