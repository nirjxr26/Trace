import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

_HTTPS_PREFIX = "https://"
_HTTP_PREFIX = "http://"  # NOSONAR
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_GITHUB_CDN_HOSTS = ("github.com", ".githubusercontent.com")


class ManifestSource(ABC):
    @abstractmethod
    def fetch(self, channel: str) -> bytes:
        raise NotImplementedError


class LocalManifestSource(ManifestSource):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self, channel: str) -> bytes:
        return self.path.read_bytes()


class TestManifestSource(ManifestSource):
    def __init__(self, data: bytes):
        self.data = data

    def fetch(self, channel: str) -> bytes:
        return self.data


class _NotModified(Exception):
    pass


class _HttpsRedirectGuard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        from urllib.parse import urlparse

        from trace_core.updates.errors import UpdateError

        if req.full_url.startswith(_HTTPS_PREFIX) and newurl.startswith(_HTTP_PREFIX):
            raise UpdateError("refusing https-to-http redirect")
        try:
            old_host = (urlparse(req.full_url).hostname or "").lower()
            new_host = (urlparse(newurl).hostname or "").lower()
        except ValueError:
            raise UpdateError(f"refusing redirect to {newurl!r}") from None
        allowed_cross = old_host == _GITHUB_CDN_HOSTS[0] and (
            new_host == _GITHUB_CDN_HOSTS[0] or new_host.endswith(_GITHUB_CDN_HOSTS[1])
        )
        if old_host and new_host and old_host != new_host and not allowed_cross:
            raise UpdateError(f"refusing cross-host manifest redirect {old_host!r} -> {new_host!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_manifest_url(url: str) -> None:
    from urllib.parse import urlparse

    from trace_core.updates.errors import UpdateNetworkError

    if url.startswith(_HTTPS_PREFIX):
        return
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        host = ""
    if url.startswith(_HTTP_PREFIX) and host.lower() in _LOOPBACK_HOSTS:
        return
    raise UpdateNetworkError(f"refusing non-https manifest url {url!r}")


_JSON_SUFFIX = ".json"


def has_json_suffix(url: str) -> bool:
    """Single source for manifest-path check. Uses parsed path so query strings do not confuse it."""
    from urllib.parse import urlparse

    try:
        return urlparse(url).path.endswith(_JSON_SUFFIX)
    except ValueError:
        return url.endswith(_JSON_SUFFIX)


def _is_retryable_url_error(e: urllib.error.URLError) -> bool:
    return not isinstance(e, urllib.error.HTTPError) or getattr(e, "code", 0) in (
        408,
        429,
        500,
        502,
        503,
        504,
    )


def _read_manifest_response(response: Any, max_bytes: int) -> tuple[bytes, str | None]:
    from trace_core.updates.errors import UpdateError

    if response.status == 304:
        raise _NotModified()
    content_type = response.headers.get("Content-Type", "").lower()
    # ponytail: content-type is a hint, not trust — GitHub serves
    # release assets as octet-stream; signature+schema decide.
    # TLS is transport-only; Ed25519 is trust.
    if "json" not in content_type and "octet-stream" not in content_type:
        raise UpdateError(f"unexpected manifest content type {content_type!r}")
    data = response.read(max_bytes + 1)
    return data, response.headers.get("ETag")


def _handle_url_error(e: urllib.error.URLError, attempt: int) -> None:
    import time

    from trace_core.updates.errors import UpdateNetworkError

    if isinstance(e, urllib.error.HTTPError) and e.code == 304:
        raise _NotModified() from None
    if _is_retryable_url_error(e) and attempt < 3:
        time.sleep(attempt)
        return
    raise UpdateNetworkError(f"manifest download failed: {e}") from e


def _with_retries(op):  # type: ignore[no-untyped-def]
    """Single source for URL retry loop. Shared by manifest and artifact fetches."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return op()
        except _NotModified:
            raise
        except urllib.error.URLError as e:
            _handle_url_error(e, attempt)


def stream_artifact_to_file(
    base_url: str,
    filename: str,
    dest_tmp: Path,
    max_bytes: int,
    timeout: float = 30.0,
    on_bytes: Callable[[int], None] | None = None,
) -> Path:
    """Single source for artifact download. Streams in 1 MB chunks, never holds full bytes in RAM."""
    from trace_core.updates.errors import UpdateNetworkError
    from trace_core.updates.verifier import assert_safe_filename

    assert_safe_filename(filename)
    base = base_url.rstrip("/")
    url = f"{base}/{filename}"
    _validate_manifest_url(url)
    opener = urllib.request.build_opener(_HttpsRedirectGuard)
    request = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})

    def _download() -> Path:
        written = 0
        with opener.open(request, timeout=timeout) as response:
            with dest_tmp.open("wb") as fout:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise UpdateNetworkError("artifact response too large")
                    fout.write(chunk)
                    if on_bytes is not None:
                        on_bytes(written)
        return dest_tmp

    return _with_retries(_download)


def fetch_artifact_bytes(base_url: str, filename: str, max_bytes: int, timeout: float = 30.0) -> bytes:
    """Single source for small artifact download. Delegates to streaming helper for one code path."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="trace-artifact-") as tmpdir:
        tmp = Path(tmpdir) / "artifact.bin"
        stream_artifact_to_file(base_url, filename, tmp, max_bytes, timeout)
        return tmp.read_bytes()


class HttpManifestSource(ManifestSource):
    def __init__(self, base_url: str, timeout: float = 10.0, max_bytes: int | None = None):
        from trace_core.updates.manifest import MAX_MANIFEST_BYTES

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_bytes = max_bytes if max_bytes is not None else MAX_MANIFEST_BYTES

    def fetch_with_etag(self, channel: str, etag: str | None = None) -> tuple[bytes, str | None]:
        from trace_core.updates.errors import UpdateNetworkError

        url = f"{self.base_url}/{channel}{_JSON_SUFFIX}"
        _validate_manifest_url(url)

        opener = urllib.request.build_opener(_HttpsRedirectGuard)
        headers = {"Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        request = urllib.request.Request(url, headers=headers)

        def _fetch() -> tuple[bytes, str | None]:
            with opener.open(request, timeout=self.timeout) as response:
                return _read_manifest_response(response, self.max_bytes)

        data, response_etag = _with_retries(_fetch)
        if len(data) > self.max_bytes:
            raise UpdateNetworkError("manifest response too large")
        return data, response_etag

    def fetch(self, channel: str) -> bytes:
        data, _ = self.fetch_with_etag(channel)
        return data


def source_for(target: str) -> ManifestSource:
    if target.startswith((_HTTPS_PREFIX, _HTTP_PREFIX)):
        base, _ = split_manifest_url(target)
        return HttpManifestSource(base)
    return LocalManifestSource(target)


def normalize_manifest_url(url: str) -> str:
    """Single source for cache keys. Strips query/fragment, preserves scheme+host+path."""
    from urllib.parse import urlparse, urlunparse

    try:
        parts = urlparse(url)
        return urlunparse((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "", ""))
    except ValueError:
        return url


def split_manifest_url(url: str) -> tuple[str, str]:
    """Single source for base/channel split. Handles query strings and .json suffix."""
    from urllib.parse import urlparse

    try:
        path = urlparse(url).path
        base_path = url.rsplit("?", 1)[0].rsplit("#", 1)[0]
        if path.endswith(_JSON_SUFFIX):
            stem = path.rsplit("/", 1)[-1].removesuffix(_JSON_SUFFIX)
            base = base_path.rsplit("/", 1)[0]
            return base, stem or "stable"
    except ValueError:
        pass
    if url.endswith(_JSON_SUFFIX):
        return url.rsplit("/", 1)[0], url.rsplit("/", 1)[-1].removesuffix(_JSON_SUFFIX).split("?", 1)[0]
    return url, "stable"
