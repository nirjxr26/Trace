from collections.abc import Callable
from pathlib import Path
from typing import Any

from trace_core.core.settings import settings
from trace_core.updates.manifest import ReleaseManifest
from trace_core.updates.policy import is_installable, is_update_available
from trace_core.updates.sources import is_http_url


def default_manifest_target() -> str | None:
    """Single source for automatic manifest default. Empty string means explicitly disabled."""
    target = settings.update_manifest
    if target is None:
        return None
    if isinstance(target, str) and not target.strip():
        return None
    return str(target)


def resolve_manifest_target(explicit: str | Path | None) -> str:
    """Single source for manifest resolution. Explicit wins, else configured default, else fail closed.

    Takes no channel: it never read one, yet five call sites passed it believing
    resolution was channel-aware. Channel comes from the URL itself, via
    `split_manifest_url`, which is the single source for that split.
    """
    from trace_core.updates.errors import UpdateError

    if explicit:
        return str(explicit)
    target = default_manifest_target()
    if target:
        return target
    raise UpdateError("no update manifest configured (set TRACE_UPDATE_MANIFEST)")


def resolve_channel(explicit: str | None) -> str:
    """Single source for channel default. Explicit wins, else configured channel."""
    if explicit:
        return explicit
    return settings.update_channel


def load_manifest_auto(explicit: str | Path | None, channel: str = "stable") -> tuple[ReleaseManifest, str]:
    """Single source for manifest loading. Handles local path and http(s) via existing sources."""
    from trace_core.updates.manifest import load_manifest, load_manifest_bytes
    from trace_core.updates.sources import HttpManifestSource, split_manifest_url

    target = resolve_manifest_target(explicit)
    if is_http_url(target):
        # H-05: the channel encoded in the URL is authoritative. It used to be discarded
        # and rebuilt from the caller's channel, so `--manifest .../beta.json` on a stable
        # install silently fetched stable.json.
        base, url_channel = split_manifest_url(target)
        return load_manifest_bytes(HttpManifestSource(base).fetch(url_channel)), target
    return load_manifest(target), target


def ensure_artifact_path(
    manifest: ReleaseManifest,
    explicit: str | Path | None,
    manifest_target: str | Path | None = None,
    on_bytes: Callable[[int], None] | None = None,
) -> Path:
    """Single source for artifact resolution. Explicit path wins, else auto-select + auto-download."""
    from trace_core.core.fs import check_contained, ensure_dir
    from trace_core.updates.errors import UpdateError, UpdateVerificationError
    from trace_core.updates.policy import select_artifact
    from trace_core.updates.sources import split_manifest_url, stream_artifact_to_file
    from trace_core.updates.verifier import verify_artifact, verify_artifact_content

    if explicit:
        return Path(explicit)
    artifact = select_artifact(manifest)
    target = str(manifest_target or resolve_manifest_target(None))
    if not is_http_url(target):
        sibling = Path(target).parent / artifact.filename
        if sibling.exists():
            return sibling
        raise UpdateError(f"artifact {artifact.filename} not found beside manifest; pass --artifact") from None
    from trace_core.updates.marker import storage_state_path

    cache_dir = ensure_dir(storage_state_path("artifacts"))
    dest = check_contained(cache_dir / artifact.filename, cache_dir)
    if dest.exists():
        try:
            # Single verification path. This used to pre-check size and hash and then
            # call verify_artifact, which re-stats the size and re-hashes — two full
            # reads of an artifact that can be gigabytes, checking the same bytes twice.
            verify_artifact(dest, artifact)
            return dest
        except (OSError, UpdateVerificationError):
            pass
    base, _ = split_manifest_url(target)
    tmp = check_contained(cache_dir / f"{artifact.filename}.tmp", cache_dir)
    stream_artifact_to_file(base, artifact.filename, tmp, max(artifact.size + 1, 1_048_576), on_bytes=on_bytes)
    verify_artifact_content(tmp, artifact)
    tmp.replace(dest)
    return dest


def check_for_update(manifest_path: str | Path, channel: str = "stable", forensic_active: bool = False) -> dict:
    manifest, _ = load_manifest_auto(manifest_path, channel)
    current = get_installed_version()
    available = is_update_available(current, manifest)
    installable, reason = is_installable(current, manifest, channel, forensic_active)
    return {
        "current": current,
        "version_problem": pointer_version()[1],
        "manifest": manifest,
        "available": available,
        "installable": installable if available else False,
        "block_reason": reason if available and not installable else None,
    }


def pointer_version() -> tuple[str | None, str | None]:
    """(version, problem) from the install pointer.

    An absent pointer is normal — source checkouts and plain `pip install` have none, and
    the package version is authoritative there. An *unreadable* one is not: the old getter
    caught OSError and fell through to the package version, so `update install` printed
    "You're up to date — v0.3.0" and exited 0 on a machine whose real version was unknown.

    version is None when the pointer cannot be trusted; problem names why.
    """
    from trace_updater import updater as updater_mod

    try:
        base = updater_mod.install_root()
    except OSError as e:
        return None, f"the install location could not be read ({e})"
    try:
        active = updater_mod.read_active(base)
    except (OSError, ValueError) as e:
        return None, f"the version pointer could not be read ({e})"
    if not active:
        return None, None
    return active, None


def get_installed_version() -> str:
    """Single source for installed version. Active pointer wins, else package settings (legacy/source mode).

    A package-version fallback is not evidence of what is installed. Callers that report
    status use `pointer_version()` so an unreadable pointer is named rather than papered over.
    """
    from trace_core.core.settings import settings as _settings

    version, _problem = pointer_version()
    return version if version is not None else _settings.version


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
    payload = _check_payload(
        current,
        manifest,
        available=available,
        installable=installable,
        block_reason=reason,
    )
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


def _check_payload(
    current: str,
    manifest: ReleaseManifest,
    *,
    available: bool,
    installable: bool,
    block_reason: str | None,
) -> dict[str, Any]:
    """Single source for the cached payload shape. Shared by file and HTTP paths."""
    return {
        "current": current,
        "available": available,
        "target": manifest.version if available else None,
        "installable": installable if available else False,
        "block_reason": block_reason if available and not installable else None,
        "security_update": manifest.security_update,
        "minimum_supported_version": manifest.minimum_supported_version,
        "restart_required": manifest.restart_required,
        "notes": manifest.notes,
    }


def _payload_from_check(res: dict[str, Any]) -> dict[str, Any]:
    return _check_payload(
        res["current"],
        res["manifest"],
        available=res["available"],
        installable=res["installable"],
        block_reason=res["block_reason"],
    )


def cached_check(target: str | Path, channel: str = "stable") -> dict[str, Any]:
    from trace_core.updates import cache as check_cache
    from trace_core.updates import selfheal

    selfheal._maybe_heal()
    key = str(target)
    cached = check_cache.read_check_cache()
    if cached is not None:
        payload = cached.get("payload") or {}
        if payload.get("current") != get_installed_version():
            cached = None  # installed version changed since check; stale result
    if is_http_url(key):
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


def peek_cached_update() -> dict[str, Any] | None:
    from trace_core.updates import cache as check_cache

    try:
        cached = check_cache.read_check_cache()
    except Exception:
        return None
    payload = (cached or {}).get("payload") or {}
    if payload.get("available") and payload.get("target"):
        return payload
    return None
