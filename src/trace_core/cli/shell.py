"""Interactive forensic console for Trace."""

import shlex

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from trace_core.adapters.db.session import db_manager
from trace_core.application.cases import (
    CaseNotFoundError,
    CaseService,
    DuplicateCaseNumberError,
    InvalidCaseStateError,
)
from trace_core.application.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseResponseDto,
    CaseUpdateDto,
)
from trace_core.cli.error_handler import render_error_card
from trace_core.cli.ui.renderers import render_case_detail, render_case_table, render_json
from trace_core.domain.models.case import CaseStatus
from trace_core.settings import settings

console = Console()

SHELL_WORDS = [
    "case",
    "create",
    "list",
    "show",
    "edit",
    "close",
    "delete",
    "select",
    "deselect",
    "use",
    "status",
    "clear",
    "cls",
    "help",
    "exit",
    "quit",
    "--status",
    "--search",
    "--output",
    "--purge",
    "--title",
    "--examiner",
    "--desc",
    "--notes",
    "--tags",
    "OPEN",
    "UNDER_REVIEW",
    "CLOSED",
    "ARCHIVED",
    "ALL",
]


class InteractiveShell:
    """Manages state and command execution in the interactive Trace console."""

    def __init__(self) -> None:
        self.active_case: CaseResponseDto | None = None
        self.service: CaseService | None = None
        self.history = InMemoryHistory()
        self.completer = WordCompleter(SHELL_WORDS, ignore_case=True)
        self._session: PromptSession[str] | None = None

    @property
    def session(self) -> PromptSession[str]:
        if self._session is None:
            self._session = PromptSession(
                history=self.history,
                auto_suggest=AutoSuggestFromHistory(),
                completer=self.completer,
            )
        return self._session

    def _ensure_service(self) -> CaseService:
        if self.service is None:
            db_manager.init_schema()
            self.service = CaseService()
        return self.service

    def print_banner(self) -> None:
        """Display branded startup banner."""
        banner_text = (
            "[bold cyan]╔═══════════════════════════════════════════════════════════════════════════════╗[/bold cyan]\n"
            "[bold cyan]║[/bold cyan]           [bold white]T R A C E[/bold white] — [dim]Forensic Data Acquisition & Case Engine[/dim]            [bold cyan]║[/bold cyan]\n"
            "[bold cyan]╚═══════════════════════════════════════════════════════════════════════════════╝[/bold cyan]\n"
            f" • [dim]Version:[/dim] [white]{settings.version}[/white]  |  [dim]Engine:[/dim] [green]Active[/green]\n"
            " • [dim]Type[/dim] [bold yellow]help[/bold yellow] [dim]or[/dim] [bold yellow]?[/bold yellow] [dim]for command list, or[/dim] [bold yellow]exit[/bold yellow] [dim]to return to terminal.[/dim]"
        )
        console.print(banner_text)

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
                    console.print("[dim]Exiting Trace. Stay secure.[/dim]")
                    break

                self.execute_line(raw_input)
            except KeyboardInterrupt:
                console.print("\n[dim]Ctrl-C pressed. Type 'exit' to quit.[/dim]")
            except EOFError:
                console.print("\n[dim]Exiting Trace.[/dim]")
                break
            except Exception as e:
                render_error_card("Execution Error", str(e))

    def execute_line(self, line: str) -> None:
        """Parse and route an interactive command string."""
        tokens = shlex.split(line)
        if not tokens:
            return

        cmd = tokens[0].lower()
        args = tokens[1:]

        # Handle top-level utilities
        if cmd in ("clear", "cls"):
            console.clear()
            self.print_banner()
            return
        if cmd in ("help", "?"):
            self.show_help()
            return
        if cmd == "status":
            self.show_status()
            return

        # Canonicalize natural aliases
        # e.g., 'create case' -> 'case create', 'list cases' -> 'case list'
        if cmd in ("create", "list", "show", "edit", "close", "delete", "use") and args:
            sub = args[0].lower()
            if sub in ("case", "cases"):
                cmd, tokens = "case", [cmd] + args[1:]
                args = tokens

        if cmd == "case":
            self.handle_case_command(args)
        else:
            render_error_card(
                "Unknown Command",
                f"'{line}' is not a recognized command.",
                "Type 'help' to see all available commands.",
            )

    def show_help(self) -> None:
        """Display clean command table."""
        help_content = (
            "[bold white]Available Commands:[/bold white]\n\n"
            "  [bold cyan]case create[/bold cyan]            Launch interactive wizard to create a new case\n"
            "  [bold cyan]case list[/bold cyan]              List cases (optional: --status OPEN|CLOSED|ALL, --search QUERY)\n"
            "  [bold cyan]case show [ID|NUM][/bold cyan]       Display details of a case (defaults to active case)\n"
            "  [bold cyan]case edit [ID|NUM][/bold cyan]       Update title, examiner, description, or notes\n"
            "  [bold cyan]case close [ID|NUM][/bold cyan]      Close a case\n"
            "  [bold cyan]case delete [ID|NUM][/bold cyan]     Soft-delete a case (or --purge for permanent removal)\n"
            "  [bold cyan]case select <ID|NUM>[/bold cyan]   Set active case context\n"
            "  [bold cyan]case deselect[/bold cyan]          Clear active case context\n"
            "  [bold cyan]status[/bold cyan]                 Check database connection and session stats\n"
            "  [bold cyan]clear[/bold cyan]                  Clear the screen and re-display header\n"
            "  [bold cyan]exit[/bold cyan]                   Quit Trace shell\n\n"
            "[dim]Note: Natural aliases are supported (e.g. 'create case', 'list cases', 'show case').[/dim]"
        )
        console.print(
            Panel(
                help_content,
                title="[bold cyan]Trace Command Reference[/bold cyan]",
                border_style="cyan",
            )
        )

    def show_status(self) -> None:
        """Display system and database connection status."""
        try:
            self._ensure_service()
            db_status = "[bold green]Connected[/bold green]"
        except Exception as e:
            db_status = f"[bold red]Disconnected ({e})[/bold red]"

        active_case_str = self.active_case.number if self.active_case else "[dim]None[/dim]"
        status_text = (
            f"[bold cyan]Database:[/bold cyan]    {db_status}\n"
            f"[bold cyan]Storage:[/bold cyan]     {settings.storage_root}\n"
            f"[bold cyan]Active Case:[/bold cyan] {active_case_str}\n"
            f"[bold cyan]Version:[/bold cyan]     {settings.version}"
        )
        console.print(Panel(status_text, title="[bold white]System Status[/bold white]", border_style="green"))

    def handle_case_command(self, args: list[str]) -> None:
        """Route subcommands for case management."""
        if not args:
            self.show_help()
            return

        action = args[0].lower()
        sub_args = args[1:]

        service = self._ensure_service()

        if action == "create":
            self._interactive_create_case(service)
        elif action in ("list", "cases"):
            self._interactive_list_cases(service, sub_args)
        elif action == "show":
            self._interactive_show_case(service, sub_args)
        elif action == "edit":
            self._interactive_edit_case(service, sub_args)
        elif action == "close":
            self._interactive_close_case(service, sub_args)
        elif action == "delete":
            self._interactive_delete_case(service, sub_args)
        elif action in ("select", "use"):
            self._select_case(service, sub_args)
        elif action in ("deselect", "unuse"):
            self.active_case = None
            console.print("[dim]Active case context cleared.[/dim]")
        else:
            render_error_card(
                "Unknown Case Action",
                f"Action '{action}' is not valid. Type 'help' for command list.",
            )

    def _resolve_target_identifier(self, sub_args: list[str]) -> str | None:
        """Determine target case identifier from args or active case context."""
        for arg in sub_args:
            if not arg.startswith("-"):
                return arg
        if self.active_case:
            return self.active_case.number
        return None

    def _interactive_create_case(self, service: CaseService) -> None:
        """Guided wizard to create a new case."""
        console.print("[bold cyan]─── Create New Case Wizard ───[/bold cyan]")
        title = ""
        while not title:
            title = Prompt.ask("  [white]Case Title[/white]").strip()
            if not title:
                console.print("  [yellow]Case title cannot be empty.[/yellow]")

        examiner = ""
        while not examiner:
            examiner = Prompt.ask("  [white]Lead Examiner[/white]").strip()
            if not examiner:
                console.print("  [yellow]Lead examiner cannot be empty.[/yellow]")

        number = Prompt.ask("  [white]Case Number[/white] [dim](press Enter to auto-generate)[/dim]", default="")
        description = Prompt.ask("  [white]Description[/white] [dim](optional)[/dim]", default="")
        tags_raw = Prompt.ask("  [white]Tags (comma-separated)[/white] [dim](optional)[/dim]", default="")

        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        dto = CaseCreateDto(
            title=title,
            lead_examiner=examiner,
            number=number.strip() if number.strip() else None,
            description=description.strip() if description.strip() else None,
            tags=tags,
        )

        try:
            created = service.create_case(dto)
            self.active_case = created
            console.print(f"\n[bold green][OK] Case '{created.number}' created and set as active context![/bold green]")
            render_case_detail(created)
        except DuplicateCaseNumberError as e:
            render_error_card(
                "Duplicate Case Number",
                str(e),
                "Choose a unique case number or leave empty to auto-generate.",
            )

    def _interactive_list_cases(self, service: CaseService, sub_args: list[str]) -> None:
        """List cases with optional filters."""
        status_filter: CaseStatus | None = None
        search_query: str | None = None
        include_all = False
        output_format = "table"

        # Simple flag parser for interactive mode
        idx = 0
        while idx < len(sub_args):
            arg = sub_args[idx]
            if arg in ("--status", "-s") and idx + 1 < len(sub_args):
                val = sub_args[idx + 1].upper()
                if val != "ALL":
                    try:
                        status_filter = CaseStatus(val)
                    except ValueError:
                        pass
                idx += 2
            elif arg in ("--search", "-q") and idx + 1 < len(sub_args):
                search_query = sub_args[idx + 1]
                idx += 2
            elif arg in ("--output", "-o") and idx + 1 < len(sub_args):
                output_format = sub_args[idx + 1].lower()
                idx += 2
            elif arg in ("--all", "-a"):
                include_all = True
                idx += 1
            else:
                idx += 1

        filter_dto = CaseFilterDto(
            status=status_filter,
            search=search_query,
            include_deleted=include_all,
        )
        cases = service.list_cases(filter_dto)
        if output_format == "json":
            render_json(cases)
        else:
            render_case_table(cases)

    def _interactive_show_case(self, service: CaseService, sub_args: list[str]) -> None:
        """Display details of target case."""
        output_format = "table"
        idx = 0
        while idx < len(sub_args):
            if sub_args[idx] in ("--output", "-o") and idx + 1 < len(sub_args):
                output_format = sub_args[idx + 1].lower()
                idx += 2
            else:
                idx += 1

        ident = self._resolve_target_identifier(sub_args)
        if not ident:
            ident = Prompt.ask("Enter Case Number or UUID")

        try:
            case = service.get_case(ident)
            if output_format == "json":
                render_json(case)
            else:
                render_case_detail(case)
        except CaseNotFoundError as e:
            render_error_card("Case Not Found", str(e), "Use 'case list' to see all cases.")

    def _interactive_edit_case(self, service: CaseService, sub_args: list[str]) -> None:
        """Edit mutable fields of target case."""
        ident = self._resolve_target_identifier(sub_args)
        if not ident:
            ident = Prompt.ask("Enter Case Number or UUID to edit")

        try:
            case = service.get_case(ident)
            console.print(f"[bold cyan]Editing Case '{case.number}' (leave blank to keep current value):[/bold cyan]")
            new_title = Prompt.ask("  Title", default=case.title)
            new_examiner = Prompt.ask("  Lead Examiner", default=case.lead_examiner)
            new_desc = Prompt.ask("  Description", default=case.description or "")
            new_notes = Prompt.ask("  Investigation Notes", default=case.notes or "")
            new_tags = Prompt.ask(
                "  Tags (comma-separated)",
                default=", ".join(case.tags) if case.tags else "",
            )

            tag_list = [t.strip() for t in new_tags.split(",") if t.strip()] if new_tags else []

            dto = CaseUpdateDto(
                title=new_title,
                lead_examiner=new_examiner,
                description=new_desc if new_desc else None,
                notes=new_notes if new_notes else None,
                tags=tag_list,
            )
            updated = service.update_case(ident, dto)
            if self.active_case and self.active_case.id == updated.id:
                self.active_case = updated
            console.print(f"[bold green][OK] Case '{updated.number}' updated successfully![/bold green]")
            render_case_detail(updated)
        except CaseNotFoundError as e:
            render_error_card("Case Not Found", str(e))
        except InvalidCaseStateError as e:
            render_error_card("Invalid Operation", str(e))

    def _interactive_close_case(self, service: CaseService, sub_args: list[str]) -> None:
        """Close target case."""
        ident = self._resolve_target_identifier(sub_args)
        if not ident:
            ident = Prompt.ask("Enter Case Number or UUID to close")

        if not Confirm.ask(f"Are you sure you want to CLOSE case '{ident}'?"):
            console.print("[dim]Action cancelled.[/dim]")
            return

        reason = Prompt.ask("Reason for closing (optional)", default="")
        try:
            closed = service.close_case(ident, reason=reason)
            if self.active_case and self.active_case.id == closed.id:
                self.active_case = closed
            console.print(f"[bold green][OK] Case '{closed.number}' has been CLOSED.[/bold green]")
        except CaseNotFoundError as e:
            render_error_card("Case Not Found", str(e))
        except InvalidCaseStateError as e:
            render_error_card("Invalid State Transition", str(e))

    def _interactive_delete_case(self, service: CaseService, sub_args: list[str]) -> None:
        """Delete or archive target case."""
        purge = "--purge" in sub_args
        ident_args = [a for a in sub_args if a != "--purge"]
        ident = self._resolve_target_identifier(ident_args)
        if not ident:
            ident = Prompt.ask("Enter Case Number or UUID to delete")

        action_name = "PERMANENTLY PURGE" if purge else "archive (soft-delete)"
        if not Confirm.ask(f"Are you sure you want to {action_name} case '{ident}'?"):
            console.print("[dim]Action cancelled.[/dim]")
            return

        try:
            target = service.get_case(ident)
            service.delete_case(ident, purge=purge)
            if self.active_case and self.active_case.id == target.id:
                self.active_case = None
            console.print(f"[bold green][OK] Case '{ident}' has been {action_name}d.[/bold green]")
        except CaseNotFoundError as e:
            render_error_card("Case Not Found", str(e))
        except InvalidCaseStateError as e:
            render_error_card("Invalid Operation", str(e))

    def _select_case(self, service: CaseService, sub_args: list[str]) -> None:
        """Select a case to become the active context."""
        if not sub_args:
            ident = Prompt.ask("Enter Case Number or UUID to select")
        else:
            ident = sub_args[0]

        try:
            case = service.get_case(ident)
            self.active_case = case
            console.print(f"[bold green][OK] Active case set to '{case.number}' ({case.title}).[/bold green]")
        except CaseNotFoundError as e:
            render_error_card("Case Not Found", str(e))


def run_interactive_shell() -> None:
    """Entrypoint function to run the interactive shell."""
    shell = InteractiveShell()
    shell.run()
