"""REPL handler for device commands. Same cores as the Typer app; shell flow only."""

from typing import Any

from trace_core.core.cli.shell_base import BaseShellHandler

_ACTIONS = frozenset({"list", "ls", "inspect", "check", "link", "unlink", "history", "export", "help"})
_ACK_FLAGS = ("--acknowledge-unverified-source", "--ack-unverified")
_PHYSICAL_FLAGS = ("--physical", "--allow-real-hardware", "--real")
_LIST_DEVICES_HELP = "List devices this adapter can see"
_ACTION_HELP = (
    ("list", _LIST_DEVICES_HELP),
    ("ls", _LIST_DEVICES_HELP),
    ("inspect", "Capture the device identity and record it"),
    ("check", "Verify write protection"),
    ("history", "Show prior observations of one device"),
    ("link", "File a device under a case"),
    ("unlink", "Remove a device from a case"),
    ("export", "Write stored observations to a JSONL file"),
    ("help", "Show device help"),
)
# Every value-taking flag across every action. `_first_positional` reads this to avoid
# swallowing the token after one, so it is the union rather than any single action's set.
_VALUE_FLAGS = (
    "--kind",
    "-k",
    "--output",
    "-o",
    "--reason",
    "--case",
    "--limit",
    "-n",
    "--out",
    "--serial",
)
_LIST_FLAGS = ("--kind", "-k", "--output", "-o")
_CHECK_FLAGS = ("--physical", *_ACK_FLAGS, "--output", "-o", "--yes", "-y")
_SHOW_FLAGS = ("--physical", "--output", "-o")
_HISTORY_FLAGS = ("--output", "-o", "--limit", "-n")
_LINK_FLAGS = ("--case", "--label")
_EXPORT_FLAGS = ("--out", "--case", "--serial")


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
        from trace_core.core.ui.renderers import render_success, sanitize_terminal
        from trace_core.devices.helpers import do_check, do_history, do_inspect, do_link, do_list, do_unlink
        from trace_core.devices.renderers import render_devices, render_gate, render_history, render_inspection

        output = parse_output(args)
        if act in ("list", "ls"):
            render_devices(do_list(None, _flag(args, "--kind", "-k") or "all", audit_recognition=True), output=output)
            return True

        if act == "export":
            return self._export(args)

        if act == "history":
            serial = _first_positional(args)
            if serial is None:
                self.unknown_action(act, "device history needs a device serial. Try `device help`.")
                return False
            render_history(do_history(None, serial, _positive_int(_flag(args, "--limit", "-n"), 10)), output=output)
            return True

        node = _first_positional(args)
        if node is None:
            self.unknown_action(act, f"device {act} needs a device node. Try `device help`.")
            return False

        if act in ("link", "unlink"):
            case_number = _flag(args, "--case")
            if not case_number:
                self.unknown_action(act, f"device {act} needs --case CASE_NUMBER.")
                return False
            if act == "link":
                link = do_link(None, node, case_number, label=_flag(args, "--label") or None)
                render_success(f"Filed {sanitize_terminal(link.node)} under {link.case_number}.")
            else:
                do_unlink(None, node, case_number)
                render_success(f"Removed {sanitize_terminal(node)} from {case_number}.")
            return True

        real = any(flag in args for flag in _PHYSICAL_FLAGS)
        if act == "inspect":
            from trace_core.devices.helpers import do_node_case_numbers

            render_inspection(
                do_inspect(None, node, allow_real_hardware=real),
                output=output,
                case_numbers=do_node_case_numbers(None, node),
            )
            return True

        acknowledged = any(flag in args for flag in _ACK_FLAGS)
        if acknowledged and "--yes" not in args and "-y" not in args:
            from trace_core.devices.commands import confirm_override

            if not confirm_override():
                return True

        render_gate(
            do_check(
                None,
                node,
                allow_real_hardware=real,
                acknowledge_unverified_source=acknowledged,
                override_reason=_flag(args, "--reason") or "",
            ),
            output=output,
        )
        return True

    def _export(self, args: list[str]) -> bool:
        from trace_core.core.database.session import db_manager
        from trace_core.core.ui.renderers import render_success
        from trace_core.devices.exporter import export_observations

        out = _flag(args, "--out")
        if not out:
            self.unknown_action("export", "device export needs --out <file>. Try `device help`.")
            return False
        with db_manager.session() as session:
            path = export_observations(
                session,
                out,
                case_number=_flag(args, "--case") or None,
                serial=_flag(args, "--serial") or None,
            )
        render_success(f"Wrote device observations to {path}.")
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
        if parts[1].lower() == "history" and not parts[-1].startswith("-"):
            return _complete_serials(parts[-1])
        return [(flag, "") for flag in _flags_for(parts[1].lower()) if flag.startswith(parts[-1])]

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        return [
            ("device list", "", _LIST_DEVICES_HELP),
            ("device list --kind os", "", "List only real-hardware nodes"),
            ("device inspect <node>", "", "Capture the device identity and record it"),
            ("device inspect <node> --case <case>", "", "File the observation under a case"),
            ("device check <node>", "", "Verify write protection; aborts when writable"),
            ("device check --ack-unverified <node>", "", "Proceed past UNKNOWN (records an override)"),
            ("device history <serial>", "", "Prior observations of one device, newest first"),
            ("device export --out <file>", "", "Write observations to a JSONL file"),
            ("device export --out <f> --case <c>", "", "Only that case's devices"),
            ("device link <node> --case <case>", "", "File a device under a case"),
            ("device unlink <node> --case <case>", "", "Remove a device from a case"),
        ]


def _flags_for(action: str) -> tuple[str, ...]:
    if action in ("list", "ls"):
        return _LIST_FLAGS
    if action == "check":
        return _CHECK_FLAGS
    if action == "history":
        return _HISTORY_FLAGS
    if action == "export":
        return _EXPORT_FLAGS
    if action in ("link", "unlink"):
        return _LINK_FLAGS
    return _SHOW_FLAGS


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


def _positive_int(raw: str | None, default: int) -> int:
    """A limit must be a positive whole number. Bad input falls back rather than raising."""
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _complete_serials(prefix: str) -> list[tuple[str, str]]:
    """Serials of devices that have been observed, so `history` takes a real argument."""
    from sqlalchemy import select

    from trace_core.core.database.session import db_manager
    from trace_core.devices.models import DeviceFingerprintModel

    try:
        with db_manager.session() as session:
            serials = session.scalars(
                select(DeviceFingerprintModel.serial).distinct().order_by(DeviceFingerprintModel.serial)
            ).all()
    except Exception:
        return []
    lowered = prefix.lower()
    return [(serial, "observed device") for serial in serials if serial.lower().startswith(lowered)]


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
