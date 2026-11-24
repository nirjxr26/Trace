import io
import os
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, NoReturn

from trace_core.audit.service import AuditService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.operators import require_admin
from trace_core.mcp.errors import ToolFailure


def _export_root() -> Path:
    from trace_core.core.fs import ensure_dir
    from trace_core.core.settings import settings

    return ensure_dir(Path(settings.storage_root) / "exports")


def _passphrase() -> str:
    return os.environ.get("TRACE_EXPORT_PASSPHRASE", "")


def export_bundle(manager: DatabaseSessionManager, filename: str, encrypt: bool, overwrite: bool) -> dict[str, Any]:
    from trace_core.audit.helpers import do_export
    from trace_core.core.fs import check_contained

    root = _export_root()
    target = check_contained(root / filename, root, what="export destination")
    passphrase = _passphrase() if encrypt else None
    if encrypt and not passphrase:
        raise ToolFailure("VALIDATION", "TRACE_EXPORT_PASSPHRASE is not set on this MCP server.")
    receipt = do_export(AuditService(manager), str(target), passphrase, force=overwrite)
    return {
        "name": Path(receipt.path).name,
        "rows": receipt.rows,
        "size_bytes": receipt.size_bytes,
        "sha256": receipt.sha256,
        "sealed": receipt.sealed,
    }


def decrypt_bundle(filename: str, overwrite: bool) -> dict[str, Any]:
    from trace_core.audit.helpers import do_decrypt, plain_destination
    from trace_core.core.fs import check_contained

    root = _export_root()
    source = check_contained(root / filename, root, what="bundle source")
    destination = check_contained(plain_destination(source), root, what="decrypt destination")
    passphrase = _passphrase()
    if not passphrase:
        raise ToolFailure("VALIDATION", "TRACE_EXPORT_PASSPHRASE is not set on this MCP server.")
    receipt = do_decrypt(str(source), str(destination), passphrase, force=overwrite)
    return {
        "name": Path(receipt.path).name,
        "rows": receipt.rows,
        "size_bytes": receipt.size_bytes,
        "sha256": receipt.sha256,
        "sealed": False,
    }


def keys_init(manager: DatabaseSessionManager, label: str) -> dict[str, Any]:
    _require_admin(manager, "initialize signing keys")
    from trace_core.audit.signing import init_key

    return {"key_id": init_key(label), "status": "active"}


def keys_rotate(manager: DatabaseSessionManager, label: str, confirm_key_id: str) -> dict[str, Any]:
    _require_admin(manager, "rotate signing keys")
    from trace_core.audit.signing import active_key_id

    if active_key_id() != confirm_key_id:
        raise ToolFailure("VALIDATION", "confirm must repeat the current active key id.")
    if AuditService(manager).has_hmac_rows():
        raise ToolFailure(
            "INVALID_STATE",
            "HMAC-signed ledger rows exist. Rotating now would make them read as tampered.",
        )
    from trace_core.audit.signing import rotate_keys

    return {"key_id": rotate_keys(label), "status": "active"}


def keys_list() -> dict[str, Any]:
    from trace_core.audit.signing import list_keys

    return {"items": list_keys()}


def install_update(manager: DatabaseSessionManager, target_version: str) -> dict[str, Any]:
    _require_admin(manager, "install updates")
    from trace_core.updates.checker import ensure_artifact_path, load_manifest_auto, resolve_channel
    from trace_core.updates.lifecycle import UpdateLifecycle
    from trace_core.updates.verifier import verify_manifest

    channel = resolve_channel(None)
    manifest, target = load_manifest_auto(None, channel)
    if manifest.version != target_version:
        raise ToolFailure("VALIDATION", "target_version must match the signed release manifest version.")
    artifact_path = ensure_artifact_path(manifest, None, target)
    verify_manifest(manifest, artifact_path)
    with redirect_stdout(io.StringIO()):
        result = UpdateLifecycle(uuid.uuid4().hex).run(
            manifest, artifact_path, channel=channel, allow_minimum_bypass=False
        )
    return {"target_version": manifest.version, "result": result.model_dump(mode="json")}


def recover_installation(manager: DatabaseSessionManager) -> dict[str, Any]:
    _require_admin(manager, "recover an interrupted update")
    from trace_core.core.cli.recovery import run_recovery
    from trace_core.updates.migration import marker_state

    before, _ = marker_state()
    with redirect_stdout(io.StringIO()):
        run_recovery()
    after, _ = marker_state()
    return {"marker_before": before, "marker_after": after, "recovered": True}


def migrate_database(manager: DatabaseSessionManager) -> dict[str, Any]:
    _require_admin(manager, "apply database migrations")
    from trace_core.core.database.migrations import apply_migrations

    applied = apply_migrations(manager.engine)
    return {"applied": applied, "count": len(applied)}


def uninstall_refused() -> NoReturn:
    raise ToolFailure(
        "INVALID_STATE",
        "Trace is currently serving this MCP connection and cannot uninstall itself. Run `trace uninstall` from a terminal.",
    )


def _require_admin(manager: DatabaseSessionManager, action: str) -> None:
    with manager.session() as session:
        require_admin(session, action=action)
