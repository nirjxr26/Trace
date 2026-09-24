from typing import Any

from rich.markup import escape
from rich.prompt import Prompt

from trace_core.cases.domain import is_archived_filter, parse_status_value
from trace_core.cases.dto import (
    CaseCreateDto,
    CaseFilterDto,
    CaseUpdateDto,
    parse_tags,
)
from trace_core.cases.renderers import render_case, render_case_detail, render_cases
from trace_core.cases.service import CaseService
from trace_core.core.cli.args import extract_flag_value, extract_int_flag, has_flag
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.output import parse_output_format
from trace_core.core.cli.registry import ShellContext
from trace_core.core.cli.shell_base import BaseShellHandler
from trace_core.core.ui.renderers import (
    console,
    get_warning_icon,
    prompt_confirm,
    prompt_optional,
    prompt_required,
    render_success,
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
    ("--limit", "Max rows"),
    ("--offset", "Skip rows"),
    ("--recent", "5 most recently updated"),
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

_CASE_VALUE_FLAGS = (
    "--status",
    "-s",
    "--search",
    "-q",
    "--output",
    "-o",
    "--limit",
    "--offset",
    "--reason",
    "-r",
    "--title",
    "-t",
    "--examiner",
    "-e",
    "--desc",
    "--notes",
    "--tags",
)

_ACTION_CANCELLED = "\n[dim]Action cancelled.[/dim]\n"


def _sync_active_case(ctx: ShellContext, case: Any) -> None:
    """Refresh shell active-case snapshot when the underlying case changed."""
    if ctx.active_case and ctx.active_case.id == case.id:
        ctx.active_case = case


def _clear_active_if_matches(ctx: ShellContext, case_id: Any) -> None:
    """Clear shell active-case context when its case was archived/purged."""
    if ctx.active_case and ctx.active_case.id == case_id:
        ctx.active_case = None


def _parse_list_options(sub_args: list[str]) -> tuple[CaseFilterDto, str]:
    from trace_core.cases.domain import STATUS_FILTER_KEYWORDS
    from trace_core.core.errors import ValidationError

    raw_status = extract_flag_value(sub_args, "--status", "-s")
    status = parse_status_value(raw_status)
    if raw_status and raw_status.upper() not in STATUS_FILTER_KEYWORDS and status is None:
        raise ValidationError(f"Status '{raw_status}' is not valid. Valid: OPEN, UNDER_REVIEW, CLOSED, ARCHIVED, ALL.")
    search = extract_flag_value(sub_args, "--search", "-q")
    output = parse_output_format(sub_args)
    include_deleted = has_flag(sub_args, "--all", "-a") or is_archived_filter(raw_status)
    deleted_only = is_archived_filter(raw_status) and not has_flag(sub_args, "--all", "-a")
    filter_dto = CaseFilterDto(
        status=status,
        search=search,
        include_deleted=include_deleted,
        deleted_only=deleted_only,
        limit=extract_int_flag(sub_args, 50, "--limit"),
        offset=extract_int_flag(sub_args, 0, "--offset"),
    )
    if has_flag(sub_args, "--recent"):
        filter_dto = filter_dto.with_recent()
    return filter_dto, output


class CaseShellCommandHandler(BaseShellHandler):
    resource = "Case"
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
            ("case close [<ID|NUM>]", "close case", "Seal & close (type number to confirm)"),
            ("case delete [<ID|NUM>] [--purge]", "delete case", "Archive (y/N) or purge (type number)"),
            ("case restore [<ID|NUM>]", "restore case", "Restore an archived case"),
            ("ls / sh / ed", "", "Short aliases for list / show / edit"),
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
            return self._complete_list_args(parts, text, ctx)
        if act in ("show", "select", "use", "edit", "close", "delete", "restore"):
            return self._complete_case_targets(act, parts, text, ctx)
        return []

    def _complete_flag_value(self, flag: str, ctx: ShellContext) -> list[Any] | None:
        """Completions for a value-taking list flag. None when the flag takes no values."""
        from trace_core.core.cli.completion import complete_search_terms, complete_tags, filter_completions

        if flag in ("--status", "-s"):
            return filter_completions(STATUS_CHOICES, "", limit=8)
        if flag in ("--output", "-o"):
            return filter_completions(FORMAT_CHOICES, "", limit=8)
        try:
            if not ctx.service:
                return []
            if flag in ("--search", "-q"):
                return complete_search_terms(ctx.service)
            if flag == "--tags":
                return complete_tags(ctx.service)
        except Exception:
            return []
        return None

    def _complete_list_args(self, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        from trace_core.core.cli.completion import filter_completions

        if len(parts) >= 3 and text.endswith(" "):
            values = self._complete_flag_value(parts[-1], ctx)
            if values is not None:
                return values
        curr = parts[-1] if not text.endswith(" ") else ""
        return filter_completions(CASE_FLAGS, curr)

    def _complete_case_targets(self, act: str, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        from trace_core.core.cli.completion import filter_completions

        curr = parts[-1] if not text.endswith(" ") else ""
        case_nums = self._get_candidate_case_numbers(ctx)
        if act == "delete":
            case_nums.append(("--purge", "Permanently erase record"))
        # keep forensic hashes out — only case numbers + preview, show up to 15 grouped
        return filter_completions(case_nums, curr, limit=15)

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

    def _prepend_active(self, ranked: list[tuple[str, str]], ctx: ShellContext) -> list[tuple[str, str]]:
        """Ensure the active case heads the list with an Active preview."""
        if ctx.active_case and ranked and ranked[0][0] != ctx.active_case.number:
            return [(ctx.active_case.number, f"Active: {ctx.active_case.title}")] + ranked
        return ranked

    def _fallback_candidates(self, ctx: ShellContext) -> list[tuple[str, str]]:
        """Direct service read when the cached ranker is unavailable."""
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

    def _get_candidate_case_numbers(self, ctx: ShellContext) -> list[tuple[str, str]]:
        # reusable, cached, ranked: active → recent/open, preview "2026-CR-0029 · CLOSED · Title"
        from trace_core.core.cli.completion import (  # local to keep shell independent
            complete_from_cases,
        )

        if ctx.service:
            try:
                active = ctx.active_case.number if ctx.active_case else None
                ranked = complete_from_cases(ctx.service, active_number=active, limit=20)
                # complete_from_cases already ranked + cached + preview; just return
                return self._prepend_active(ranked, ctx)[:20]
            except Exception:
                pass
        return self._fallback_candidates(ctx)

    def execute(self, action: str, args: list[str], ctx: ShellContext) -> bool:
        service: CaseService = ctx.service or CaseService()

        act = action.lower()
        if act == "create":
            self._interactive_create_case(service, ctx)
            return True
        if act in ("list", "cases"):
            self._interactive_list_cases(service, args, ctx)
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

        return self.unknown_action(
            act, f"Action '{act}' is not valid for case commands. Type 'help' for available actions."
        )

    def _resolve_target_identifier(self, sub_args: list[str], ctx: ShellContext) -> str | None:
        from trace_core.core.cli.args import extract_positional

        positional = extract_positional(sub_args, *_CASE_VALUE_FLAGS)
        if positional:
            return positional[0]
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
        # tag autosuggest from existing taxonomy
        try:
            existing = sorted({t for c in service.list_cases() for t in c.tags})[:10]
            if existing:
                console.print(f"  [dim]Existing tags: {escape(', '.join(existing))}[/dim]")
        except Exception:
            pass
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
            render_success(f"Case {created.number} created and set as active")
            render_case_detail(created)

    def _interactive_list_cases(
        self, service: CaseService, sub_args: list[str], ctx: ShellContext | None = None
    ) -> None:
        with capture_cli_errors("Query Failed", exit_on_error=False):
            filter_dto, output_format = _parse_list_options(sub_args)
            cases = service.list_cases(filter_dto)
            active = ctx.active_case.number if ctx and ctx.active_case else None  # type: ignore[union-attr]
            render_cases(cases, output_format, active_number=active)

    def _interactive_show_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        output_format = parse_output_format(sub_args)
        ident = self._resolve_or_prompt_identifier(sub_args, ctx)

        with capture_cli_errors(
            "Show Case", exit_on_error=False, default_remediation="Use 'case list' to inspect available cases."
        ):
            from trace_core.audit.helpers import fetch_case_with_history

            case, events = fetch_case_with_history(service, ident)
            render_case(case, output_format, events)

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
            reason = prompt_optional("Reason             ", hint="why, optional")

            # Clear rules: required fields keep current on blank; optionals clear to "".
            # (The service treats None and "" as the same empty and stores None,
            # so the preview normalizes identically to stay in agreement with it.)
            new_title = new_title.strip() or case.title
            new_examiner = new_examiner.strip() or case.lead_examiner
            cleared_desc = new_desc.strip()
            cleared_notes = new_notes.strip()
            tag_list = parse_tags(new_tags) or []

            # 5W1H diff preview before confirm
            from trace_core.audit.renderers import format_change_value
            from trace_core.cases.domain import changed_fields, tracked_snapshot

            before = tracked_snapshot(case)
            # Same empty-normalization as the service (None == ""), so legacy ""
            # rows don't preview a change the service will skip.
            before = {
                **before,
                "description": before["description"] or None,
                "notes": before["notes"] or None,
            }
            after_vals = {
                "title": new_title,
                "lead_examiner": new_examiner,
                "description": cleared_desc or None,
                "notes": cleared_notes or None,
                "tags": tag_list,
            }
            changed = changed_fields(before, after_vals)
            if not changed:
                console.print("\n[dim]No changes detected.[/dim]\n")
                return
            console.print(f"\n[{THEME_TOKENS['accent']}]Changes:[/{THEME_TOKENS['accent']}]")
            for k in changed:
                console.print(f'  {k}: "{format_change_value(before[k])}" → "{format_change_value(after_vals[k])}"')
            if not prompt_confirm("Apply these changes?"):
                console.print(_ACTION_CANCELLED)
                return

            dto = CaseUpdateDto(
                title=new_title,
                lead_examiner=new_examiner,
                description=cleared_desc,
                notes=cleared_notes,
                tags=tag_list,
            )
            updated = service.update_case(ident, dto, reason=reason)
            _sync_active_case(ctx, updated)
            render_success(f"Case '{updated.number}' updated successfully!")
            render_case_detail(updated)

    def _confirm_typed(self, ident: str, action: str) -> bool:
        typed = Prompt.ask(f"  Type case number '{ident}' to confirm {action}")
        if typed.strip() != ident.strip():
            console.print(f"\n[dim]{action.capitalize()} cancelled (mismatch).[/dim]\n")
            return False
        return True

    def _interactive_close_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to close")

        console.print("")
        if not self._confirm_typed(ident, "close"):
            return

        reason = prompt_required("Reason             ", "A closure reason is required to seal a case.")
        closed_by = prompt_optional("Closed By          ", hint="examiner name, optional")
        with capture_cli_errors("Close Case", exit_on_error=False):
            from trace_core.audit.anchor import describe_anchor

            closed = service.close_case(ident, reason=reason, closed_by=closed_by)
            _sync_active_case(ctx, closed)
            render_success(f"Case {closed.number} permanently closed.")
            line = describe_anchor(service.session_manager, closed.number)
            if line is not None:
                console.print(f"[dim]{escape(line)}[/dim]")
            render_case_detail(closed)

    def _interactive_delete_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        purge = has_flag(sub_args, "--purge")
        ident_args = [a for a in sub_args if a != "--purge"]
        ident = self._resolve_or_prompt_identifier(ident_args, ctx, "to delete")

        console.print("")
        if purge:
            warn_icon = get_warning_icon()
            console.print(f"  [{THEME_TOKENS['danger']}]{warn_icon} Purge is irreversible![/{THEME_TOKENS['danger']}]")
            if not self._confirm_typed(ident, "purge"):
                return
            action_label = "purged"
        else:
            prompt_msg = f"Archive case '{ident}'?"
            action_label = "archived"
            if not prompt_confirm(prompt_msg, is_danger=False):
                console.print(_ACTION_CANCELLED)
                return

        with capture_cli_errors("Delete Case", exit_on_error=False):
            target = service.get_case(ident)
            service.delete_case(ident, purge=purge)
            _clear_active_if_matches(ctx, target.id)
            render_success(f"Case {ident} {action_label}.")

    def _interactive_restore_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to restore")

        console.print("")
        if not prompt_confirm(f"Restore archived case '{ident}'?"):
            console.print(_ACTION_CANCELLED)
            return

        with capture_cli_errors("Restore Case", exit_on_error=False):
            restored = service.restore_case(ident)
            _sync_active_case(ctx, restored)
            render_success(f"Case {ident} restored.")

    def _select_case(self, service: CaseService, sub_args: list[str], ctx: ShellContext) -> None:
        ident = self._resolve_or_prompt_identifier(sub_args, ctx, "to select")

        with capture_cli_errors("Select Case", exit_on_error=False):
            case = service.get_case(ident)
            ctx.active_case = case
            render_success(f"Active case set to '{case.number}' ({case.title}).")
