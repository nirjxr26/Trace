"""End-to-end update proving against the real pip install path.

Drives the real `trace update` CLI against fake isolated machines, each with
its own install tree, sqlite database, storage root, and real venv with real
pip. Asserts end state, never output text: running version, pointer file,
database rows, and the durable update marker. Needs TRACE_E2E_WHEELS pointing at a directory
holding trace-0.2.3 and trace-0.2.4 release wheels, built from the v0.2.3 and
v0.2.4 tags (the CI `update-e2e` job builds them); unset means the module skips.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app

NEW_VERSION = "0.2.99"


@pytest.fixture(scope="module")
def old_wheels():
    raw = os.environ.get("TRACE_E2E_WHEELS", "").strip()
    if not raw:
        pytest.skip(
            "set TRACE_E2E_WHEELS to a directory holding the trace-0.2.3 and trace-0.2.4 "
            "release wheels to run the real install path"
        )
    wheels = {}
    for ver in ("0.2.3", "0.2.4"):
        p = Path(raw) / f"trace-{ver}-py3-none-any.whl"
        if not p.is_file():
            pytest.fail(f"TRACE_E2E_WHEELS is set to {raw} but {p.name} is missing there")
        wheels[ver] = p
    return wheels


@pytest.fixture(scope="module")
def box_venv(tmp_path_factory, old_wheels):
    """Shared box venv. System site packages stand in for a release venv's
    own dependency set; the venv-installed trace wheel always shadows repo
    source, even for isolated (-I) probes."""
    _ = old_wheels
    venv = tmp_path_factory.mktemp("e2e-venv") / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
        timeout=180,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert python.is_file()
    return python


@pytest.fixture
def serve_e2e():
    servers = []

    def _serve(routes):
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = routes.get(self.path)
                if raw is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield _serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _pip_install(python, wheel):
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", "--no-index", "--force-reinstall", str(wheel)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _venv_version(python):
    from trace_core.updates.pip_backend import pip_installed_version

    return pip_installed_version(python)


def _wheel_version(wheel_path):
    import re

    match = re.match(r"^trace-(.+)-py3-none-any\.whl$", wheel_path.name)
    assert match
    return match.group(1)


def _repack(old_wheel, dest_dir, new_version, patch_code):
    old_version = _wheel_version(old_wheel)
    with zipfile.ZipFile(old_wheel) as zin:
        names = zin.namelist()
        blob = {n: zin.read(n) for n in names}
    dist = next(n.split("/")[0] for n in names if n.endswith(".dist-info/METADATA"))
    new_dist = f"trace-{new_version}.dist-info"
    targets = [f"{dist}/METADATA"]
    if patch_code:
        targets = ["trace_core/__init__.py", "trace_core/core/settings.py"] + targets
    for path in targets:
        assert old_version.encode() in blob[path]
        blob[path] = blob[path].replace(old_version.encode(), new_version.encode())
    wheel_path = dest_dir / f"trace-{new_version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in blob.items():
            if name.startswith(dist + "/"):
                name = new_dist + name[len(dist) :]
            zout.writestr(name, data)
    return wheel_path


def _test_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from trace_core.updates import signing

    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    key_id = signing.import_release_pubkey(pub_hex)
    return priv, key_id


def _make_e2e_manifest(artifact_path, version, priv, key_id, **over):
    from trace_core.updates import signing
    from trace_core.updates.manifest import ReleaseManifest, load_manifest

    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    unsigned = {
        "schema": 1,
        "product": "trace",
        "channel": "stable",
        "version": version,
        "release_id": over.get("release_id", f"e2e-{version}"),
        "security_update": over.get("security_update", False),
        "restart_required": over.get("restart_required", True),
        "manifest_signature": "",
        "signing_key_id": "",
        "artifacts": {
            "default": {
                "filename": artifact_path.name,
                "sha256": digest,
                "size": artifact_path.stat().st_size,
                "signature": "",
                "signing_key_id": "",
            }
        },
    }
    for key in (
        "minimum_supported_version",
        "notes",
        "schema_min",
        "schema_target",
        "backup_required",
        "backup_waiver",
    ):
        if key in over:
            unsigned[key] = over[key]
    art_sig = priv.sign(artifact_path.read_bytes()).hex()
    unsigned["artifacts"]["default"]["signature"] = art_sig
    unsigned["artifacts"]["default"]["signing_key_id"] = key_id
    probe = ReleaseManifest.model_validate(unsigned)
    unsigned["manifest_signature"] = priv.sign(signing.canonical_manifest_bytes(probe)).hex()
    unsigned["signing_key_id"] = key_id
    manifest_path = artifact_path.parent / f"e2e-manifest-{version}.json"
    manifest_path.write_text(json.dumps(unsigned), encoding="utf-8")
    return load_manifest(manifest_path), manifest_path


def _install_box(monkeypatch, tmp_path, *, venv_python, old_wheel, pointer_version, prev_wheel=None):
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.database.session import DatabaseSessionManager
    from trace_core.core.settings import settings
    from trace_updater import updater as updater_mod

    box = tmp_path / "box"
    monkeypatch.setattr(settings, "storage_root", box / "storage")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    monkeypatch.setattr("trace_core.updates.pip_backend.venv_python", lambda: venv_python)
    manager = DatabaseSessionManager(f"sqlite:///{box / 'e2e.db'}")
    with manager.session():
        pass
    _pip_install(venv_python, old_wheel)
    base = updater_mod.install_root()
    base.mkdir(parents=True, exist_ok=True)
    (base / "active-version").write_text(pointer_version, encoding="utf-8")
    if prev_wheel is not None:
        prev_version = _wheel_version(prev_wheel)
        (base / "previous-version").write_text(prev_version, encoding="utf-8")
        prevdir = base / "releases" / prev_version
        prevdir.mkdir(parents=True)
        shutil.copy(prev_wheel, prevdir / prev_wheel.name)
        (prevdir / "release.json").write_text(
            json.dumps({"version": prev_version, "release_id": "seed", "schema_min": None, "schema_target": None}),
            encoding="utf-8",
        )
    case = CaseService(manager).create_case(CaseCreateDto(title="e2e", lead_examiner="e2e"))
    priv, key_id = _test_keys()
    return SimpleNamespace(box=box, base=base, manager=manager, case_number=case.number, priv=priv, key_id=key_id)


def _serve_release(serve_e2e, manifest_path, wheel_path):
    routes = {"/stable.json": manifest_path.read_bytes(), f"/{wheel_path.name}": wheel_path.read_bytes()}
    return serve_e2e(routes) + "/stable.json"


def _install_cli(*args):
    return CliRunner().invoke(app, ["update", "install", *args])


def _result_marker():
    from trace_core.updates.marker import read_marker

    return read_marker()


def _run_upgrade_flow(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    from trace_core.cases.service import CaseService

    work = tmp_path / "work"
    work.mkdir()
    new_wheel = _repack(old_wheels["0.2.4"], work, NEW_VERSION, patch_code=True)
    machine = _install_box(
        monkeypatch, tmp_path, venv_python=box_venv, old_wheel=old_wheels["0.2.4"], pointer_version="0.2.4"
    )
    _, manifest_path = _make_e2e_manifest(new_wheel, NEW_VERSION, machine.priv, machine.key_id)
    target = _serve_release(serve_e2e, manifest_path, new_wheel)
    res = _install_cli("--manifest", target, "--yes")
    assert res.exit_code == 0, res.output
    assert _venv_version(box_venv) == NEW_VERSION
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == NEW_VERSION
    marker = _result_marker()
    assert marker["previous_version"] == "0.2.4"
    assert marker["target_version"] == NEW_VERSION
    assert marker["state"] == "COMPLETED"
    assert CaseService(machine.manager).get_case(machine.case_number).number == machine.case_number


def test_e2e_upgrade_old_to_new(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    _run_upgrade_flow(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e)


def test_e2e_upgrade_default_credentials_succeeds(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    from trace_core.core.settings import Settings

    monkeypatch.setenv("TRACE_DATABASE_URL", Settings.model_fields["database_url"].default)
    _run_upgrade_flow(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e)


def test_e2e_minimum_blocked_no_side_effects(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    from trace_core.core.settings import settings

    work = tmp_path / "work"
    work.mkdir()
    new_wheel = _repack(old_wheels["0.2.3"], work, NEW_VERSION, patch_code=True)
    machine = _install_box(
        monkeypatch, tmp_path, venv_python=box_venv, old_wheel=old_wheels["0.2.3"], pointer_version="0.2.2"
    )
    _, manifest_path = _make_e2e_manifest(
        new_wheel,
        NEW_VERSION,
        machine.priv,
        machine.key_id,
        minimum_supported_version="9.9.9",
        notes="e2e migration notes",
    )
    target = _serve_release(serve_e2e, manifest_path, new_wheel)
    monkeypatch.setattr(settings, "update_manifest", target)
    check = CliRunner().invoke(app, ["update", "check"])
    assert check.exit_code == 0
    assert "deferred" in check.output.lower()
    assert "e2e migration notes" in check.output
    res = _install_cli("--manifest", target, "--yes")
    assert res.exit_code != 0
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == "0.2.2"
    assert _venv_version(box_venv) == "0.2.3"


def test_e2e_bypass_recorded(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    work = tmp_path / "work"
    work.mkdir()
    new_wheel = _repack(old_wheels["0.2.3"], work, NEW_VERSION, patch_code=True)
    machine = _install_box(
        monkeypatch, tmp_path, venv_python=box_venv, old_wheel=old_wheels["0.2.3"], pointer_version="0.2.2"
    )
    _, manifest_path = _make_e2e_manifest(
        new_wheel, NEW_VERSION, machine.priv, machine.key_id, minimum_supported_version="9.9.9"
    )
    target = _serve_release(serve_e2e, manifest_path, new_wheel)
    res = _install_cli("--manifest", target, "--yes", "--bypass-minimum")
    assert res.exit_code == 0, res.output
    assert _result_marker()["state"] == "COMPLETED"
    assert _venv_version(box_venv) == NEW_VERSION
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == NEW_VERSION


def test_e2e_corrupt_artifact_rejected(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    work = tmp_path / "work"
    work.mkdir()
    new_wheel = _repack(old_wheels["0.2.4"], work, NEW_VERSION, patch_code=True)
    machine = _install_box(
        monkeypatch, tmp_path, venv_python=box_venv, old_wheel=old_wheels["0.2.4"], pointer_version="0.2.4"
    )
    _, manifest_path = _make_e2e_manifest(new_wheel, NEW_VERSION, machine.priv, machine.key_id)
    raw = new_wheel.read_bytes()
    routes = {"/stable.json": manifest_path.read_bytes(), f"/{new_wheel.name}": raw[:-8] + b"tampered"}
    target = serve_e2e(routes) + "/stable.json"
    res = _install_cli("--manifest", target, "--yes")
    assert res.exit_code == 11
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == "0.2.4"
    assert _venv_version(box_venv) == "0.2.4"


def test_e2e_bad_signature_rejected(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    work = tmp_path / "work"
    work.mkdir()
    new_wheel = _repack(old_wheels["0.2.4"], work, NEW_VERSION, patch_code=True)
    machine = _install_box(
        monkeypatch, tmp_path, venv_python=box_venv, old_wheel=old_wheels["0.2.4"], pointer_version="0.2.4"
    )
    rogue = Ed25519PrivateKey.generate()
    _, manifest_path = _make_e2e_manifest(new_wheel, NEW_VERSION, rogue, "ed25519:0000000000000000")
    target = _serve_release(serve_e2e, manifest_path, new_wheel)
    res = _install_cli("--manifest", target, "--yes")
    assert res.exit_code == 11
    staging = machine.base / "staging"
    assert not staging.exists() or list(staging.iterdir()) == []
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == "0.2.4"


def test_e2e_migration_incompatible_rejected(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    work = tmp_path / "work"
    work.mkdir()
    new_wheel = _repack(old_wheels["0.2.4"], work, NEW_VERSION, patch_code=True)
    machine = _install_box(
        monkeypatch, tmp_path, venv_python=box_venv, old_wheel=old_wheels["0.2.4"], pointer_version="0.2.4"
    )
    _, manifest_path = _make_e2e_manifest(
        new_wheel, NEW_VERSION, machine.priv, machine.key_id, schema_min=99999, schema_target=99999
    )
    target = _serve_release(serve_e2e, manifest_path, new_wheel)
    res = _install_cli("--manifest", target, "--yes")
    assert res.exit_code != 0
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == "0.2.4"
    assert _result_marker()["state"] == "FAILED"


def test_e2e_rollback_restores_running_version(monkeypatch, tmp_path, box_venv, old_wheels, serve_e2e):
    work = tmp_path / "work"
    work.mkdir()
    lying_wheel = _repack(old_wheels["0.2.4"], work, NEW_VERSION, patch_code=False)
    machine = _install_box(
        monkeypatch,
        tmp_path,
        venv_python=box_venv,
        old_wheel=old_wheels["0.2.4"],
        pointer_version="0.2.4",
        prev_wheel=old_wheels["0.2.3"],
    )
    _, manifest_path = _make_e2e_manifest(lying_wheel, NEW_VERSION, machine.priv, machine.key_id)
    target = _serve_release(serve_e2e, manifest_path, lying_wheel)
    res = _install_cli("--manifest", target, "--yes")
    assert "The update was rolled back." in res.output
    assert _result_marker()["state"] == "ROLLED_BACK"
    assert (machine.base / "active-version").read_text(encoding="utf-8").strip() == "0.2.3"
    assert _venv_version(box_venv) == "0.2.3"
