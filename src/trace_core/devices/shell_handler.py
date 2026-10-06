"""REPL handler for device commands. Same cores as the Typer app; shell flow only."""

from typing import Any

from trace_core.core.cli.shell_base import BaseShellHandler

_ACTIONS = frozenset({"list", "ls", "inspect", "check", "help"})
_ACK_FLAGS = ("--acknowledge-unverified-source", "--ack-unverified")
_LIST_DEVICES_HELP = "List devices this adapter can see"
_ACTION_HELP = (
    ("list", _LIST_DEVICES_HELP),
    ("ls", _LIST_DEVICES_HELP),
    ("inspect", "Capture a fingerprint and record it"),
    ("check", "Verify write protection"),
    ("help", "Show device help"),
)
_VALUE_FLAGS = ("--kind", "-k", "--output", "-o")
_LIST_FLAGS = _VALUE_FLAGS
_CHECK_FLAGS = ("--allow-real-hardware", *_ACK_FLAGS, "--output", "-o", "--yes", "-y")
_SHOW_FLAGS = ("--allow-real-hardware", "--output", "-o")


class DeviceShellCommandHandler(BaseShellHandler):
    resource = "Device"

    @property
    def command_name(self) -> str:
        return "device"

    @property
    def aliases(self) -> list[str]:
        return ["devices", "dev"]

    def execute(self, action: str, args: list[str], ctx: object) -> bool:  # noqa: ARG002
        from trace_core.core.cli.error_handler import capture_cli_errors
        from trace_core.core.cli.output import parse_output_format

        act = (action or "").lower()
        if act in ("help", "", "?"):
            return self._help()
        if act not in _ACTIONS:
            return self.unknown_action(action, f"Action '{action}' not valid for device. Try `help`.")

        with capture_cli_errors(f"Device {act.title()} Failed", exit_on_error=False):
            return self._dispatch(act, args, parse_output_format)

    def _dispatch(self, act: str, args: list[str], parse_output) -> bool:  # type: ignore[no-untyped-def]
        from trace_core.devices.helpers import do_check, do_inspect, do_list
        from trace_core.devices.renderers import render_devices, render_gate, render_inspection

        output = parse_output(args)
        if act in ("list", "ls"):
            render_devices(do_list(None, _flag(args, "--kind", "-k") or "all"), output=output)
            return True

        node = _first_positional(args)
        if node is None:
            self.unknown_action(act, f"device {act} needs a device node. Try `device help`.")
            return False

        real = "--allow-real-hardware" in args
        if act == "inspect":
            render_inspection(do_inspect(None, node, allow_real_hardware=real), output=output)
            return True

        render_gate(
            do_check(
                None,
                node,
                allow_real_hardware=real,
                acknowledge_unverified_source=any(flag in args for flag in _ACK_FLAGS),
            ),
            output=output,
        )
        return True

    def _help(self) -> bool:
        from trace_core.core.ui.renderers import console

        for usage, _, desc in self.get_help_entries():
            console.print(f"[dim]{usage}[/dim] - {desc}")
        return True

    def get_completions(self, text: str, ctx: object) -> list[Any]:
        """`(value, description)` pairs, matching the case handler's contract.

        Values carry no trailing space: the shell completer appends it, so a value that
        arrives pre-spaced is offered twice under the same prefix. The shell asks every
        handler for every line, so a handler that does not recognise the leading word must
        answer nothing or it will offer its actions under another command.
        """
        _ = ctx
        parts = text.split()
        if not self.owns_text(text):
            return []
        if len(parts) < 2 or (len(parts) == 2 and not text.endswith(" ")):
            prefix = "" if text.endswith(" ") else parts[-1].lower()
            return [(action, description) for action, description in _ACTION_HELP if action.startswith(prefix)]
        if parts[1].lower() in ("check", "inspect") and not parts[-1].startswith("-"):
            return _complete_nodes(parts[-1])
        return [(flag, "") for flag in _flags_for(parts[1].lower()) if flag.startswith(parts[-1])]

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        return [
            ("device list", "", _LIST_DEVICES_HELP),
            ("device list --kind os", "", "List only real-hardware nodes"),
            ("device inspect <node>", "", "Capture a fingerprint and record it"),
            ("device check <node>", "", "Verify write protection; aborts when writable"),
            ("device check --ack-unverified <node>", "", "Proceed past UNKNOWN (records an override)"),
        ]


def _flags_for(action: str) -> tuple[str, ...]:
    if action in ("list", "ls"):
        return _LIST_FLAGS
    return _CHECK_FLAGS if action == "check" else _SHOW_FLAGS


def _complete_nodes(prefix: str) -> list[tuple[str, str]]:
    """Enumerated nodes plus their short ids. Completion never fails the line."""
    from trace_core.devices.helpers import do_list
    from trace_core.devices.service import short_id

    try:
        devices = do_list(None, "all")
    except Exception:
        return []
    lowered = prefix.lower()
    found: list[tuple[str, str]] = []
    for device in devices:
        meta = device.model_hint or ""
        if device.node.lower().startswith(lowered):
            found.append((device.node, meta))
        alias = short_id(device.node)
        if alias != device.node and alias.lower().startswith(lowered):
            found.append((alias, meta))
    return found


def _flag(args: list[str], *names: str) -> str | None:
    for index, token in enumerate(args):
        if token in names and index + 1 < len(args):
            return args[index + 1]
        for name in names:
            if token.startswith(f"{name}="):
                return token.split("=", 1)[1]
    return None


def _first_positional(args: list[str]) -> str | None:
    """The node, skipping values consumed by value-taking flags.

    Boolean flags must not swallow the token after them: treating `--allow-real-hardware`
    as value-taking made `device check --allow-real-hardware /dev/sda` report a missing node.
    """
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token.startswith("-"):
            if token in _VALUE_FLAGS or any(token.startswith(f"{name}=") for name in _VALUE_FLAGS):
                skip = "=" not in token
            continue
        return token
    return None
