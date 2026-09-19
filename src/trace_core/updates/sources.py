import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

_HTTPS_PREFIX = "https://"
_HTTP_PREFIX = "http://"  # NOSONAR
_LOOPBACK_PREFIXES = ("http://localhost", "http://127.0.0.1", "http://[::1]")


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
        if req.full_url.startswith(_HTTPS_PREFIX) and newurl.startswith(_HTTP_PREFIX):
            from trace_core.updates.errors import UpdateError

            raise UpdateError("refusing https-to-http redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_manifest_url(url: str) -> None:
    from trace_core.updates.errors import UpdateError

    loopback = url.startswith(_LOOPBACK_PREFIXES)
    if not url.startswith(_HTTPS_PREFIX) and not loopback:
        raise UpdateError(f"refusing non-https manifest url {url!r}")


def _is_retryable_url_error(e: urllib.error.URLError) -> bool:
    return not isinstance(e, urllib.error.HTTPError) or getattr(e, "code", 0) in (
        408,
        429,
        500,
        502,
        503,
        504,
    )


class HttpManifestSource(ManifestSource):
    def __init__(self, base_url: str, timeout: float = 10.0, max_bytes: int = 1_048_576):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_bytes = max_bytes

    def fetch_with_etag(self, channel: str, etag: str | None = None) -> tuple[bytes, str | None]:
        import time

        from trace_core.updates.errors import UpdateError

        url = f"{self.base_url}/{channel}.json"
        _validate_manifest_url(url)

        opener = urllib.request.build_opener(_HttpsRedirectGuard)
        headers = {"Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        request = urllib.request.Request(url, headers=headers)
        data, response_etag, attempt = b"", None, 0
        while True:
            attempt += 1
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    if response.status == 304:
                        raise _NotModified()
                    content_type = response.headers.get("Content-Type", "")
                    if "json" not in content_type:
                        raise UpdateError(f"unexpected manifest content type {content_type!r}")
                    data = response.read(self.max_bytes + 1)
                    response_etag = response.headers.get("ETag")
                    break
            except _NotModified:
                raise
            except urllib.error.URLError as e:
                if _is_retryable_url_error(e) and attempt < 3:
                    time.sleep(attempt)
                    continue
                raise UpdateError(f"manifest download failed: {e}") from e
        if len(data) > self.max_bytes:
            raise UpdateError("manifest response too large")
        return data, response_etag

    def fetch(self, channel: str) -> bytes:
        data, _ = self.fetch_with_etag(channel)
        return data


def source_for(target: str) -> ManifestSource:
    if target.startswith((_HTTPS_PREFIX, _HTTP_PREFIX)):
        return HttpManifestSource(target.rsplit("/", 1)[0])
    return LocalManifestSource(target)
