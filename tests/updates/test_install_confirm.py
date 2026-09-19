import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app

pytestmark = pytest.mark.unit


def test_install_refuses_without_yes_non_interactive(signed_release, temp_storage_root):
    _, manifest_path, art_path, _ = signed_release()
    res = CliRunner().invoke(app, ["update", "install", "--manifest", str(manifest_path), "--artifact", str(art_path)])
    assert res.exit_code != 0
    assert "--yes" in res.output


def test_install_with_yes_runs_lifecycle(
    signed_release, release_keys, temp_storage_root, session_manager, monkeypatch, tmp_path
):
    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    from trace_core.updates import signing

    signing.import_release_pubkey(release_keys["pub_hex"])
    _, manifest_path, art_path, _ = signed_release()
    res = CliRunner().invoke(
        app,
        ["update", "install", "--manifest", str(manifest_path), "--artifact", str(art_path), "--yes"],
    )
    assert res.exit_code == 0
    assert "SUCCESS" in res.output


def test_install_bypass_minimum_records_override(
    signed_release, release_keys, temp_storage_root, session_manager, monkeypatch, tmp_path
):
    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    from trace_core.updates import signing

    signing.import_release_pubkey(release_keys["pub_hex"])
    _, manifest_path, art_path, _ = signed_release(minimum_supported_version="9.9.9")
    blocked = CliRunner().invoke(
        app,
        ["update", "install", "--manifest", str(manifest_path), "--artifact", str(art_path), "--yes"],
    )
    assert blocked.exit_code == 14
    allowed = CliRunner().invoke(
        app,
        [
            "update",
            "install",
            "--manifest",
            str(manifest_path),
            "--artifact",
            str(art_path),
            "--yes",
            "--bypass-minimum",
        ],
    )
    assert allowed.exit_code == 0
    assert "minimum-supported-version bypassed" in allowed.output
