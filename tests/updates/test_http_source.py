import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from trace_core.updates.errors import UpdateError
from trace_core.updates.sources import HttpManifestSource, source_for

pytestmark = pytest.mark.unit


@pytest.fixture
def manifest_bytes(signed_release):
    manifest, _, _, _ = signed_release()
    return manifest.model_dump_json(by_alias=True).encode()


@pytest.fixture
def serve():
    servers = []

    def _serve(handler):
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield _serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _handler(body, content_type="application/json", code=200, location=None):
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            if location:
                self.send_response(code)
                self.send_header("Location", location)
                self.end_headers()
                return
            raw = body() if callable(body) else body
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    return _H


def test_http_fetch_ok(serve, manifest_bytes):
    base = serve(_handler(manifest_bytes))
    data = HttpManifestSource(base, timeout=5).fetch("stable")
    assert json.loads(data)["product"] == "trace"


def test_non_json_rejected(serve):
    base = serve(_handler(b"<html>nope</html>", content_type="text/html"))
    source = HttpManifestSource(base, timeout=5)
    with pytest.raises(UpdateError):
        source.fetch("stable")


def test_oversized_rejected(serve):
    base = serve(_handler(b"x" * 100))
    source = HttpManifestSource(base, timeout=5, max_bytes=10)
    with pytest.raises(UpdateError):
        source.fetch("stable")


def test_connection_failure_fails_closed():
    source = HttpManifestSource("http://127.0.0.1:1", timeout=2)
    with pytest.raises(UpdateError):
        source.fetch("stable")


def test_non_https_production_refused():
    source = HttpManifestSource("http://updates.example.com", timeout=2)
    with pytest.raises(UpdateError):
        source.fetch("stable")


def test_redirect_to_same_host_ok(serve, manifest_bytes):
    target = serve(_handler(manifest_bytes))
    port = target.rsplit(":", 1)[1]
    base = serve(_handler(b"", location=f"http://127.0.0.1:{port}/stable.json", code=302))
    data = HttpManifestSource(base, timeout=5).fetch("stable")
    assert json.loads(data)["product"] == "trace"


def test_source_for_routing(tmp_path):
    assert type(source_for("https://x.example.com/r/stable.json")).__name__ == "HttpManifestSource"
    assert type(source_for(str(tmp_path / "m.json"))).__name__ == "LocalManifestSource"


def test_checker_accepts_http_url(serve, manifest_bytes, temp_storage_root):
    from trace_core.updates.checker import check_for_update

    base = serve(_handler(manifest_bytes))
    res = check_for_update(f"{base}/stable.json", "stable")
    assert res["available"] is True
    assert res["installable"] is True
