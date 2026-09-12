from typing import Any

from rich.prompt import Prompt

from trace_core.cases.domain import CaseStatus, is_archived_filter, parse_status_value
from trace_core.cases.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseUpdateDto,
    parse_tags,
)
from trace_core.cases.renderers import render_case, render_case_detail, render_cases
from trace_core.cases.service import CaseService
from trace_core.core.cli.args import extract_flag_value, has_flag
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.output import parse_output_format
from trace_core.core.cli.registry import ShellCommandHandler, ShellContext
from trace_core.core.ui.renderers import (
    console,
    get_success_icon,
    get_warning_icon,
    prompt_confirm,
    prompt_optional,
    prompt_required,
    render_error_card,
    render_wizard_header,
)
from trace_core.core.ui.theme import THEME_TOKENS

CASE_ACTIONS = [
    ("create", "Guided case wizard"),
    ("list", "List all cases"),
    ("show", "Display case dossier"),
    ("edit", "Update case metadata"),
    ("close", "Seal & close case"),
    ("delete", "Archive or purge case"),
    ("restore", "Restore archived case"),
    ("select", "Set active case context"),
    ("deselect", "Clear active case context"),
]

CASE_FLAGS = [
    ("--status", "Filter by case status"),
    ("--search", "Search title/examiner/notes"),
    ("--output", "Output format (table/json)"),
    ("--all", "Include deleted cases"),
    ("-s", "Filter by status"),
    ("-q", "Search query"),
    ("-o", "Output format"),
    ("-a", "Include deleted cases"),
]

STATUS_CHOICES = [
    ("OPEN", "Active case"),
    ("UNDER_REVIEW", "Case under review"),
    ("CLOSED", "Sealed closed case"),
    ("ARCHIVED", "Archived / soft-deleted"),
    ("ALL", "All statuses"),
]

FORMAT_CHOICES = [("table", "Formatted table view"), ("json", "Raw JSON export")]

_ACTION_CANCELLED = "\n[dim]Action cancelled.[/dim]\n"


def _parse_status(val: str | None) -> CaseStatus | None:
    return parse_status_value(val)


def _sync_active_case(ctx: ShellContext, case: Any) -> None:
    """Refresh shell active-case snapshot when the underlying case changed."""
    if ctx.active_case and ctx.active_case.id == case.id:
        ctx.active_case = case


def _clear_active_if_matches(ctx: ShellContext, case_id: Any) -> None:
    """Clear shell active-case context when its case was archived/purged."""
    if ctx.active_case and ctx.active_case.id == case_id:
        ctx.active_case = None


def _parse_list_options(sub_args: list[str]) -> tuple[CaseFilterDto, str]:
    raw_status = extract_flag_value(sub_args, "--status", "-s")
    status = _parse_status(raw_status)
    search = extract_flag_value(sub_args, "--search", "-q")
    output = parse_output_format(sub_args)
    include_deleted = has_flag(sub_args, "--all", "-a") or is_archived_filter(raw_status)
    return CaseFilterDto(status=status, search=search, include_deleted=include_deleted), output


class CaseShellCommandHandler(ShellCommandHandler):
    """Case feature handler for the interactive shell REPL."""

    @property
    def command_name(self) -> str:
        return "case"

    @property
    def aliases(self) -> list[str]:
        return [
            "list cases",
            "create case",
            "show case",
            "edit case",
            "close case",
            "delete case",
            "restore case",
            "use case",
            "unuse case",
            "select case",
            "deselect case",
        ]

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        return [
            ("case create", "create case", "Guided interactive wizard to create a new case"),
            ("case list [-s STATUS] [-q QUERY]", "list cases", "List cases (table or --output json)"),
            ("case show [<ID|NUM>]", "show case", "Display case dossier (uses active case if omitted)"),
            ("case select <ID|NUM>", "use case", "Set active case context"),
            ("case deselect", "unuse case", "Clear active case context"),
            ("case edit [<ID|NUM>]", "edit case", "Update case metadata (title, examiner, notes, tags)"),
            ("case close [<ID|NUM>]", "close case", "Close a case"),
            ("case delete [<ID|NUM>] [--purge]", "delete case", "Archive or permanently purge a case"),
            ("case restore [<ID|NUM>]", "restore case", "Restore an archived case"),
        ]

    def get_completions(self, text: str, ctx: ShellContext) -> list[Any]:
        parts = text.split()
        if text.startswith("case"):
            return self._complete_case_command(parts, text, ctx)
        return self._complete_aliases(parts, text, ctx)

    def _complete_case_command(self, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        if len(parts) == 1 and (text.endswith(" ") or parts[0] == "case"):
            return CASE_ACTIONS
        if len(parts) == 2 and not text.endswith(" "):
            prefix = parts[1].lower()
            return [(a, d) for a, d in CASE_ACTIONS if a.startswith(prefix)]
        if len(parts) >= 2:
            return self._complete_action_args(parts[1].lower(), parts, text, ctx)
        return []

    def _complete_action_args(self, act: str, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        if act == "list":
            return self._complete_list_args(parts, text)
        if act in ("show", "select", "use", "edit", "close", "delete", "restore"):
            return self._complete_case_targets(act, parts, text, ctx)
        return []

    def _complete_list_args(self, parts: list[str], text: str) -> list[Any]:
        if len(parts) >= 3 and parts[-1] in ("--status", "-s") and text.endswith(" "):
            return STATUS_CHOICES
        if len(parts) >= 3 and parts[-1] in ("--output", "-o") and text.endswith(" "):
            return FORMAT_CHOICES
        curr = parts[-1] if not text.endswith(" ") else ""
        return [(f, d) for f, d in CASE_FLAGS if f.startswith(curr)]

    def _complete_case_targets(self, act: str, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        curr = parts[-1] if not text.endswith(" ") else ""
        case_nums = self._get_candidate_case_numbers(ctx)
        if act == "delete":
            case_nums.append(("--purge", "Permanently erase record"))
        return [(cn, meta) for cn, meta in case_nums if cn.startswith(curr)]

    def _complete_aliases(self, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        first_word = parts[0].lower() if parts else ""
        if first_word == "list" and (len(parts) == 1 or text.endswith(" ")):
            return [("cases", "List all forensic cases")]
        if first_word == "create" and (len(parts) == 1 or text.endswith(" ")):
            return [("case", "Guided case creation wizard")]
        if first_word in ("show", "select", "use", "edit", "close", "delete", "restore"):
            curr = parts[-1] if not text.endswith(" ") else ""
            res = [("case", "Case action")] + self._get_candidate_case_numbers(ctx)
            if first_word == "delete":
                res.append(("--purge", "Permanently erase record"))
            return [(r, m) for r, m in res if r.startswith(curr)]
        return []

    def _get_candidate_case_numbers(self, ctx: ShellContext) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if ctx.active_case:
            candidates.append((ctx.active_case.number, f"Active: {ctx.active_case.title}"))
        if ctx.service:
            try:
                cases = ctx.service.list_cases(CaseFilterDto(include_deleted=True))
                for c in cases[:15]:
                    if not any(c.number == cand[0] for cand in candidates):
                        candidates.append((c.number, c.title[:30]))
            except Exception:
                pass
        return candidates

    def execute(self, action: str, args: list[str], ctx: ShellContext) -> bool:
        service: CaseService = ctx.service or CaseService()

        act = action.lower()
        if act == "create":
            self._interactive_create_case(service, ctx)
            return True
        if act in ("list", "cases"):
            self._interactive_list_cases(service, args)
            return True
        if act == "show":
            self._interactive_show_case(service, args, ctx)
            return True
        if act == "edit":
            self._interactive_edit_case(service, args, ctx)
            return True
        if act == "close":
            self._interactive_close_case(service, args, ctx)
            return True
        if act == "delete":
            self._interactive_delete_case(service, args, ctx)
            return True
        if act == "restore":
            self._interactive_restore_case(service, args, ctx)
            return True
        if act in ("select", "use"):
            self._select_case(service, args, ctx)
            return True
        if act in ("deselect", "unuse"):
            ctx.active_case = None
            console.print("[dim]Active case context cleared.[/dim]")
            return True

        render_error_card(
            "Unknown Case Action",
            f"Action '{act}' is not valid for case commands. Type 'help' for available actions.",
        )
        return False

    def _resolve_target_identifier(self, sub_args: list[str], ctx: ShellContext) -> str | None:
        for arg in sub_args:
            if not arg.startswith("-"):
                return arg
        if ctx.active_case:
            return ctx.active_case.number
        return None

    def _resolve_or_prompt_identifier(self, sub_args: list[str], ctx: ShellContext, action_label: str = "") -> str:
        ident = self._resolve_target_identifier(sub_args, ctx)
        if not ident:
            prompt_text = f"Enter Case Number or UUID {action_label}".strip()
            ident = Prompt.ask(f"\n[{THEME_TOKENS['section_title']}]{prompt_text}[/{THEME_TOKENS['section_title']}]")
        return ident.strip()

    def _interactive_create_case(self, service: CaseService, ctx: ShellContext) -> None:
        render_wizard_header("New Case", "fields marked * are required")

        title = prompt_required("* Title            ", "Case title cannot be empty.")
        examiner = prompt_required("* Lead Examiner    ", "Lead examiner cannot be empty.")

        number = prompt_optional("Case Number        ", hint="auto-generated if left blank")
        description = prompt_optional("Description        ", hint="optional")
        tags_raw = prompt_optional("Tags               ", hint="comma-separated, optional")

        tags = parse_tags(tags_raw) or []

        dto = CaseCreateDto(
            title=title,
            lead_examiner=examiner,
            number=number.strip() if number.strip() else None,
            description=description.strip() if description.strip() else None,
            tags=tags,
        )

        with capture_cli_errors(
            "Duplicate Case Number",
            exit_on_error=False,
            default_remediation="Choose a unique case number or leave empty to auto-generate.",
        ):
            created = service.create_case(dto)
            ctx.active_case = created
            check_icon = get_success_icon()
            console.print(
                f"\n  [{THEME_TOKENS['success']}]{check_icon} Case {created.number} created and set as active[/{THEME_TOKENS['success']}]"
            )
            render_case_detail(created)

    def _interactive_list_cases(self, service: CaseService, sub_args: list[str]) -> None:
        filter_dto, output_format = _parse_list_options(sub_args)
        cases = service.list_cases(filter_dto)
        render_cases(cases, output_format)

    def _interactive_show_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        output_format = parse_output_format(sub_args)
        ident = self._resolve_or_prompt_identifier(sub_args, ctx)

        with capture_cli_errors(
            "Show Case", exit_on_error=False, default_remediation="Use 'case list' to inspect available cases."
        ):
            case = service.get_case(ident)
            render_case(case, output_format)

    def _interactive_edit_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to edit")

        with capture_cli_errors("Update Case", exit_on_error=False):
            case = service.get_case(ident)
            console.print(
                f"\n[{THEME_TOKENS['section_title']}]Editing Case '{case.number}'[/{THEME_TOKENS['section_title']}] [{THEME_TOKENS['muted']}](press Enter to keep current value):[/{THEME_TOKENS['muted']}]\n"
            )
            new_title = Prompt.ask(f"  [{THEME_TOKENS['label']}]Title[/{THEME_TOKENS['label']}]", default=case.title)
            new_examiner = Prompt.ask(
                f"  [{THEME_TOKENS['label']}]Lead Examiner[/{THEME_TOKENS['label']}]", default=case.lead_examiner
            )
            new_desc = Prompt.ask(
                f"  [{THEME_TOKENS['label']}]Description[/{THEME_TOKENS['label']}]", default=case.description or ""
            )
            new_notes = Prompt.ask(
                f"  [{THEME_TOKENS['label']}]Investigation Notes[/{THEME_TOKENS['label']}]", default=case.notes or ""
            )
            new_tags = Prompt.ask(
                f"  [{THEME_TOKENS['label']}]Tags (comma-separated)[/{THEME_TOKENS['label']}]",
                default=", ".join(case.tags) if case.tags else "",
            )

            tag_list = parse_tags(new_tags) or []

            dto = CaseUpdateDto(
                title=new_title,
                lead_examiner=new_examiner,
                description=new_desc if new_desc else None,
                notes=new_notes if new_notes else None,
                tags=tag_list,
            )
            updated = service.update_case(ident, dto)
            _sync_active_case(ctx, updated)
            console.print(
                f"\n[{THEME_TOKENS['success']}][OK] Case '{updated.number}' updated successfully![/{THEME_TOKENS['success']}]"
            )
            render_case_detail(updated)

    def _interactive_close_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to close")

        console.print("")
        if not prompt_confirm(f"Seal & permanently close case '{ident}'?"):
            console.print(_ACTION_CANCELLED)
            return

        reason = prompt_optional("Reason             ", hint="optional")
        closed_by = prompt_optional("Closed By          ", hint="examiner name, optional")
        with capture_cli_errors("Close Case", exit_on_error=False):
            closed = service.close_case(ident, reason=reason, closed_by=closed_by)
            _sync_active_case(ctx, closed)
            check_icon = get_success_icon()
            console.print(
                f"\n  [{THEME_TOKENS['success']}]{check_icon} Case {closed.number} permanently closed.[/{THEME_TOKENS['success']}]\n"
            )
            render_case_detail(closed)

    def _interactive_delete_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        purge = "--purge" in sub_args
        ident_args = [a for a in sub_args if a != "--purge"]
        ident = self._resolve_or_prompt_identifier(ident_args, ctx, "to delete")

        console.print("")
        if purge:
            warn_icon = get_warning_icon()
            prompt_msg = f"{warn_icon} Permanently purge case '{ident}'? This cannot be undone."
            action_label = "purged"
        else:
            prompt_msg = f"Archive case '{ident}'?"
            action_label = "archived"

        if not prompt_confirm(prompt_msg, is_danger=purge):
            console.print(_ACTION_CANCELLED)
            return

        with capture_cli_errors("Delete Case", exit_on_error=False):
            target = service.get_case(ident)
            service.delete_case(ident, purge=purge)
            _clear_active_if_matches(ctx, target.id)
            check_icon = get_success_icon()
            console.print(
                f"\n  [{THEME_TOKENS['success']}]{check_icon} Case {ident} {action_label}.[/{THEME_TOKENS['success']}]\n"
            )

    def _interactive_restore_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to restore")

        console.print("")
        if not prompt_confirm(f"Restore archived case '{ident}'?"):
            console.print(_ACTION_CANCELLED)
            return

        with capture_cli_errors("Restore Case", exit_on_error=False):
            restored = service.restore_case(ident)
            _sync_active_case(ctx, restored)
            check_icon = get_success_icon()
            console.print(
                f"\n  [{THEME_TOKENS['success']}]{check_icon} Case {ident} restored.[/{THEME_TOKENS['success']}]\n"
            )

    def _select_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to select")

        with capture_cli_errors("Select Case", exit_on_error=False):
            case = service.get_case(ident)
            ctx.active_case = case
            console.print(
                f"\n[{THEME_TOKENS['success']}][OK] Active case set to '{case.number}' ({case.title}).[/{THEME_TOKENS['success']}]\n"
            )
