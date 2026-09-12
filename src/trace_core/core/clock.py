"""Central clock abstraction for deterministic time generation."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Protocol for time providers."""

    def now(self) -> datetime: ...


class SystemUtcClock:
    """Default system clock providing timezone-aware UTC datetime."""

    def now(self) -> datetime:
        return datetime.now(UTC)


_current_clock: Clock = SystemUtcClock()


def get_clock() -> Clock:
    """Return the currently configured clock."""
    return _current_clock


def set_clock(clock: Clock) -> None:
    """Set the active clock (useful for deterministic tests)."""
    global _current_clock
    _current_clock = clock


def reset_clock() -> None:
    """Reset clock back to default SystemUtcClock."""
    global _current_clock
    _current_clock = SystemUtcClock()


def now_utc() -> datetime:
    """Return current timestamp in timezone-aware UTC using active clock."""
    return get_clock().now()
