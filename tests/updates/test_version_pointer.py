"""An unreadable version pointer must not be reported as "you're up to date".

`get_installed_version` caught OSError and fell through to the package version, so an
install whose pointer could not be read claimed to be on a known version — and
`update install` exited 0 with a green "You're up to date". A newer-than-real fallback
would also have offered a downgrade.
"""

import pytest


def test_an_absent_pointer_is_normal_and_falls_back(monkeypatch) -> None:
    """Source checkouts and plain pip installs have no pointer. That is not a fault."""
    from trace_core.updates import checker

    monkeypatch.setattr(checker, "pointer_version", lambda: (None, None))
    from trace_core.core.settings import settings

    assert checker.get_installed_version() == settings.version


def test_pointer_version_distinguishes_absent_from_unreadable(tmp_path, monkeypatch) -> None:
    """The single difference that matters. Absent means source mode and the package version
    is authoritative; unreadable means the real version is unknown and must be reported."""
    import trace_updater.updater as updater_mod
    from trace_core.updates import checker

    monkeypatch.setattr(updater_mod, "install_root", lambda: tmp_path)
    (tmp_path / "active-version").write_text("1.2.3", encoding="utf-8")
    version, problem = checker.pointer_version()
    assert version == "1.2.3", version
    assert problem is None, problem

    def _refused(_base):
        raise PermissionError(13, "access denied")

    monkeypatch.setattr(updater_mod, "read_active", _refused)
    version, problem = checker.pointer_version()
    assert version is None, "an unreadable pointer must not yield a version"
    assert "could not be read" in str(problem), problem

    monkeypatch.setattr(updater_mod, "read_active", lambda _b: None)
    version, problem = checker.pointer_version()
    assert version is None
    assert problem is None, "an absent pointer is normal and must not be reported as a problem"


def test_install_refuses_when_the_version_cannot_be_determined(monkeypatch, signed_release, temp_storage_root):
    from trace_core.updates import checker
    from trace_core.updates.errors import UpdateError

    monkeypatch.setattr(checker, "pointer_version", lambda: (None, "the version pointer could not be read"))
    _v, manifest_path, art_path, _ = signed_release()
    from trace_core.updates.commands import load_update

    with pytest.raises(UpdateError, match="cannot tell which version is installed"):
        load_update(str(manifest_path), str(art_path))


def test_install_still_works_when_the_pointer_is_fine(monkeypatch, signed_release, temp_storage_root):
    """The refusal must not fire on the normal path."""
    from trace_core.updates import checker
    from trace_core.updates.commands import load_update

    monkeypatch.setattr(checker, "pointer_version", lambda: ("1.0.0", None))
    _v, manifest_path, art_path, _ = signed_release()
    manifest, _target, current, _entry = load_update(str(manifest_path), str(art_path))
    assert current == "1.0.0", current
    assert manifest is not None


def test_the_check_card_says_the_version_is_unknown(monkeypatch) -> None:
    from trace_core.core.ui.renderers import console
    from trace_core.updates.renderers import render_check_card

    payload = {
        "current": "0.3.0",
        "version_problem": "the version pointer could not be read",
        "available": False,
        "security_update": False,
        "minimum_supported_version": None,
        "restart_required": False,
        "installable": False,
        "target": "1.5.0",
    }
    with console.capture() as cap:
        render_check_card(payload, "stable")
    out = " ".join(cap.get().split())
    assert "Couldn't tell which version is installed" in out, out
    assert "You're up to date" not in out, out
    assert "Nothing was changed" in out, out


def test_the_check_card_still_reports_up_to_date_normally(monkeypatch) -> None:
    from trace_core.core.ui.renderers import console
    from trace_core.updates.renderers import render_check_card

    payload = {
        "current": "0.3.0",
        "version_problem": None,
        "available": False,
        "security_update": False,
        "minimum_supported_version": None,
        "restart_required": False,
        "installable": False,
        "target": "1.5.0",
    }
    with console.capture() as cap:
        render_check_card(payload, "stable")
    out = " ".join(cap.get().split())
    assert "You're up to date" in out, out
    assert "Couldn't tell" not in out, out
