from pathlib import Path
from typing import Any

from trace_core.core.settings import settings
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.policy import is_installable, is_update_available

_URL_PREFIXES = ("https://", "http://")  # NOSONAR


def default_manifest_target() -> str | None:
    """Single source for automatic manifest default. Empty string means explicitly disabled."""
    target = settings.update_manifest
    if target is None:
        return None
    if isinstance(target, str) and not target.strip():
        return None
    return str(target)


def resolve_manifest_target(explicit: str | Path | None, channel: str = "stable") -> str:
    """Single source for manifest resolution. Explicit wins, else configured default, else fail closed."""
    from trace_core.updates.errors import UpdateError

    if explicit:
        return str(explicit)
    target = default_manifest_target()
    if target:
        return target
    raise UpdateError("no update manifest configured (pass --manifest or set TRACE_UPDATE_MANIFEST)")


def resolve_channel(explicit: str | None) -> str:
    """Single source for channel default. Explicit wins, else configured channel."""
    if explicit:
        return explicit
    return settings.update_channel


def load_manifest_auto(explicit: str | Path | None, channel: str = "stable") -> tuple[ReleaseManifest, str]:
    """Single source for manifest loading. Handles local path and http(s) via existing sources."""
    from trace_core.updates.manifest import load_manifest, load_manifest_bytes
    from trace_core.updates.sources import source_for

    target = resolve_manifest_target(explicit, channel)
    if target.startswith(_URL_PREFIXES):
        return load_manifest_bytes(source_for(target).fetch(channel)), target
    return load_manifest(target), target


def ensure_artifact_path(
    manifest: ReleaseManifest, explicit: str | Path | None, manifest_target: str | Path | None = None
) -> Path:
    """Single source for artifact resolution. Explicit path wins, else auto-select + auto-download."""
    from trace_core.core.fs import check_contained, ensure_dir, sha256_file
    from trace_core.core.settings import settings
    from trace_core.updates.errors import UpdateError
    from trace_core.updates.policy import select_artifact
    from trace_core.updates.sources import split_manifest_url, stream_artifact_to_file
    from trace_core.updates.verifier import verify_artifact

    if explicit:
        return Path(explicit)
    artifact = select_artifact(manifest)
    target = str(manifest_target or resolve_manifest_target(None))
    if not target.startswith(_URL_PREFIXES):
        sibling = Path(target).parent / artifact.filename
        if sibling.exists():
            return sibling
        raise UpdateError(f"artifact {artifact.filename} not found beside manifest; pass --artifact") from None
    cache_dir = ensure_dir(Path(settings.storage_root) / "state" / "artifacts")
    dest = check_contained(cache_dir / artifact.filename, cache_dir)
    if dest.exists():
        try:
            if dest.stat().st_size == artifact.size and sha256_file(dest) == artifact.sha256:
                verify_artifact(dest, artifact)
                return dest
        except OSError:
            pass
    base, _ = split_manifest_url(target)
    tmp = check_contained(cache_dir / f"{artifact.filename}.tmp", cache_dir)
    stream_artifact_to_file(base, artifact.filename, tmp, max(artifact.size + 1, 1_048_576))
    verify_artifact(tmp, artifact)
    tmp.replace(dest)
    return dest


def check_for_update(manifest_path: str | Path, channel: str = "stable", forensic_active: bool = False) -> dict:
    manifest, _ = load_manifest_auto(manifest_path, channel)
    current = get_installed_version()
    available = is_update_available(current, manifest)
    installable, reason = is_installable(current, manifest, channel, forensic_active)
    return {
        "current": current,
        "manifest": manifest,
        "available": available,
        "installable": installable if available else False,
        "block_reason": reason if available and not installable else None,
    }


def get_installed_version() -> str:
    """Single source for installed version. Active pointer wins, else package settings (legacy/source mode)."""
    from trace_core.core.settings import settings as _settings

    try:
        from trace_updater import updater as updater_mod

        base = updater_mod.install_root()
        active = updater_mod.read_active(base)
        if active:
            return active
    except OSError:
        pass
    return _settings.version


def _cached_check_http(key: str, channel: str, cached: dict[str, Any] | None) -> dict[str, Any]:
    import hashlib

    from trace_core.updates import cache as check_cache
    from trace_core.updates.manifest import load_manifest_bytes
    from trace_core.updates.sources import (
        HttpManifestSource,
        _NotModified,
        has_json_suffix,
        normalize_manifest_url,
        split_manifest_url,
    )

    norm_key = normalize_manifest_url(key)
    base, chan = split_manifest_url(key)
    if not has_json_suffix(key):
        chan = channel
    norm_cached_key = normalize_manifest_url(cached.get("manifest_path", "")) if cached else None
    etag = cached.get("etag") if cached and norm_cached_key == norm_key else None
    try:
        data, new_etag = HttpManifestSource(base).fetch_with_etag(chan, etag)
    except _NotModified:
        if cached:
            check_cache.write_check_cache({**cached})
            return cached["payload"]
        raise
    manifest = load_manifest_bytes(data)
    current = get_installed_version()
    available = is_update_available(current, manifest)
    installable, reason = is_installable(current, manifest, channel, False)
    payload = {
        "current": current,
        "available": available,
        "target": manifest.version if available else None,
        "installable": installable if available else False,
        "block_reason": reason if available and not installable else None,
        "security_update": manifest.security_update,
        "minimum_supported_version": manifest.minimum_supported_version,
        "restart_required": manifest.restart_required,
    }
    check_cache.write_check_cache(
        {
            "manifest_path": norm_key,
            "channel": channel,
            "etag": new_etag,
            "manifest_sha256": hashlib.sha256(data).hexdigest(),
            "payload": payload,
        }
    )
    return payload


def _payload_from_check(res: dict[str, Any]) -> dict[str, Any]:
    """Single source for cached payload shape. Shared by file and HTTP paths."""
    m = res["manifest"]
    return {
        "current": res["current"],
        "available": res["available"],
        "target": m.version if res["available"] else None,
        "installable": res["installable"],
        "block_reason": res["block_reason"],
        "security_update": m.security_update,
        "minimum_supported_version": m.minimum_supported_version,
        "restart_required": m.restart_required,
    }


def cached_check(target: str | Path, channel: str = "stable") -> dict[str, Any]:
    from trace_core.updates import cache as check_cache

    key = str(target)
    cached = check_cache.read_check_cache()
    if cached is not None:
        payload = cached.get("payload") or {}
        if payload.get("current") != get_installed_version():
            cached = None  # installed version changed since check; stale result
    if key.startswith(_URL_PREFIXES):
        return _cached_check_http(key, channel, cached)
    stored = (cached.get("manifest_identity") or {}) if cached else None
    identity = check_cache.manifest_identity(key, known=stored)
    if cached and identity is not None and check_cache.cache_valid_for(cached, key, channel, identity):
        return cached["payload"]
    res = check_for_update(target, channel)
    payload = _payload_from_check(res)
    if identity is not None:
        check_cache.write_check_cache(
            {"manifest_path": key, "channel": channel, "manifest_identity": identity, "payload": payload}
        )
    return payload
