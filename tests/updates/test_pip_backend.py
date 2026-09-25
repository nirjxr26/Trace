"""Tribunal tests for the pip backend: venv layouts upgrade via pip, frozen never does."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from trace_core.updates import pip_backend
from trace_core.updates.errors import UpdateError

pytestmark = pytest.mark.unit


def _manifest(version="0.2.3"):  # type: ignore[no-untyped-def]
    from trace_core.updates.manifest import load_manifest_dict

    return load_manifest_dict(
        {
            "schema": 1,
            "product": "trace",
            "channel": "stable",
            "version": version,
            "release_id": "r1",
            "security_update": False,
            "restart_required": True,
            "manifest_signature": "00",
            "signing_key_id": "ed25519:" + "0" * 16,
            "artifacts": {
                f"pkg-{version}.whl": {
                    "filename": f"pkg-{version}.whl",
                    "sha256": "0" * 64,
                    "size": 1,
                    "signature": None,
                    "signing_key_id": None,
                }
            },
        }
    )


def _force_venv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Deterministic venv detection regardless of the test runner's interpreter."""
    monkeypatch.setattr(pip_backend, "venv_python", lambda: tmp_path / "venv" / "python")


def test_layout_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _force_venv(monkeypatch, tmp_path)
    assert pip_backend.pip_layout_for(tmp_path / "pkg-0.2.3.whl") is True
    assert pip_backend.pip_layout_for(tmp_path / "pkg-0.2.3.bin") is False
    monkeypatch.setattr(pip_backend, "venv_python", lambda: None)
    assert pip_backend.pip_layout_for(tmp_path / "pkg-0.2.3.whl") is False


def test_install_failure_is_typed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*a, **k):  # type: ignore[no-untyped-def]
        return SimpleNamespace(returncode=1, stdout="", stderr="no vem here")

    monkeypatch.setattr(pip_backend.subprocess, "run", boom)
    with pytest.raises(UpdateError, match="pip install failed"):
        pip_backend.pip_install_wheel(tmp_path / "python", tmp_path / "pkg.whl")


def test_install_unstartable_is_typed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def missing(*a, **k):  # type: ignore[no-untyped-def]
        raise OSError("no such interpreter")

    monkeypatch.setattr(pip_backend.subprocess, "run", missing)
    with pytest.raises(UpdateError, match="failed to start"):
        pip_backend.pip_install_wheel(tmp_path / "python", tmp_path / "pkg.whl")


def test_installed_version_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _force_venv(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pip_backend.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="TRACE_VERSION=0.2.3\n", stderr="warn noise\n"),
    )
    assert pip_backend.pip_installed_version() == "0.2.3"
    monkeypatch.setattr(
        pip_backend.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert pip_backend.pip_installed_version() is None


def test_installed_version_ignores_stdout_noise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _force_venv(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pip_backend.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="2026-09-25 10:40:25 [warning] shipped default credentials\nTRACE_VERSION=9.9.9\n",
            stderr="",
        ),
    )
    assert pip_backend.pip_installed_version() == "9.9.9"


def test_restore_skips_without_wheel(tmp_path: Path) -> None:
    base = tmp_path / "install"
    (base / "releases" / "0.2.2").mkdir(parents=True)
    assert pip_backend.restore_release(base, "0.2.2") is False


def test_restore_refuses_ambiguous_wheels(tmp_path: Path) -> None:
    base = tmp_path / "install"
    prev = base / "releases" / "0.2.2"
    prev.mkdir(parents=True)
    (prev / "a.whl").write_bytes(b"a")
    (prev / "b.whl").write_bytes(b"b")
    with pytest.raises(UpdateError, match="ambiguous"):
        pip_backend.restore_release(base, "0.2.2")


def test_health_proves_pip_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manifest()
    staged = tmp_path / "pkg-0.2.3.whl"
    _force_venv(monkeypatch, tmp_path)
    monkeypatch.setattr(pip_backend, "pip_installed_version", lambda *a, **k: "0.2.3")
    assert pip_backend.pip_health(m, staged) is True
    monkeypatch.setattr(pip_backend, "pip_installed_version", lambda *a, **k: "0.2.1")
    assert pip_backend.pip_health(m, staged) is False
    # Frozen artifacts and missing paths never consult pip.
    assert pip_backend.pip_health(m, tmp_path / "pkg.bin") is True
    assert pip_backend.pip_health(m, None) is True


def test_rollback_reinstalls_previous_wheel(tmp_path, session_manager, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from trace_core.updates.migration import rollback_release
    from trace_updater.updater import read_active

    base = tmp_path / "install"
    prev = base / "releases" / "0.2.2"
    prev.mkdir(parents=True)
    wheel = prev / "trace-0.2.2-py3-none-any.whl"
    wheel.write_bytes(b"fake-wheel")
    (prev / "release.json").write_text(json.dumps({"version": "0.2.2", "release_id": "r", "schema_min": 1}))
    (base / "previous-version").write_text("0.2.2")
    calls: dict = {}

    def fake_install(python, wheel_path):  # type: ignore[no-untyped-def]
        calls["wheel"] = wheel_path

    _force_venv(monkeypatch, tmp_path)
    monkeypatch.setattr(pip_backend, "pip_install_wheel", fake_install)
    assert rollback_release(base, session_manager, None) == "0.2.2"
    assert calls["wheel"] == wheel
    assert read_active(base) == "0.2.2"
