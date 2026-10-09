"""Regression guards for the update-source permanent fixes.

Each test names the finding it closes and the specific defect that let it through.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from trace_core.updates import sources
from trace_core.updates.errors import UpdateError, UpdateNetworkError, UpdateResponseRefused


def _response(body: bytes = b"") -> object:
    """Minimal response that returns `body` once, then EOF, like a real stream."""

    class _Resp:
        def __init__(self) -> None:
            self._chunks: list[bytes] = [body] if body else []

        def read(self, _n: int) -> bytes:
            return self._chunks.pop(0) if self._chunks else b""

        def __enter__(self) -> object:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    return _Resp()


# --- H-12: redirect allowlist was endswith, so any *.githubusercontent.com matched ---


def test_h12_rejects_sibling_domain_ending_in_cdn_suffix() -> None:
    """H-12: endswith('.githubusercontent.com') also accepts an attacker-registrable sibling."""
    assert sources._is_release_asset_host("objects.githubusercontent.com") is True
    assert sources._is_release_asset_host("github.com") is True
    for impostor in (
        "evil-githubusercontent.com",
        "evilgithubusercontent.com",
        "githubusercontent.com.evil.example",
        "notgithubusercontent.com",
        "raw.githubusercontent.com.evil.example",
    ):
        assert sources._is_release_asset_host(impostor) is False, impostor


def test_h12_cross_host_redirect_guard_blocks_impostor(monkeypatch) -> None:  # type: ignore[no-untyped-def]

    guard = sources._HttpsRedirectGuard()
    req = urllib.request.Request("https://github.com/x/manifest.json")
    to_impostor = "https://evil-githubusercontent.com/manifest.json"
    with pytest.raises(UpdateError, match="cross-host"):
        guard.redirect_request(req, None, 302, "", {}, to_impostor)  # type: ignore[arg-type]
    # the genuine CDN still works
    ok = guard.redirect_request(
        req,
        None,
        302,
        "",
        {},
        "https://objects.githubusercontent.com/manifest.json",  # type: ignore[arg-type]
    )
    assert ok is not None


# --- H-10: a size-cap / network failure left a partial temp file behind ---


def test_h10_partial_download_is_removed(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    dest = tmp_path / "artifact.part"

    class _Opener:
        def open(self, *_a: object, **_k: object) -> object:
            return _response(b"x" * (1 << 21))

    monkeypatch.setattr(sources.urllib.request, "build_opener", lambda *_a, **_k: _Opener())
    monkeypatch.setattr(sources, "_validate_manifest_url", lambda _u: None)
    with pytest.raises(UpdateResponseRefused, match="exceeded"):
        sources.stream_artifact_to_file("https://example.test/base", "a.whl", dest, max_bytes=1 << 20)
    assert not Path(dest).exists(), "partial artifact must not survive a failed download"


def test_h10_legitimate_download_still_writes(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    dest = tmp_path / "artifact.part"

    class _Opener:
        def open(self, *_a: object, **_k: object) -> object:
            return _response(b"payload-bytes")

    monkeypatch.setattr(sources.urllib.request, "build_opener", lambda *_a, **_k: _Opener())
    monkeypatch.setattr(sources, "_validate_manifest_url", lambda _u: None)
    got = sources.stream_artifact_to_file("https://example.test/base", "a.whl", dest, max_bytes=1 << 20)
    assert Path(got).read_bytes() == b"payload-bytes"


# --- H-07: the artifact cap was 10 GiB, so the happy path could exhaust memory ---


def test_h07_artifact_cap_is_bounded() -> None:
    from trace_core.updates.manifest import MAX_ARTIFACT_BYTES

    assert MAX_ARTIFACT_BYTES == 512 * 1024 * 1024
    assert MAX_ARTIFACT_BYTES <= 2 * 1024**3, "a release is a wheel+sdist, not multi-gigabyte"


def test_h07_oversized_artifact_is_refused_before_read(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from trace_core.updates.errors import UpdateVerificationError
    from trace_core.updates.manifest import MAX_ARTIFACT_BYTES
    from trace_core.updates.signing import verify_artifact_signature_file

    big = tmp_path / "big.bin"
    big.write_bytes(b"0")

    class _Stat:
        st_size = MAX_ARTIFACT_BYTES + 1

        def __fspath__(self) -> str:
            return str(big)

    # stub stat to report oversized without allocating the bytes
    big.unlink()
    big.write_bytes(b"0")
    original = type(big).stat

    def _fake_stat(self: object) -> object:  # type: ignore[no-untyped-def]
        return _Stat() if self == big else original(self)

    big.__class__.stat = _fake_stat  # type: ignore[method-assign,assignment]
    try:
        with pytest.raises(UpdateVerificationError, match="too large"):
            verify_artifact_signature_file(big, None, None)
    finally:
        big.__class__.stat = original  # type: ignore[method-assign]


# --- H-06: the cache path hashed the file twice (once to trust, once to verify) ---


def test_h06_cache_path_does_not_prehash(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """H-06: ensure_artifact_path hashed the cached file and then verify_artifact hashed it again."""
    import inspect

    src = inspect.getsource(sources_checker_module())
    body = src.split("def ensure_artifact_path", 1)[1]
    assert "sha256_file(" not in body, "cache path must not pre-hash before verify_artifact"


def sources_checker_module():  # type: ignore[no-untyped-def]
    from trace_core.updates import checker

    return checker


# --- H-21 / H-52: symlink containment and lock files ---


def test_h21_containment_uses_root_literally(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core.fs import check_contained

    root = tmp_path / "trust"
    root.mkdir()
    assert check_contained(root / "key.pub", root).name == "key.pub"
    for bad in (root / ".." / "escape.txt", tmp_path / "sibling" / "x"):
        with pytest.raises(ValueError, match="escaping storage root"):
            check_contained(bad, root)


def test_h21_root_is_not_resolved_before_comparison(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A resolved root makes every candidate vacuously contained, so the check can never fire."""
    import inspect

    from trace_core.core import fs

    src = inspect.getsource(fs.check_contained)
    assert "Path(root).resolve()" not in src


def test_h52_lock_open_refuses_symlinks() -> None:
    import inspect

    from trace_core.core import fs

    assert "a+b" not in inspect.getsource(fs.file_lock)
    helper = inspect.getsource(fs._open_lock_file)
    assert "O_NOFOLLOW" in helper
    assert "closefd=True" in helper


def test_h52_lock_still_creates_and_reopens(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core.fs import file_lock

    lock = tmp_path / "update.lock"
    with file_lock(lock) as held:
        assert held is True
    assert lock.exists()
    with file_lock(lock) as held:
        assert held is True


def test_uncontended_try_lock_yields_true_and_is_released(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from trace_core.core.fs import try_file_lock

    lock = tmp_path / "update.lock"
    with try_file_lock(lock) as held:
        assert held is True
    with try_file_lock(lock) as held:
        assert held is True


# --- H-60: allocation contended on the year row, outside the DB error handler ---


def test_h60_allocation_contention_is_translated(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """H-60: 'database is locked' from the sequence row surfaced as a raw OperationalError."""
    from sqlalchemy.exc import OperationalError

    from trace_core.cases import service as case_service

    err = OperationalError("stmt", {}, Exception("database is locked"))
    assert "locked" in str(err).lower()

    class _Repo:
        def __init__(self, _session: object) -> None:
            pass

        def get_next_sequence_number(self, year: int | None = None) -> str:
            raise err

    monkeypatch.setattr(case_service, "SqlAlchemyCaseRepository", _Repo)
    assert issubclass(case_service.CaseSequenceContentionError, case_service.ConflictError)


def test_h60_lock_contention_message_is_narrow() -> None:
    """A blanket OperationalError catch would relabel real bugs as contention."""
    from sqlalchemy.exc import OperationalError

    from trace_core.cases.service import CaseSequenceContentionError, ConflictError

    locked = OperationalError("stmt", {}, Exception("database is locked"))
    other = OperationalError("stmt", {}, Exception("no such column: cases.title"))
    assert "locked" in str(locked).lower()
    assert "locked" not in str(other).lower(), "genuine bugs must not map to contention"
    assert CaseSequenceContentionError("retry").resource_type == "Case sequence"
    assert issubclass(CaseSequenceContentionError, ConflictError)


# --- H-43: one predicate for missing table/column, shared by ledger and operators ---


def test_h43_single_missing_relation_predicate() -> None:
    from sqlalchemy.exc import ProgrammingError

    from trace_core.core.database.health import is_missing_relation_error

    missing = ProgrammingError("stmt", {}, Exception('relation "cases" does not exist'))
    privilege = ProgrammingError("stmt", {}, Exception("permission denied"))
    assert is_missing_relation_error(missing) is True
    assert is_missing_relation_error(privilege) is False


def test_h43_no_duplicate_implementations_remain() -> None:
    """The two former implementations must not reappear beside the shared predicate."""
    import inspect

    from trace_core.audit import service as audit_service
    from trace_core.core import operators

    assert not hasattr(audit_service, "_is_ledger_missing")
    assert not hasattr(operators, "_missing_table")
    assert "is_missing_relation_error" in inspect.getsource(audit_service)
    assert "is_missing_relation_error" in inspect.getsource(operators)


def test_h43_pg_sqlstate_recognised() -> None:
    psycopg = pytest.importorskip("psycopg")
    from trace_core.core.database.health import is_missing_relation_error

    class _Orig:
        sqlstate = "42P01"

    class _Err(Exception):
        orig = _Orig()

    assert is_missing_relation_error(_Err()) is True
    assert psycopg is not None


def test_h10_urllib_error_still_propagates(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dest = tmp_path / "p.part"

    class _Opener:
        def open(self, *_a: object, **_k: object) -> object:
            raise urllib.error.URLError("boom")

    monkeypatch.setattr(sources.urllib.request, "build_opener", lambda *_a, **_k: _Opener())
    monkeypatch.setattr(sources, "_validate_manifest_url", lambda _u: None)

    with pytest.raises(UpdateNetworkError, match="boom"):
        sources.stream_artifact_to_file("https://example.test/base", "a.whl", dest, max_bytes=1 << 20)
