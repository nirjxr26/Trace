"""H-05: the channel encoded in the manifest URL is authoritative."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _manifest_dict(channel: str) -> dict:  # type: ignore[type-arg]
    """Structurally valid manifest body. Signature fields stay empty — H-05 is about
    which URL gets fetched, so manifest signing is not what is under test here."""
    return {
        "schema": 1,
        "product": "trace",
        "channel": channel,
        "version": "9.9.9",
        "release_id": "r-beta",
        "security_update": False,
        "restart_required": False,
        "minimum_supported_version": "0.0.1",
        "manifest_signature": "",
        "signing_key_id": "",
        "artifacts": {
            "default": {"filename": "a.bin", "sha256": "0" * 64, "size": 1, "signature": "", "signing_key_id": ""}
        },
    }


def test_install_fetches_the_channel_in_the_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """H-05: `--manifest .../beta.json` on a stable install fetched stable.json.

    source_for() discarded the channel encoded in the URL and .fetch(channel) rebuilt
    `{base}/{channel}.json` from the caller's channel instead.
    """
    from trace_core.updates import checker
    from trace_core.updates.sources import HttpManifestSource

    fetched: list[str] = []

    def _fake_fetch(self: object, channel: str) -> bytes:
        fetched.append(channel)
        return json.dumps(_manifest_dict(channel)).encode()

    monkeypatch.setattr(HttpManifestSource, "fetch", _fake_fetch)
    manifest, target = checker.load_manifest_auto("https://updates.example.com/beta.json", channel="stable")

    assert fetched == ["beta"], f"URL channel was discarded; fetched {fetched}"
    assert manifest.channel == "beta"
    assert target == "https://updates.example.com/beta.json"


def test_split_manifest_url_is_the_single_channel_source() -> None:
    from trace_core.updates.sources import split_manifest_url

    assert split_manifest_url("https://h/beta.json") == ("https://h", "beta")
    assert split_manifest_url("https://h/stable.json") == ("https://h", "stable")
    assert split_manifest_url("https://h/base") == ("https://h/base", "stable")


def test_checker_no_longer_rebuilds_the_url_from_the_caller_channel() -> None:
    import inspect

    from trace_core.updates import checker

    src = inspect.getsource(checker.load_manifest_auto)
    assert ".fetch(channel)" not in src, "the caller's channel must not override the URL"
    assert ".fetch(url_channel)" in src


def test_local_manifest_ignores_channel_entirely(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trace_core.updates import checker

    path = tmp_path / "beta.json"
    body = _manifest_dict("beta")
    body["release_id"] = "r-local"
    path.write_text(json.dumps(body), encoding="utf-8")
    manifest, target = checker.load_manifest_auto(path, channel="stable")
    assert manifest.channel == "beta"
    assert target == str(path)


@pytest.mark.parametrize("channel", ["beta", "nightly", "stable"])
def test_every_channel_survives_the_round_trip(channel: str) -> None:
    from trace_core.updates.sources import split_manifest_url

    base, parsed = split_manifest_url(f"https://updates.example.com/{channel}.json")
    assert base == "https://updates.example.com"
    assert parsed == channel
