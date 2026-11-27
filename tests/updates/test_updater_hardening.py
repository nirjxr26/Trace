import json
import threading
from pathlib import Path

import pytest

from trace_core.core.cli.exit_codes import (
    EXIT_ERROR,
    EXIT_RECOVERY_RETRY,
    EXIT_SUCCESS,
)
from trace_core.updates.errors import (
    MigrationCompatibilityError,
    UpdateError,
    UpdateInProgressError,
    UpdateNotAvailableError,
    UpdateVerificationError,
)


def test_automatic_checks_exclude_state_and_tmp() -> None:
    from trace_core.updates import selfheal

    assert selfheal.check_state_json not in selfheal.CHECKS
    assert selfheal.check_artifact_tmp not in selfheal.CHECKS
    names = {check.__name__ for check in selfheal.CHECKS}
    assert names == {"check_trust_dirs", "check_trust_anchor"}
    explicit = {check.__name__ for check in selfheal.EXPLICIT_CHECKS}
    assert "check_state_json" in explicit
    assert "check_artifact_tmp" in explicit


def test_maybe_heal_runs_only_automatic_checks(temp_storage_root: Path, monkeypatch) -> None:
    from contextlib import contextmanager

    from trace_core.updates import lock as lock_mod
    from trace_core.updates import selfheal

    @contextmanager
    def _held():
        yield True

    monkeypatch.setattr(lock_mod, "try_update_lock", _held)
    seen: list[str] = []

    def _check(name: str):
        seen.append(name)
        return selfheal.SelfCheck(name, True, "ok")

    automatic = (lambda: _check("trust dirs"), lambda: _check("trust anchor"))
    explicit = automatic + (lambda: _check("state files"), lambda: _check("artifact tmp"))
    monkeypatch.setattr(selfheal, "CHECKS", automatic)
    monkeypatch.setattr(selfheal, "EXPLICIT_CHECKS", explicit)
    monkeypatch.setattr(selfheal, "heal_schema_drift", lambda: False)
    monkeypatch.setattr(selfheal, "_LAST_HEAL", 0.0)
    monkeypatch.setattr(selfheal.time, "monotonic", lambda: selfheal._HEAL_INTERVAL + 1.0)

    selfheal._maybe_heal()
    assert seen == ["trust dirs", "trust anchor"]
    assert selfheal._automatic_only is False


def test_maybe_heal_skips_while_another_thread_holds_the_lock(temp_storage_root: Path, monkeypatch) -> None:
    from trace_core.updates import selfheal
    from trace_core.updates.lock import update_lock

    monkeypatch.setattr(selfheal, "_LAST_HEAL", 0.0)
    monkeypatch.setattr(selfheal.time, "monotonic", lambda: selfheal._HEAL_INTERVAL + 1.0)
    calls: list[bool] = []

    def _spy() -> list[selfheal.SelfCheck]:
        calls.append(True)
        return []

    monkeypatch.setattr(selfheal, "run_self_heal", _spy)

    ready = threading.Event()
    release = threading.Event()

    def _hold() -> None:
        with update_lock():
            ready.set()
            release.wait(timeout=10)

    thread = threading.Thread(target=_hold, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    try:
        selfheal._maybe_heal()
        assert calls == [], "automatic healing must not run during an active update"
        assert selfheal._LAST_HEAL == 0.0, "a skipped heal must stay eligible for a later retry"
    finally:
        release.set()
        thread.join(timeout=10)


def test_lifecycle_refuses_an_untrusted_pointer(session_manager, signed_release, monkeypatch) -> None:
    from trace_core.updates import checker
    from trace_core.updates.lifecycle import UpdateLifecycle

    monkeypatch.setattr(checker, "pointer_version", lambda: (None, "the version pointer could not be read"))
    manifest, _, art_path, _ = signed_release()
    with pytest.raises(UpdateError) as caught:
        UpdateLifecycle("tx-hard-pointer", session_manager).run(manifest, art_path)
    message = str(caught.value)
    assert "cannot tell which version is installed" in message, message
    assert "Run `trace recovery`" in message, message


def test_mcp_install_refuses_an_untrusted_pointer(
    session_manager, signed_release, release_keys, temp_storage_root: Path, monkeypatch
) -> None:
    from trace_core.core.settings import settings
    from trace_core.mcp import services as mcp_services
    from trace_core.updates import checker, signing

    signing.import_release_pubkey(release_keys["pub_hex"])
    manifest, manifest_path, _art_path, _ = signed_release()
    monkeypatch.setattr(settings, "update_manifest", str(manifest_path))
    monkeypatch.setattr(checker, "pointer_version", lambda: (None, "the version pointer could not be read"))
    monkeypatch.setattr(mcp_services, "_require_admin", lambda *_a, **_k: None)

    with pytest.raises(UpdateError, match="cannot tell which version is installed"):
        mcp_services.install_update(session_manager, manifest.version)


def test_installed_code_failure_never_leaks_stderr(monkeypatch) -> None:
    import subprocess

    from trace_core.core.settings import settings
    from trace_core.updates import migration

    secrets = "postgresql://alice:s3cr3t@db.internal/trace"
    stderr_text = (
        "Traceback (most recent call last):\n"
        '  File "C:\\work\\trace\\migrations.py", line 9, in run\n'
        + secrets
        + "\nSELECT password FROM operators WHERE token='abc123';\n"
    )

    class Result:
        returncode = 1
        stdout = ""
        stderr = stderr_text

    captured: list[tuple[str, dict]] = []

    class Log:
        def debug(self, event: str, **kwargs: object) -> None:
            captured.append((event, kwargs))

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Result())
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(migration.structlog, "get_logger", lambda: Log())

    with pytest.raises(UpdateError) as caught:
        migration.apply_migrations_with_installed_code()
    message = str(caught.value)
    assert "database migration failed" in message, message
    for leak in ("s3cr3t", "SELECT", "migrations.py", "alice", "abc123"):
        assert leak not in message, leak
    assert len(captured) == 1, captured
    detail = str(captured[0][1])
    for leak in ("s3cr3t", "SELECT password", "C:\\work", "abc123"):
        assert leak not in detail, detail
    assert "<credentials>@" in detail or "<path>" in detail, detail


def test_installed_code_failure_logs_only_in_debug(monkeypatch) -> None:
    import subprocess

    from trace_core.core.settings import settings
    from trace_core.updates import migration

    class Result:
        returncode = 1
        stdout = ""
        stderr = "migration failed"

    calls: list[bool] = []

    class Log:
        def debug(self, *_a: object, **_k: object) -> None:
            calls.append(True)

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Result())
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(migration.structlog, "get_logger", lambda: Log())
    with pytest.raises(UpdateError):
        migration.apply_migrations_with_installed_code()
    assert calls == []


def test_updater_migration_acquires_the_reentrant_lock(session_manager, temp_storage_root: Path, monkeypatch) -> None:
    from contextlib import contextmanager

    from trace_core.updates import lock as lock_mod
    from trace_core.updates import migration

    acquisitions: list[Path] = []

    @contextmanager
    def _locked(path: str | Path, **_kwargs: object):
        acquisitions.append(Path(path))
        yield True

    monkeypatch.setattr(lock_mod, "file_lock", _locked)
    monkeypatch.setattr(migration, "_run_updater_migration_locked", lambda *_a, **_k: {"schema": 1})
    expected = lock_mod.lock_path()

    assert migration.run_updater_migration(session_manager, "tx-lock-1") == {"schema": 1}
    assert acquisitions == [expected]

    with lock_mod.update_lock():
        acquisitions.clear()
        assert migration.run_updater_migration(session_manager, "tx-lock-2") == {"schema": 1}
    assert acquisitions == [], "a reentrant call must not re-acquire the file lock"


def test_finish_preserves_a_corrupt_marker(temp_storage_root: Path) -> None:
    from trace_core.updates.migration import marker_state, migration_marker_path

    marker = migration_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{not-json", encoding="utf-8")
    from trace_core.updates.migration import finish_update_migration

    with pytest.raises(UpdateInProgressError, match="run trace recovery"):
        finish_update_migration("tx-any")
    assert marker.exists(), "an unreadable or corrupt marker is evidence and must survive"
    assert marker_state()[0] == "corrupt"


def test_finish_preserves_an_unreadable_marker(temp_storage_root: Path, monkeypatch) -> None:
    from trace_core.updates.migration import finish_update_migration, migration_marker_path

    marker = migration_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"transaction_id": "tx-locked"}), encoding="utf-8")
    original = type(marker).read_text

    def _refused(*_a: object, **_k: object) -> str:
        raise PermissionError(32, "file in use by another process")

    monkeypatch.setattr(type(marker), "read_text", _refused)
    try:
        with pytest.raises(UpdateInProgressError, match="run trace recovery"):
            finish_update_migration("tx-locked")
        assert marker.exists()
    finally:
        monkeypatch.setattr(type(marker), "read_text", original)


def test_finish_refuses_another_transactions_marker(temp_storage_root: Path) -> None:
    from trace_core.updates.migration import begin_update_migration, finish_update_migration, marker_state

    begin_update_migration("tx-owner")
    with pytest.raises(UpdateInProgressError, match="another update transaction"):
        finish_update_migration("tx-other")
    assert marker_state()[0] == "active"


def test_finish_is_a_noop_when_no_marker_exists(temp_storage_root: Path) -> None:
    from trace_core.updates.migration import finish_update_migration, marker_state

    finish_update_migration("tx-absent")
    assert marker_state() == ("absent", None)


def test_loading_a_key_rejects_content_that_does_not_match_its_id(temp_storage_root: Path, monkeypatch) -> None:
    import trace_core.updates.trust as trust_mod
    from trace_core.updates import signing
    from trace_core.updates.trust import trust_key_path

    monkeypatch.setattr(trust_mod, "_TRUST_ROOT_CACHE", None)
    key_id = signing.import_release_pubkey("11" * 32)
    trust_key_path(key_id).write_text("22" * 32, encoding="utf-8")
    with pytest.raises(UpdateVerificationError, match="does not match its own key content"):
        signing.load_release_pubkey(key_id)


def test_missing_bootstrap_key_is_not_reprovisioned_by_verification(temp_storage_root: Path, monkeypatch) -> None:
    import trace_core.updates.trust as trust_mod
    from trace_core.updates import bootstrap, signing
    from trace_core.updates.trust import trust_key_path

    monkeypatch.setattr(trust_mod, "_TRUST_ROOT_CACHE", None)
    path = trust_key_path(bootstrap.KEY_ID)
    assert not path.exists()
    with pytest.raises(UpdateVerificationError, match="unknown release key"):
        signing.load_release_pubkey(bootstrap.KEY_ID)
    assert not path.exists(), "only the explicit recovery path may provision the anchor"


def test_update_exit_codes_are_semantic() -> None:
    from trace_core.core.cli.error_handler import _resolve_error_details

    title, _message, remedy, code = _resolve_error_details(UpdateInProgressError("another update"), None, None)
    assert code == EXIT_RECOVERY_RETRY, title
    assert remedy is not None
    assert "recovery" in remedy.lower(), remedy

    title, _message, remedy, code = _resolve_error_details(MigrationCompatibilityError("schema 1 below 2"), None, None)
    assert code == EXIT_ERROR, title
    assert remedy is not None
    assert "migrate" in remedy.lower(), remedy

    title, _message, _remedy, code = _resolve_error_details(UpdateNotAvailableError("current"), None, None)
    assert code == EXIT_SUCCESS, title


def test_peek_only_swallows_cache_read_data_errors(temp_storage_root: Path, monkeypatch) -> None:
    from trace_core.updates import cache, checker

    def _unreadable() -> dict:
        raise OSError("locked")

    monkeypatch.setattr(cache, "read_check_cache", _unreadable)
    assert checker.peek_cached_update() is None

    def _broken() -> dict:
        raise RuntimeError("bug")

    monkeypatch.setattr(cache, "read_check_cache", _broken)
    with pytest.raises(RuntimeError, match="bug"):
        checker.peek_cached_update()


def test_staging_refuses_a_symlinked_destination(tmp_path: Path) -> None:
    import hashlib

    from trace_updater import updater as updater_mod

    payload = b"verified bytes"
    src = tmp_path / "payload.bin"
    src.write_bytes(payload)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"do not overwrite")
    staging = tmp_path / "staging"
    staging.mkdir()
    try:
        (staging / "payload.bin").symlink_to(outside)
    except OSError as e:
        pytest.skip(f"symlinks unavailable on this platform: {e}")

    with pytest.raises(ValueError, match="Refusing"):
        updater_mod.stage_artifact(src, staging, expected_sha256=hashlib.sha256(payload).hexdigest())
    assert outside.read_bytes() == b"do not overwrite"
