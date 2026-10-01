"""C-04: the database boundary hands back timezone-aware UTC on every backend.

DateTime(timezone=True) is a no-op on SQLite — its result processor returns a naive
datetime, so every read produced a value that looked UTC but was local wall-clock.
That is the 5h30m error the ZULU-labelled field printed. UTCDateTime fixes it at the
column type, so these tests pin the boundary itself rather than a caller's guard.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import DateTime, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from trace_core.core.database.base import Base, UTCDateTime

STAMP = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
ZULU = "2026-09-27T10:00:00Z"


class _Scratch(DeclarativeBase):
    """Isolated metadata so the probe tables never enter the production schema."""


class _Legacy(_Scratch):
    """The pre-fix declaration, kept only so the regression can be shown to bite."""

    __tablename__ = "legacy_ts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class _Current(_Scratch):
    __tablename__ = "current_ts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)


@pytest.fixture
def sqlite_engine() -> sa.Engine:
    """One engine per test: a second create_engine('sqlite://') is a different database."""
    engine = sa.create_engine("sqlite://")
    _Scratch.metadata.create_all(engine)
    return engine


def _zulu(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_then_read(engine: sa.Engine, model: Any) -> datetime:
    """Round-trip one timestamp column through the boundary.

    `model` is typed `Any` rather than `type` because this helper is called with several
    distinct ORM classes and reads a different column off each (`ts`, `observed_at`, ...);
    `type` made every attribute access an error without checking anything real.
    """
    with Session(engine) as session:
        session.add(model(ts=STAMP))
        session.commit()
    with Session(engine) as session:
        return session.execute(select(model.ts)).scalar_one()


def test_sqlite_round_trip_is_aware_and_utc(sqlite_engine: sa.Engine):
    stored = _write_then_read(sqlite_engine, _Current)
    assert stored.tzinfo is not None
    assert stored == STAMP
    assert _zulu(stored) == ZULU


def test_legacy_declaration_would_have_rendered_five_hours_wrong(sqlite_engine: sa.Engine):
    """Pins the defect. Revert UTCDateTime to DateTime(timezone=True) and this is the value callers got."""
    stored = _write_then_read(sqlite_engine, _Legacy)
    assert stored.tzinfo is None
    assert _zulu(stored) == "2026-09-27T04:30:00Z"


def test_naive_bind_is_stored_as_utc_rather_than_local_wall_clock(sqlite_engine: sa.Engine):
    """Symmetric with the read side: what goes in comes back aware UTC, not local time."""
    with Session(sqlite_engine) as session:
        session.add(_Current(ts=datetime(2026, 9, 27, 10, 0)))
        session.commit()
    with Session(sqlite_engine) as session:
        stored = session.execute(select(_Current.ts)).scalar_one()
    assert stored == STAMP
    assert _zulu(stored) == ZULU


def test_every_timestamp_column_uses_the_decorator():
    """A bare DateTime(timezone=True) reappearing anywhere is the regression."""
    import trace_core.audit.models  # noqa: F401
    import trace_core.cases.models  # noqa: F401
    import trace_core.core.operators  # noqa: F401
    import trace_core.updates.models  # noqa: F401
    from trace_core.core.database.migrations import schema_migrations

    checked = 0
    for table in (*Base.metadata.tables.values(), schema_migrations):
        for column in table.columns:
            if not isinstance(column.type, (sa.DateTime, UTCDateTime)):
                continue
            assert isinstance(column.type, UTCDateTime), f"{table.name}.{column.name} is a bare DateTime"
            checked += 1
    assert checked >= 10, "expected every timestamp column to be covered"
