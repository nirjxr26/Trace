"""Modular Interactive Forensic Console Shell (REPL) for Trace."""

import shlex
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, AutoSuggestFromHistory, Suggestion
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from rich.text import Text

from trace_core.cases.domain import Case
from trace_core.cases.service import CaseService
from trace_core.cases.shell_handler import CaseShellCommandHandler
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.registry import ShellCommandHandler, ShellCommandRegistry, ShellContext
from trace_core.core.settings import settings
from trace_core.core.ui.renderers import (
    console,
    create_key_value_grid,
    get_rule_char,
    render_error_card,
    render_key_value_grid,
)
from trace_core.core.ui.theme import THEME_TOKENS


class TraceAutoSuggest(AutoSuggest):
    """Context-aware inline ghost command suggestion generator."""

    def __init__(self, shell: "InteractiveShell") -> None:
        self.shell = shell
        self.history_suggest = AutoSuggestFromHistory()
        self.default_suggestions = [
            "case list",
            "case create",
            "case show",
            "case select",
            "case deselect",
            "case edit",
            "case close",
            "case delete",
            "list cases",
            "create case",
            "show case",
            "select case",
            "deselect case",
            "status",
            "clear",
            "help",
            "exit",
        ]

    def _suggest_from_history(self, buffer: Any, document: Any) -> Suggestion | None:
        if buffer is not None and hasattr(buffer, "history"):
            return self.history_suggest.get_suggestion(buffer, document)
        return None

    def _suggest_from_defaults(self, text: str) -> Suggestion | None:
        for cmd in self.default_suggestions:
            if cmd.startswith(text) and len(cmd) > len(text):
                return Suggestion(cmd[len(text) :])
        return None

    def _suggest_from_active_case(self, text: str) -> Suggestion | None:
        if text.startswith("case ") and self.shell.active_case:
            active_num = self.shell.active_case.number
            case_prefixes = ("case show ", "case select ", "case edit ", "case close ", "case delete ")
            if any(text == p for p in case_prefixes):
                return Suggestion(active_num)
        return None

    def get_suggestion(self, buffer: Any, document: Any) -> Suggestion | None:
        if (hist := self._suggest_from_history(buffer, document)) is not None:
            return hist

        text = document.text.lstrip()
        if not text:
            return None

        return self._suggest_from_defaults(text) or self._suggest_from_active_case(text)


class TraceShellCompleter(Completer):
    """Context-aware command autocompleter for the interactive shell."""

    def __init__(self, shell: "InteractiveShell") -> None:
        self.shell = shell

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        text = document.text_before_cursor.lstrip()
        word = document.get_word_before_cursor()

        if " " not in text:
            root_options = [
                ("case", "Forensic case management commands"),
                ("status", "Display system & database status"),
                ("clear", "Clear screen & re-render banner"),
                ("cls", "Clear screen & re-render banner"),
                ("help", "Display command manual"),
                ("?", "Display command manual"),
                ("exit", "Exit interactive console"),
                ("quit", "Exit interactive console"),
                ("list", "List cases (alias: list cases)"),
                ("create", "Create case (alias: create case)"),
                ("show", "Show case (alias: show case)"),
                ("select", "Set active case context"),
                ("use", "Set active case context"),
                ("deselect", "Clear active case context"),
                ("unuse", "Clear active case context"),
                ("edit", "Edit case metadata"),
                ("close", "Close case"),
                ("delete", "Delete / purge case"),
            ]
            for cmd, meta in root_options:
                if cmd.startswith(text.lower()):
                    yield Completion(cmd, start_position=-len(word), display_meta=meta)
            return

        ctx = self.shell.context
        for handler in self.shell.registry.all_handlers():
            for completion in handler.get_completions(text, ctx):
                if isinstance(completion, tuple):
                    val, meta = completion
                else:
                    val, meta = completion, ""
                yield Completion(val, start_position=-len(word), display_meta=meta)


class InteractiveShell:
    """Production-ready interactive forensic shell with pluggable command dispatch."""

    def __init__(self, service: CaseService | None = None) -> None:
        self.context = ShellContext(service=service)
        self.registry = ShellCommandRegistry()
        self.history = InMemoryHistory()
        self._session: PromptSession[str] | None = None
        self.completer = TraceShellCompleter(self)

        # Register standard feature command handlers
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register built-in feature handlers."""
        self.registry.register(CaseShellCommandHandler())

    def register_handler(self, handler: ShellCommandHandler) -> None:
        """Allow other AI agents and feature modules to plug in commands."""
        self.registry.register(handler)

    @property
    def service(self) -> CaseService | None:
        return self.context.service

    @service.setter
    def service(self, s: CaseService | None) -> None:
        self.context.service = s

    @property
    def active_case(self) -> Case | None:
        return self.context.active_case

    @active_case.setter
    def active_case(self, case: Case | None) -> None:
        self.context.active_case = case

    @property
    def session(self) -> PromptSession[str]:
        if self._session is None:
            self._session = PromptSession(
                history=self.history,
                auto_suggest=TraceAutoSuggest(self),
                completer=self.completer,
                complete_while_typing=True,
            )
        return self._session

    def _ensure_service(self) -> CaseService:
        if self.service is None:
            self.service = CaseService()
            self.context.service = self.service
        return self.service

    def print_banner(self) -> None:
        """Display simplified startup banner with breathing room and clean status rules."""
        logo = r"""
   _____ ____      _    ____ _____ 
  |_   _|  _ \    / \  / ___| ____|
    | | | |_) |  / _ \| |   |  _|  
    | | |  _ <  / ___ \ |___| |___ 
    |_| |_| \_\/_/   \_\____|_____|"""

        rule_char = get_rule_char()
        rule_line = "  " + (rule_char * 50)

        logo_text = Text(logo, style=THEME_TOKENS["accent"])
        sub_text = Text(
            f"  Forensic Data Acquisition & Case Engine · v{settings.version}\n",
            style=THEME_TOKENS["muted"],
        )

        try:
            self._ensure_service()
            db_label = Text.assemble(
                ("Online ", THEME_TOKENS["success"]),
                ("(Database)", THEME_TOKENS["muted"]),
            )
        except Exception:
            db_label = Text("Offline / Standalone", style=THEME_TOKENS["danger"])

        if self.active_case:
            active_label = Text.assemble(
                (self.active_case.number, THEME_TOKENS["accent"]),
                (" · ", THEME_TOKENS["muted"]),
                (self.active_case.title, THEME_TOKENS["value"]),
            )
        else:
            active_label = Text("None (use 'case select' or 'case create')", style=THEME_TOKENS["muted"])

        status_grid = create_key_value_grid(
            [
                ("Database", db_label),
                ("Active Case", active_label),
            ],
            width=18,
        )

        console.print("")
        console.print(logo_text)
        console.print(sub_text)
        console.print(Text(rule_line, style=THEME_TOKENS["border"]))
        console.print(status_grid)
        console.print(Text(rule_line, style=THEME_TOKENS["border"]))
        console.print(Text("  Type help for commands · exit to quit\n", style=THEME_TOKENS["muted"]))

    def get_prompt_text(self) -> str:
        """Dynamic prompt reflecting active case context."""
        if self.active_case:
            return f"trace [{self.active_case.number}]> "
        return "trace> "

    def run(self) -> None:
        """Run main REPL loop."""
        self.print_banner()

        while True:
            try:
                raw_input = self.session.prompt(self.get_prompt_text()).strip()
                if not raw_input:
                    continue

                if raw_input.lower() in ("exit", "quit"):
                    console.print("\n[dim italic]Exiting Trace console. Stay secure.[/dim italic]\n")
                    break

                self.execute_line(raw_input)
            except KeyboardInterrupt:
                console.print("\n[dim]Ctrl-C pressed. Type 'exit' to quit Trace.[/dim]\n")
            except EOFError:
                console.print("\n[dim italic]Exiting Trace console.[/dim italic]\n")
                break
            except Exception as e:
                with capture_cli_errors("Execution Error", exit_on_error=False):
                    raise e

    def _handle_control_command(self, cmd: str) -> bool:
        if cmd in ("help", "?"):
            self.show_help()
            return True
        if cmd in ("clear", "cls"):
            console.clear()
            self.print_banner()
            return True
        if cmd == "status":
            self.show_status()
            return True
        return False

    def _handle_alias(self, line: str) -> bool:
        alias_res = self.registry.resolve_alias(line)
        if not alias_res:
            return False
        cmd, action, args = alias_res
        handler = self.registry.get_handler(cmd)
        if handler:
            handler.execute(action, args, self.context)
            return True
        return False

    def _handle_registered_command(self, tokens: list[str]) -> bool:
        handler = self.registry.get_handler(tokens[0].lower())
        if not handler:
            return False
        action = tokens[1].lower() if len(tokens) > 1 else ""
        args = tokens[2:] if len(tokens) > 2 else []
        if not action:
            self.show_help()
            return True
        handler.execute(action, args, self.context)
        return True

    def execute_line(self, line: str) -> None:
        """Parse and route an interactive command string."""
        clean_line = line.strip()
        if not clean_line:
            return

        self._ensure_service()
        tokens = shlex.split(clean_line)
        if not tokens:
            return

        if self._handle_control_command(tokens[0].lower()):
            return
        if self._handle_alias(clean_line):
            return
        if self._handle_registered_command(tokens):
            return

        render_error_card(
            "Unknown Command",
            f"Command '{clean_line}' is not recognized. Type 'help' for command list.",
        )

    def show_help(self) -> None:
        """Render clean 3-tier grouped command listing."""
        console.print("")
        console.print(Text("  Trace Command Manual\n", style=THEME_TOKENS["title"]))

        # Registered feature commands
        for handler in self.registry.all_handlers():
            entries = handler.get_help_entries()
            if entries:
                console.print(Text(f"  {handler.command_name.capitalize()}", style=THEME_TOKENS["accent"]))
                for syntax, alias, desc in entries:
                    alias_str = f"({alias})" if alias else ""
                    console.print(
                        f"    [{THEME_TOKENS['value']}]{syntax:<36}[/{THEME_TOKENS['value']}] [{THEME_TOKENS['muted']}]{alias_str:<16}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['label']}]{desc}[/{THEME_TOKENS['label']}]"
                    )
                console.print("")

        # Global session commands
        console.print(Text("  Console", style=THEME_TOKENS["accent"]))
        console.print(
            f"    [{THEME_TOKENS['value']}]{'status':<36}[/{THEME_TOKENS['value']}] [{THEME_TOKENS['muted']}]{'':<16}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['label']}]Display system status and connection info[/{THEME_TOKENS['label']}]"
        )
        console.print(
            f"    [{THEME_TOKENS['value']}]{'clear / cls':<36}[/{THEME_TOKENS['value']}] [{THEME_TOKENS['muted']}]{'':<16}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['label']}]Clear console screen and re-render banner[/{THEME_TOKENS['label']}]"
        )
        console.print(
            f"    [{THEME_TOKENS['value']}]{'help / ?':<36}[/{THEME_TOKENS['value']}] [{THEME_TOKENS['muted']}]{'':<16}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['label']}]Show this command manual[/{THEME_TOKENS['label']}]"
        )
        console.print(
            f"    [{THEME_TOKENS['value']}]{'exit / quit':<36}[/{THEME_TOKENS['value']}] [{THEME_TOKENS['muted']}]{'':<16}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['label']}]Exit the interactive shell[/{THEME_TOKENS['label']}]"
        )
        console.print("")

    def show_status(self) -> None:
        """Display frameless system and connection diagnostics."""
        try:
            self._ensure_service()
            db_status = Text("Connected · Operational", style=THEME_TOKENS["success"])
        except Exception:
            db_status = Text("Disconnected", style=THEME_TOKENS["danger"])

        if self.active_case:
            active_str = Text.assemble(
                (self.active_case.number, THEME_TOKENS["accent"]),
                (" · ", THEME_TOKENS["muted"]),
                (self.active_case.title, THEME_TOKENS["value"]),
            )
        else:
            active_str = Text("None (No active case selected)", style=THEME_TOKENS["muted"])

        render_key_value_grid(
            "System Status",
            [
                ("Database", db_status),
                ("Storage", str(settings.storage_root)),
                ("Active Case", active_str),
                ("Version", settings.version),
                ("Compliance", "UTC · Parameterized SQL · ISO 17025 Ready"),
            ],
        )


def run_interactive_shell() -> None:
    """Entrypoint function to run the interactive shell."""
    shell = InteractiveShell()
    shell.run()
