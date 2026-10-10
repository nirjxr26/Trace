"""A refused response must not be blamed on the network.

Both the manifest size cap and the artifact size cap raised UpdateNetworkError, whose
remedy is "Check network connectivity and manifest URL, then retry". Retrying the same URL
returns the same oversized response, so the advice could never work — on the one procedure
most likely to run unattended.
"""

import pytest


def _resolve(exc: Exception):
    from trace_core.core.cli.error_handler import _resolve_error_details

    return _resolve_error_details(exc, None, None)


def test_a_refused_response_is_not_told_to_check_connectivity() -> None:
    from trace_core.updates.errors import UpdateResponseRefused

    title, message, remedy, code = _resolve(UpdateResponseRefused("manifest response exceeded 5242880 bytes"))
    assert title == "Update Response Refused", title
    assert "connectivit" not in remedy.lower(), remedy
    assert "network" not in remedy.lower(), remedy
    assert code != 0
    assert "Nothing was installed" in remedy, remedy


def test_a_real_network_fault_still_says_check_connectivity() -> None:
    """The distinction has to survive both ways."""
    from trace_core.updates.errors import UpdateNetworkError

    _title, _message, remedy, _code = _resolve(UpdateNetworkError("manifest download failed: timed out"))
    assert "connectivit" in remedy.lower(), remedy


def test_an_oversized_manifest_is_refused_not_a_network_error() -> None:
    from trace_core.updates import sources

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self, _n):  # type: ignore[no-untyped-def]
            return b"x" * 100

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_a):  # type: ignore[no-untyped-def]
            return False

    from trace_core.updates.errors import UpdateNetworkError, UpdateResponseRefused

    with pytest.raises(UpdateResponseRefused):
        sources._read_manifest_response(_Response(), 10)
    assert not issubclass(UpdateResponseRefused, UpdateNetworkError)


def test_a_wrong_content_type_is_refused_with_a_reason() -> None:
    from trace_core.updates import sources
    from trace_core.updates.errors import UpdateResponseRefused

    class _Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def read(self, _n):  # type: ignore[no-untyped-def]
            return b"<html>"

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_a):  # type: ignore[no-untyped-def]
            return False

    with pytest.raises(UpdateResponseRefused, match="not JSON"):
        sources._read_manifest_response(_Response(), 1 << 20)


def test_a_normal_manifest_still_reads() -> None:
    from trace_core.updates import sources

    class _Response:
        status = 200
        headers = {"Content-Type": "application/json", "ETag": "abc"}

        def read(self, _n):  # type: ignore[no-untyped-def]
            return b'{"version": "1.0.0"}'

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_a):  # type: ignore[no-untyped-def]
            return False

    data, etag = sources._read_manifest_response(_Response(), 1 << 20)
    assert data == b'{"version": "1.0.0"}'
    assert etag == "abc"
