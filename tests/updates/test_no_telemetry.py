from pathlib import Path

BANNED_ANYWHERE = ("httpx", "requests", "aiohttp", "urllib3", "telemetry", "analytics")
NETWORK_ALLOWED_ONLY_IN = {"sources.py"}


def test_no_network_or_telemetry_imports():
    roots = [Path("src/trace_core/updates"), Path("src/trace_updater")]
    offenders = []
    network_outside = []
    for root in roots:
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in BANNED_ANYWHERE:
                if token in text:
                    offenders.append(f"{path}:{token}")
            if ("urlopen" in text or "urllib" in text) and path.name not in NETWORK_ALLOWED_ONLY_IN:
                network_outside.append(str(path))
    assert offenders == []
    assert network_outside == []
