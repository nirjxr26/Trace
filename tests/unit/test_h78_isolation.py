"""H-78: tests must not share one install_root, or write into the checkout."""

from __future__ import annotations

from pathlib import Path


def test_storage_root_is_not_shared_with_install_root(temp_storage_root: Path) -> None:
    """H-78: install_root() and trust_root() derive from storage_root.parent.

    With storage_root set to tmp_path, that parent was pytest's per-session directory —
    shared by every test in the run. The fixture now nests a "storage" dir so every
    derived root stays under this test's own tmp_path.
    """
    from trace_updater import updater as updater_mod

    base = updater_mod.install_root()
    assert base.parent == temp_storage_root.parent, f"install_root parent drifted: {base}"


def test_trust_root_is_also_isolated(temp_storage_root: Path) -> None:
    from trace_core.updates.trust import trust_root

    root = trust_root()
    # Both derive from storage_root, so per-test isolation is what matters.
    assert str(root).startswith(str(temp_storage_root.parent)), f"trust_root escaped: {root}"


def test_two_fixtures_never_share_a_root(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Two separate storages must not resolve to the same install/trust root."""
    from trace_core.core.settings import settings
    from trace_updater import updater as updater_mod

    roots = []
    for name in ("alpha", "beta"):
        candidate = tmp_path / name / "storage"
        candidate.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "storage_root", candidate)
        roots.append(updater_mod.install_root())
    assert roots[0] != roots[1], f"two tests shared install_root {roots[0]}"


def test_fixture_does_not_point_into_the_checkout(temp_storage_root: Path) -> None:
    """The CI default was the relative ./.test_storage, making install_root ./install."""
    assert not str(temp_storage_root).startswith(".test_storage")
    assert Path(temp_storage_root).is_absolute()


def test_conftest_session_default_is_not_the_checkout() -> None:
    """H-78's worst case: the session default TRACE_STORAGE_ROOT was './.test_storage',
    a relative path. install_root() then became './install' and trust_root()
    './trust/releases' — inside the repository — on every CI run."""
    src = (Path(__file__).resolve().parents[1] / "conftest.py").read_text(encoding="utf-8")
    line = next(
        ln for ln in src.splitlines() if ln.strip().startswith('os.environ["TRACE_STORAGE_ROOT"] =')
    )
    assert '"./.test_storage"' not in line, "session default is still the relative in-checkout path"
    # The default must be a real absolute temp dir, not something reconstructed from cwd.
    assert "tmp_path_factory" in src, "session default must come from a temp factory"
    assert "mktemp" in src, "the storage root must be a fresh temp dir per session"


def test_derived_roots_are_never_inside_the_repository(temp_storage_root: Path) -> None:
    """The actual harm: derived roots must not land in the working tree."""
    from trace_core.updates.trust import trust_root
    from trace_updater import updater as updater_mod

    repo = Path.cwd()
    for derived in (updater_mod.install_root(), trust_root()):
        assert not str(derived).startswith(str(repo)), f"{derived} points inside the checkout"