from pathlib import Path
from typing import Any

from trace_core.core.settings import settings
from trace_core.updates.manifest import load_manifest
from trace_core.updates.policy import is_installable, is_update_available

_URL_PREFIXES = ("https://", "http://")  # NOSONAR


def check_for_update(manifest_path: str | Path, channel: str = "stable", forensic_active: bool = False) -> dict:
    target = str(manifest_path)
    if target.startswith(_URL_PREFIXES):
        from trace_core.updates.manifest import load_manifest_bytes
        from trace_core.updates.sources import source_for

        manifest = load_manifest_bytes(source_for(target).fetch(channel))
    else:
        manifest = load_manifest(manifest_path)
    current = settings.version
    available = is_update_available(current, manifest)
    installable, reason = is_installable(current, manifest, channel, forensic_active)
    return {
        "current": current,
        "manifest": manifest,
        "available": available,
        "installable": installable if available else False,
        "block_reason": reason if available and not installable else None,
    }


def _cached_check_http(key: str, channel: str, cached: dict[str, Any] | None) -> dict[str, Any]:
    import hashlib

    from trace_core.updates import cache as check_cache
    from trace_core.updates.manifest import load_manifest_bytes
    from trace_core.updates.sources import HttpManifestSource, _NotModified, normalize_manifest_url, split_manifest_url

    norm_key = normalize_manifest_url(key)
    base, chan = split_manifest_url(key)
    if not key.endswith(".json"):
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
    current = settings.version
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
    if key.startswith(_URL_PREFIXES):
        return _cached_check_http(key, channel, cached)
    identity = check_cache.manifest_identity(key)
    if cached and identity is not None and check_cache.cache_valid_for(cached, key, channel, identity):
        return cached["payload"]
    res = check_for_update(target, channel)
    payload = _payload_from_check(res)
    if identity is not None:
        check_cache.write_check_cache(
            {"manifest_path": key, "channel": channel, "manifest_identity": identity, "payload": payload}
        )
    return payload
