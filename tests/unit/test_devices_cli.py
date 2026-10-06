"""CLI tribunal: the device sub-app is registered, reachable, and exits semantically."""

import json
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.core.cli.exit_codes import EXIT_NOT_FOUND, EXIT_SUCCESS
from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT

runner = CliRunner()
pytestmark = pytest.mark.unit


def _payload(out: str) -> Any:
    return json.loads(out)


def test_the_device_app_is_registered() -> None:
    from trace_core.core.cli.catalog import feature_apps

    assert any(name == "device" for name, _ in feature_apps())


def test_the_shell_handler_is_registered() -> None:
    from trace_core.core.cli.catalog import default_handlers

    assert any(handler.command_name == "device" for handler in default_handlers())


def test_list_renders_a_table(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "list"])
    assert result.exit_code == EXIT_SUCCESS
    assert "disk-a.dd" in result.stdout
    assert "disk-b.dd" in result.stdout


def test_list_json_is_machine_readable(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "list", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = _payload(result.stdout)
    assert [entry["node"] for entry in payload] == [
        str(device_file_env / "disk-a.dd"),
        str(device_file_env / "disk-b.dd"),
    ]


def test_list_filters_by_kind(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "list", "--kind", "file", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert len(_payload(result.stdout)) == 2
    assert runner.invoke(app, ["device", "list", "--kind", "os", "--output", "json"]).stdout.count("node") == 0


def test_list_rejects_an_unknown_kind(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "list", "--kind", "floppy"])
    assert result.exit_code != EXIT_SUCCESS
    assert "unknown device kind" in result.stdout


def test_inspect_captures_and_reports(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "inspect", str(device_file_env / "disk-a.dd"), "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = _payload(result.stdout)
    assert payload["fingerprint"]["serial"].startswith("SYNTH-")
    assert payload["fingerprint"]["capacity_bytes"] == 2048


def test_check_reports_read_only_and_exits_zero(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "check", str(device_file_env / "disk-a.dd"), "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert _payload(result.stdout)["verdict"] == "READ_ONLY"


@pytest.mark.parametrize("argv", (["list"], ["list", "--kind", "file"]))
def test_json_output_is_the_only_thing_on_stdout(device_file_env: Path, argv: list[str]) -> None:
    """A trailing confirmation line makes `--output json` unparseable for an examiner."""
    result = runner.invoke(app, ["device", *argv, "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert _payload(result.stdout) is not None


def test_check_json_output_is_pure_json(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "check", str(device_file_env / "disk-a.dd"), "--output", "json"])
    assert _payload(result.stdout)["verdict"] == "READ_ONLY"


def test_a_long_field_survives_the_json_contract(device_file_env: Path) -> None:
    """Rich must not hard-wrap a JSON string at the console width."""
    long_name = f"{'n' * 120}.dd"
    disk = device_file_env / long_name
    disk.write_bytes(b"z" * 4096)
    result = runner.invoke(app, ["device", "list", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert long_name in [entry["model_hint"] for entry in _payload(result.stdout)]


def test_an_unenumerated_node_exits_not_found(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "check", str(device_file_env / "absent.dd")])
    assert result.exit_code == EXIT_NOT_FOUND
    assert "device list" in result.stdout


def test_an_unenumerated_node_on_inspect_also_exits_not_found(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "inspect", str(device_file_env / "absent.dd")])
    assert result.exit_code == EXIT_NOT_FOUND


def test_no_adapter_configured_refuses_rather_than_enumerating_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.delenv(ENV_DEVICE_ROOT, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "innocent.txt").write_text("not a device")
    result = runner.invoke(app, ["device", "list"])
    assert result.exit_code != EXIT_SUCCESS
    assert ENV_DEVICE_ROOT in result.stdout
    assert "innocent.txt" not in result.stdout


def test_an_unexpected_error_is_never_reported_as_unknown(
    device_file_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§14.10: exit 9 is the device preflight UNKNOWN outcome and nothing else."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr("trace_core.devices.commands.do_check", _boom)
    result = runner.invoke(app, ["device", "check", str(device_file_env / "disk-a.dd")])
    assert result.exit_code != 9
    assert result.exit_code == 1


def test_a_writable_source_exits_ten(monkeypatch: pytest.MonkeyPatch, device_file_env: Path) -> None:
    from datetime import datetime

    from trace_core.devices.domain import ProtectionCheck, ProtectionEvidence, WpVerdict, WriteProtectionError

    evidence = ProtectionEvidence(
        platform="fake",
        checks=(ProtectionCheck(name="exists", result="True"),),
        adapter_version="file",
        checked_at=datetime.now(UTC),
    )

    def _writable(*_args, **_kwargs):
        raise WriteProtectionError("source is writable", WpVerdict.WRITABLE, evidence)

    monkeypatch.setattr("trace_core.devices.commands.do_check", _writable)
    result = runner.invoke(app, ["device", "check", str(device_file_env / "disk-a.dd")])
    assert result.exit_code == 10
    assert "writable" in result.stdout.lower()


def test_the_acknowledgement_flag_requires_confirmation(device_file_env: Path) -> None:
    result = runner.invoke(
        app, ["device", "check", str(device_file_env / "disk-a.dd"), "--acknowledge-unverified-source"], input="n\n"
    )
    assert "cancelled" in result.stdout.lower()
    assert result.exit_code == EXIT_SUCCESS


def test_the_acknowledgement_flag_proceeds_when_confirmed(device_file_env: Path) -> None:
    result = runner.invoke(
        app, ["device", "check", str(device_file_env / "disk-a.dd"), "--acknowledge-unverified-source"], input="y\n"
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "READ_ONLY" in result.stdout


def test_yes_skips_the_acknowledgement_prompt(device_file_env: Path) -> None:
    result = runner.invoke(
        app, ["device", "check", str(device_file_env / "disk-a.dd"), "--acknowledge-unverified-source", "--yes"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "READ_ONLY" in result.stdout


def test_help_documents_only_flags_the_handler_accepts() -> None:
    """Help that names a flag the parser rejects is worse than no help."""
    from trace_core.devices import shell_handler as handler_module
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    accepted = set(handler_module._LIST_FLAGS) | set(handler_module._CHECK_FLAGS) | set(handler_module._SHOW_FLAGS)
    for usage, _alias, _desc in DeviceShellCommandHandler().get_help_entries():
        for token in usage.split()[1:]:
            if token.startswith("-"):
                assert token in accepted, f"help advertises {token!r}, which the handler does not accept"


def test_the_short_ack_alias_really_overrides(device_file_env: Path) -> None:
    from trace_core.devices.shell_handler import _ACK_FLAGS, DeviceShellCommandHandler

    handler = DeviceShellCommandHandler()
    node = str(device_file_env / "disk-a.dd")
    for flag in _ACK_FLAGS:
        assert handler.execute("check", [node, flag, "--output", "json"], None) is True


def test_every_help_syntax_fits_the_shared_grid() -> None:
    from trace_core.cli.shell import HELP_GRID_SYNTAX_WIDTH
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    for usage, _alias, _desc in DeviceShellCommandHandler().get_help_entries():
        assert len(usage) <= HELP_GRID_SYNTAX_WIDTH, usage


def test_the_shell_handler_dispatches_list(device_file_env: Path) -> None:
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    assert DeviceShellCommandHandler().execute("list", ["--output", "json"], None) is True


def test_the_shell_handler_reports_an_unknown_action() -> None:
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    assert DeviceShellCommandHandler().execute("frobnicate", [], None) is False


def test_the_shell_handler_reports_a_missing_node() -> None:
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    assert DeviceShellCommandHandler().execute("check", [], None) is False


def test_the_shell_handler_completes_actions_and_flags() -> None:
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    handler = DeviceShellCommandHandler()
    assert ("check", "Verify write protection") in handler.get_completions("device ch", None)
    flags = [value for value, _meta in handler.get_completions("device check --", None)]
    assert any(f.startswith("--allow-real-hardware") for f in flags)


def test_no_handler_offers_completions_for_another_command() -> None:
    """The shell asks every handler for every line; a leak offers the wrong flags."""
    from trace_core.core.cli.catalog import default_handlers

    for line in ("device ", "device list --", "device check --", "case list --", "update ", "uninstall "):
        words = line.split()
        owners = [h.command_name for h in default_handlers() if h.get_completions(line, None)]
        assert owners == [words[0]], f"{line!r} answered by {owners}"


def test_the_completer_offers_device_actions_without_duplicates() -> None:
    from prompt_toolkit.document import Document

    from trace_core.cli.shell import InteractiveShell

    shell = InteractiveShell(service=None)
    values = [c.text for c in shell.completer.get_completions(Document("device "), None)]
    assert "list" in values
    assert "check" in values
    assert len(values) == len(set(values)), f"duplicate completions: {values}"


def test_device_is_discoverable_from_the_root() -> None:
    from prompt_toolkit.document import Document

    from trace_core.cli.shell import InteractiveShell

    shell = InteractiveShell(service=None)
    values = [c.text for c in shell.completer.get_completions(Document("dev"), None)]
    assert "device" in values
    assert "devices" in values


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["sda"], "sda"),
        (["--allow-real-hardware", "sda"], "sda"),
        (["--acknowledge-unverified-source", "sda"], "sda"),
        (["--ack-unverified", "sda"], "sda"),
        (["--yes", "sda"], "sda"),
        (["-y", "sda"], "sda"),
        (["--output", "json", "sda"], "sda"),
        (["--kind", "os", "sda"], "sda"),
        (["--kind=os", "sda"], "sda"),
        (["--output=json", "sda"], "sda"),
        (["-o", "json", "sda"], "sda"),
        (["--unknown-flag"], None),
        ([], None),
    ],
)
def test_shell_flag_parsing_never_swallows_the_node(args: list[str], expected: str | None) -> None:
    """A boolean flag must not consume the token after it as its value."""
    from trace_core.devices.shell_handler import _first_positional

    assert _first_positional(args) == expected


def test_the_shell_check_reaches_the_service_with_a_boolean_flag(device_file_env: Path, monkeypatch) -> None:
    from trace_core.devices import helpers as helpers_module
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    seen: dict[str, object] = {}
    real = helpers_module.do_check

    def _spy(_session, node, **kwargs):
        seen.update(kwargs)
        return real(_session, node, **kwargs)

    monkeypatch.setattr("trace_core.devices.helpers.do_check", _spy)
    assert (
        DeviceShellCommandHandler().execute(
            "check", ["--allow-real-hardware", "--output", "json", str(device_file_env / "disk-a.dd")], None
        )
        is True
    )
    assert seen["allow_real_hardware"] is True
    assert seen["acknowledge_unverified_source"] is False


def test_a_denied_drive_exits_with_elevation_guidance(device_file_env: Path, monkeypatch) -> None:
    from trace_core.devices.domain import DeviceAccessDeniedError

    def _denied(*_args, **_kwargs):
        raise DeviceAccessDeniedError("access denied for X; re-run from an elevated Administrator shell")

    monkeypatch.setattr("trace_core.devices.commands.do_check", _denied)
    result = runner.invoke(app, ["device", "check", str(device_file_env / "disk-a.dd")])
    assert result.exit_code == 1
    assert "elevated" in result.stdout


def test_the_list_table_shows_the_short_id(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "list"])
    assert result.exit_code == EXIT_SUCCESS
    assert "ID" in result.stdout
    assert "disk-a.dd" in result.stdout


def test_a_short_id_works_end_to_end_on_the_cli(device_file_env: Path) -> None:
    result = runner.invoke(app, ["device", "inspect", "disk-b.dd", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert _payload(result.stdout)["fingerprint"]["capacity_bytes"] == 1024


def test_the_shell_completes_device_nodes(device_file_env: Path) -> None:
    from trace_core.devices.shell_handler import DeviceShellCommandHandler

    handler = DeviceShellCommandHandler()
    values = [value for value, _ in handler.get_completions("device check disk", None)]
    assert any("disk-a.dd" in v for v in values)
    flags = [value for value, _ in handler.get_completions("device check --", None)]
    assert "--allow-real-hardware" in flags
