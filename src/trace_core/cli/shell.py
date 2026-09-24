"""Modular Interactive Forensic Console Shell (REPL) for Trace."""

import shlex
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.text import Text

from trace_core.cases.domain import Case
from trace_core.cases.service import CaseService
from trace_core.cli.suggest import TraceAutoSuggest, TraceShellCompleter
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.registry import ShellCommandHandler, ShellCommandRegistry, ShellContext

__all__ = ["InteractiveShell", "TraceAutoSuggest", "TraceShellCompleter", "run_interactive_shell"]
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.settings import settings
from trace_core.core.ui.renderers import (
    breakpoint_width,
    clear_screen,
    console,
    create_key_value_grid,
    is_compact_view,
    kv_width,
    render_error_card,
    render_key_value_grid,
    rule_line,
    table_padding,
)
from trace_core.core.ui.theme import THEME_TOKENS


def _format_active_case(active_case: Any, empty_hint: str) -> Text:
    """Format active-case label shared by banner and status views."""
    if active_case:
        return Text.assemble(
            (active_case.number, THEME_TOKENS["accent"]),
            (" · ", THEME_TOKENS["muted"]),
            (active_case.title, THEME_TOKENS["value"]),
        )
    return Text(empty_hint, style=THEME_TOKENS["muted"])


HELP_GRID_SYNTAX_WIDTH = 36
HELP_GRID_ALIAS_WIDTH = 16


def _print_help_row(syntax: str, alias: str, desc: str) -> None:
    """Print one manual row shared by feature and console listings. Stacked on XS."""
    from trace_core.core.ui.renderers import breakpoint_width, fit_text

    bp, term_w = breakpoint_width()
    alias_str = f"({alias})" if alias else ""
    if bp == "XS":
        console.print(f"    [{THEME_TOKENS['value']}]{fit_text(syntax, max(20, term_w - 6))}[/{THEME_TOKENS['value']}]")
        if alias_str:
            console.print(f"    [{THEME_TOKENS['muted']}]{alias_str}[/{THEME_TOKENS['muted']}]")
        console.print(f"    [{THEME_TOKENS['label']}]{fit_text(desc, max(20, term_w - 6))}[/{THEME_TOKENS['label']}]")
        return
    console.print(
        f"    [{THEME_TOKENS['value']}]{syntax:<{HELP_GRID_SYNTAX_WIDTH}}[/{THEME_TOKENS['value']}] [{THEME_TOKENS['muted']}]{alias_str:<{HELP_GRID_ALIAS_WIDTH}}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['label']}]{desc}[/{THEME_TOKENS['label']}]"
    )


CONSOLE_HELP_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("status", "", "Display system status and connection info"),
    ("clear / cls", "", "Clear console screen and re-render banner"),
    ("help / ?", "", "Show this command manual"),
    ("exit / quit", "", "Exit the interactive shell"),
)


class InteractiveShell:
    """Production-ready interactive forensic shell with pluggable command dispatch."""

    def __init__(
        self,
        service: CaseService | None = None,
        session_manager: DatabaseSessionManager | None = None,
    ) -> None:
        self.context = ShellContext(service=service)
        self._session_manager = session_manager
        self.registry = ShellCommandRegistry()
        self.history = InMemoryHistory()
        self._session: PromptSession[str] | None = None
        self.completer = TraceShellCompleter(self)

        # Register standard feature command handlers
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register built-in feature handlers."""
        from trace_core.core.cli.catalog import default_handlers

        for handler in default_handlers():
            self.registry.register(handler)

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
            self.service = CaseService(self._session_manager)
            self.context.service = self.service
        return self.service

    def print_banner(self) -> None:
        """Display responsive startup banner adapted to terminal height and width."""
        bp, term_w = breakpoint_width()
        compact = is_compact_view(bp)

        rule_str = rule_line(term_w, max_len=50)

        try:
            self._ensure_service()
            db_label = Text.assemble(
                ("Online ", THEME_TOKENS["success"]),
                ("(Database)", THEME_TOKENS["muted"]),
            )
        except Exception:
            db_label = Text("Offline / Standalone", style=THEME_TOKENS["danger"])

        active_label = _format_active_case(self.active_case, "None (use 'case select' or 'case create')")

        status_grid = create_key_value_grid(
            [
                ("Database", db_label),
                ("Active Case", active_label),
            ],
            width=kv_width(bp, narrow=14, default=18),
            padding=table_padding(bp),
        )

        console.print("")
        if compact:
            # Sleek 2-line header for 80x24 / compact panes — saves 10+ rows for forensic work
            header_text = Text.assemble(
                ("  TRACE ", f"bold {THEME_TOKENS['accent']}"),
                (f"v{settings.version} ", THEME_TOKENS["muted"]),
                ("· Forensic Console\n", THEME_TOKENS["value"]),
            )
            console.print(header_text)
        else:
            logo = r"""
   _____ ____      _    ____ _____ 
  |_   _|  _ \    / \  / ___| ____|
    | | | |_) |  / _ \| |   |  _|  
    | | |  _ <  / ___ \ |___| |___ 
    |_| |_| \_\/_/   \_\____|_____|"""
            logo_text = Text(logo, style=THEME_TOKENS["accent"])
            sub_text = Text(
                f"  Forensic Data Imaging & Retrieval Tool · v{settings.version}\n",
                style=THEME_TOKENS["muted"],
            )
            console.print(logo_text)
            console.print(sub_text)

        console.print(Text(rule_str, style=THEME_TOKENS["border"]))
        console.print(status_grid)
        console.print(Text(rule_str, style=THEME_TOKENS["border"]))
        console.print(Text("  Type help for commands · exit to quit\n", style=THEME_TOKENS["muted"]))

    def get_prompt_text(self) -> str:
        """Dynamic prompt reflecting active case context."""
        if self.active_case:
            return f"trace [{self.active_case.number}]> "
        return "trace> "

    def run(self) -> None:
        """Run main REPL loop. Each command reads terminal size fresh during render."""
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
            clear_screen()
            self.print_banner()
            return True
        if cmd == "status":
            self.show_status()
            return True
        if cmd in ("recent", "recents"):
            self._show_recent()
            return True
        if cmd in ("back", "b"):
            self.context.active_case = None
            console.print("[dim]Back to general. Active case cleared.[/dim]")
            return True
        return False

    def _show_recent(self) -> None:
        from trace_core.cases.dto import CaseFilterDto
        from trace_core.cases.renderers import render_cases

        try:
            self._ensure_service()
            cases = self.service.list_cases(CaseFilterDto(limit=5, offset=0, recent=True))  # type: ignore[union-attr]
            render_cases(cases, "table", active_number=self.active_case.number if self.active_case else None)
        except Exception:
            console.print("[dim]No recent cases.[/dim]")

    def _handle_short_alias(self, line: str) -> bool:
        # ls/sh/ed -> case list/show/edit (comfort aliases)
        low = line.strip().lower()
        mapping = {
            "ls": ("case", "list"),
            "sh": ("case", "show"),
            "ed": ("case", "edit"),
        }
        for short, (cmd, act) in mapping.items():
            if low == short or low.startswith(short + " "):
                rest = line.strip()[len(short) :].strip()
                handler = self.registry.get_handler(cmd)
                if handler:
                    handler.execute(act, rest.split() if rest else [], self.context)
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
        import re as _re

        try:
            # Forgive leading `trace` inside REPL: `trace update check` == `update check`.
            stripped = _re.sub(r"(?i)^\s*trace\s+", "", clean_line).strip()
            if not stripped:
                return
            tokens = shlex.split(stripped)
            clean_line = stripped
        except ValueError:
            render_error_card("Invalid Command", f"Command '{clean_line}' has unbalanced quotes.")
            return
        if not tokens:
            return

        if self._handle_short_alias(clean_line):
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
                    _print_help_row(syntax, alias, desc)
                console.print("")

        # Global session commands
        console.print(Text("  Console", style=THEME_TOKENS["accent"]))
        for syntax, alias, desc in CONSOLE_HELP_ENTRIES:
            _print_help_row(syntax, alias, desc)
        console.print("")

    def show_status(self) -> None:
        """Display frameless system and connection diagnostics."""
        try:
            self._ensure_service()
            db_status = Text("Connected · Operational", style=THEME_TOKENS["success"])
        except Exception:
            db_status = Text("Disconnected", style=THEME_TOKENS["danger"])

        active_str = _format_active_case(self.active_case, "None (No active case selected)")

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


def run_interactive_shell(session_manager: DatabaseSessionManager | None = None) -> None:
    """Entrypoint function to run the interactive shell."""
    shell = InteractiveShell(session_manager=session_manager)
    shell.run()
