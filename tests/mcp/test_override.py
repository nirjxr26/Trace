from pathlib import Path

import pytest
from conftest import ClientHarness  # type: ignore[import-not-found]

from trace_core.audit import signing
from trace_core.core.fs import ensure_dir
from trace_core.core.settings import settings


def test_purge_requires_archived_case(mcp_client: ClientHarness) -> None:
    created = mcp_client.call("trace_case_create", {"title": "Purge", "lead_examiner": "Analyst"})
    number = created.structured_content["number"]
    blocked = mcp_client.call("trace_case_purge", {"identifier": number, "confirm": number})
    assert blocked.is_error is True
    assert "INVALID_STATE" in blocked.content[0].text
    assert mcp_client.call("trace_case_archive", {"identifier": number, "confirm": number}).is_error is False
    purged = mcp_client.call("trace_case_purge", {"identifier": number, "confirm": number})
    assert purged.is_error is False
    assert purged.structured_content["purged"] is True


def test_export_rejects_traversal(mcp_client: ClientHarness) -> None:
    response = mcp_client.call("trace_audit_export", {"filename": "../secret.jsonl"})
    assert response.is_error is True
    assert "VALIDATION" in response.content[0].text


def test_export_writes_inside_export_root(
    mcp_client: ClientHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "storage_root", tmp_path)  # type: ignore[attr-defined]
    monkeypatch.setenv("TRACE_EXPORT_PASSPHRASE", "test-passphrase")  # type: ignore[attr-defined]
    response = mcp_client.call("trace_audit_export", {"filename": "bundle.jsonl", "encrypt": True})
    assert response.is_error is False
    assert response.structured_content["sealed"] is True
    assert (tmp_path / "exports" / "bundle.jsonl.sealed").is_file()


def test_export_overwrite_requires_confirm(mcp_client: ClientHarness) -> None:
    response = mcp_client.call("trace_audit_export", {"filename": "bundle.jsonl", "overwrite": True})
    assert response.is_error is True
    assert "VALIDATION" in response.content[0].text


def test_uninstall_is_refused(mcp_client: ClientHarness) -> None:
    response = mcp_client.call("trace_uninstall", {"confirm": "UNINSTALL"})
    assert response.is_error is True
    assert "INVALID_STATE" in response.content[0].text


def test_install_state_tools_require_confirmation(mcp_client: ClientHarness) -> None:
    update = mcp_client.call("trace_update_install", {"target_version": "0.4.2", "confirm": "wrong"})
    assert update.is_error is True
    recovery = mcp_client.call("trace_recovery", {"confirm": "wrong"})
    assert recovery.is_error is True
    migration = mcp_client.call("trace_db_migrate", {"confirm": "wrong"})
    assert migration.is_error is True


def test_key_rotation_guard(mcp_client: ClientHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = ensure_dir(tmp_path / "keystore")
    monkeypatch.setattr(signing, "_keystore_dir", lambda: root)  # type: ignore[attr-defined]
    created = mcp_client.call("trace_audit_keys_init", {"label": "mcp-test"})
    assert created.is_error is False
    key_id = created.structured_content["key_id"]
    listed = mcp_client.call("trace_audit_keys_list")
    assert listed.is_error is False
    monkeypatch.setattr(signing, "active_key_id", lambda: key_id)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "trace_core.audit.service.AuditService.has_hmac_rows",
        lambda self: True,
        raising=False,  # type: ignore[attr-defined]
    )
    rotated = mcp_client.call("trace_audit_keys_rotate", {"confirm": key_id})
    assert rotated.is_error is True
    assert "INVALID_STATE" in rotated.content[0].text
