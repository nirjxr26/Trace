"""H-76: the PostgreSQL integration suite must never inherit a production URL."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_postgres as pg  # type: ignore[import-not-found]  # noqa: E402


def test_production_url_is_never_picked_up(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """H-76: the URL lookup fell back to TRACE_DATABASE_URL.

    A developer with a production URL in their shell ran this suite against production,
    and these tests create, close, archive and permanently purge cases.
    """
    monkeypatch.setenv("TRACE_DATABASE_URL", "postgresql+psycopg://user:pw@prod.example.com:5432/trace")
    monkeypatch.delenv("TRACE_TEST_POSTGRES_URL", raising=False)
    assert pg.get_postgres_url() is None, "production URL was inherited as a test target"


def test_explicit_opt_in_is_honoured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = "postgresql+psycopg://postgres:postgres@localhost:5432/trace_test"
    monkeypatch.setenv("TRACE_TEST_POSTGRES_URL", url)
    monkeypatch.setenv("TRACE_DATABASE_URL", "postgresql+psycopg://user:pw@prod.example.com:5432/prod")
    assert pg.get_postgres_url() == url, "explicit opt-in must win over the ambient variable"


def test_no_fallback_to_database_url_in_code() -> None:
    """Inspect the compiled code, not the file — the docstring names the variable it removed."""
    import inspect

    code = inspect.getsource(pg.get_postgres_url)
    code = code.split('"""', 2)[-1]  # drop the docstring
    assert "TRACE_DATABASE_URL" not in code, "the fallback must not come back"


def test_unset_environment_skips_rather_than_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACE_TEST_POSTGRES_URL", raising=False)
    assert pg.get_postgres_url() is None
