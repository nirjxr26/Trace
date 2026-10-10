import pytest

from trace_core.core.cli.registry import ShellContext
from trace_core.updates.shell_handler import UpdateShellCommandHandler

pytestmark = pytest.mark.unit


def test_the_handler_is_registered() -> None:
    from trace_core.core.cli.catalog import default_handlers

    assert any(h.command_name == "update" for h in default_handlers())


def test_bare_update_prints_help(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: list[str] = []
    monkeypatch.setattr("trace_core.core.ui.renderers.console.print", lambda *a, **k: printed.append(str(a[0])))

    assert UpdateShellCommandHandler().execute("", [], ShellContext()) is True
    assert any("update check" in line for line in printed)


def test_check_renders_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    from trace_core.updates import checker, renderers

    seen: list[tuple[object, str]] = []
    monkeypatch.setattr(checker, "resolve_channel", lambda _s: "stable")
    monkeypatch.setattr(checker, "resolve_manifest_target", lambda _s: "https://example.test/stable.json")
    monkeypatch.setattr(checker, "cached_check", lambda target, channel: {"target": "9.9.9"})
    monkeypatch.setattr(renderers, "render_check_card", lambda payload, channel: seen.append((payload, channel)))

    assert UpdateShellCommandHandler().execute("check", [], ShellContext()) is True
    assert seen == [({"target": "9.9.9"}, "stable")]


def test_install_refuses_and_points_at_the_standalone_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: list[str] = []
    monkeypatch.setattr("trace_core.core.ui.renderers.console.print", lambda *a, **k: printed.append(str(a[0])))

    assert UpdateShellCommandHandler().execute("install", [], ShellContext()) is True
    assert any("trace update install --yes" in line for line in printed)


def test_an_unknown_action_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "trace_core.core.ui.renderers.render_error_card",
        lambda title, message, remediation=None: rendered.append((title, message)),
    )

    assert UpdateShellCommandHandler().execute("frobnicate", [], ShellContext()) is False
    assert [title for title, _ in rendered] == ["Unknown Update Action"]


def test_completions_offer_only_update_flags() -> None:
    handler = UpdateShellCommandHandler()
    assert handler.get_completions("update ", None) == ["check", "install"]
    assert handler.get_completions("update check --", None) == ["--output", "--manifest"]
    assert handler.get_completions("update check -o", None) == ["-o"]
    assert handler.get_completions("update install --y", None) == ["--yes"]
    assert handler.get_completions("case ", None) == []


def test_help_entries_fit_the_shared_grid() -> None:
    from trace_core.cli.shell import HELP_GRID_SYNTAX_WIDTH

    for syntax, _alias, _desc in UpdateShellCommandHandler().get_help_entries():
        assert len(syntax) <= HELP_GRID_SYNTAX_WIDTH, syntax
