"""Shell handler for audit commands."""

from typing import Any

from rich.markup import escape

from trace_core.audit.dto import (
    ACTION_CHOICES,
    AUDIT_DECRYPT_FLAGS,
    AUDIT_EXPORT_FLAGS,
    AUDIT_SHOW_FLAGS,
    AUDIT_VERIFY_FLAGS,
    AuditFilterDto,
)
from trace_core.audit.service import AuditService
from trace_core.core.cli.args import extract_flag_value, has_flag
from trace_core.core.cli.error_handler import capture_cli_errors
from trace_core.core.cli.output import OUTPUT_CHOICES, parse_output_format
from trace_core.core.cli.registry import ShellContext
from trace_core.core.cli.shell_base import BaseShellHandler
from trace_core.core.ui.renderers import console, render_error_card

AUDIT_ACTIONS = [
    ("show", "List audit events"),
    ("verify", "Verify chain integrity"),
    ("export", "Export JSONL bundle"),
    ("decrypt", "Open a sealed bundle"),
]

_AUDIT_VALUE_FLAGS = (
    "--case",
    "--action",
    "--actor",
    "--search",
    "-q",
    "--output",
    "-o",
    "--limit",
    "--offset",
    "--seq",
    "--anchor",
)


class AuditShellCommandHandler(BaseShellHandler):
    resource = "Audit"

    @property
    def command_name(self) -> str:
        return "audit"

    @property
    def aliases(self) -> list[str]:
        return []

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        return [
            ("audit show [--case NUM] [--action X]", "", "List audit events"),
            ("audit verify", "", "Verify chain integrity"),
            ("audit export --out FILE", "", "Export JSONL bundle"),
            ("audit decrypt --in FILE --out FILE", "", "Open a sealed bundle"),
        ]

    def get_completions(self, text: str, ctx: ShellContext) -> list[Any]:
        parts = text.split()
        if not text.startswith("audit"):
            return []
        # audit
        if len(parts) == 1 and text.endswith(" "):
            return AUDIT_ACTIONS
        if len(parts) == 2 and not text.endswith(" "):
            return [(a, d) for a, d in AUDIT_ACTIONS if a.startswith(parts[1].lower())]
        if len(parts) >= 2:
            act = parts[1].lower()
            if act == "show":
                return self._complete_show(parts, text, ctx)
            if act == "verify":
                return self._complete_verify(parts, text)
            if act == "export":
                return self._complete_export(parts, text)
            if act == "decrypt":
                return self._complete_decrypt(parts, text)
        return []

    def _complete_show(self, parts: list[str], text: str, ctx: ShellContext) -> list[Any]:
        if text.endswith(" "):
            flag = parts[-1]
            if flag in ("--action",):
                from trace_core.core.cli.completion import filter_completions

                return filter_completions(ACTION_CHOICES, "", limit=8)
            if flag in ("--output", "-o"):
                from trace_core.core.cli.completion import filter_completions

                return filter_completions(OUTPUT_CHOICES, "", limit=8)
            return self._complete_show_value(flag, ctx)
        from trace_core.core.cli.completion import filter_completions

        curr = parts[-1] if not text.endswith(" ") else ""
        return filter_completions(AUDIT_SHOW_FLAGS, curr)

    def _complete_show_value(self, flag: str, ctx: ShellContext) -> list[Any]:
        if flag == "--seq":
            from trace_core.core.cli.completion import complete_from_audit

            return complete_from_audit(self._svc(ctx))
        if flag == "--case":
            from trace_core.core.cli.completion import complete_from_cases

            try:
                case_svc = getattr(ctx, "service", None)
                if case_svc:
                    return complete_from_cases(case_svc)
            except Exception:
                pass
            return []
        if flag in ("--search", "-q"):
            from trace_core.core.cli.completion import complete_search_terms

            try:
                case_svc = getattr(ctx, "service", None)
                if case_svc:
                    return complete_search_terms(case_svc)
            except Exception:
                pass
            return []
        if flag == "--actor":
            from trace_core.core.cli.completion import complete_actors

            return complete_actors(self._svc(ctx))
        return []

    def _complete_verify(self, parts: list[str], text: str) -> list[Any]:
        if parts[-1] in ("--output", "-o") and text.endswith(" "):
            return OUTPUT_CHOICES
        curr = parts[-1] if not text.endswith(" ") else ""
        return [(f, d) for f, d in AUDIT_VERIFY_FLAGS if f.startswith(curr)]

    def _complete_export(self, parts: list[str], text: str) -> list[Any]:
        if parts[-1] in ("--format",) and text.endswith(" "):
            return [("jsonl", "JSONL bundle")]
        curr = parts[-1] if not text.endswith(" ") else ""
        return [(f, d) for f, d in AUDIT_EXPORT_FLAGS if f.startswith(curr)]

    def _complete_decrypt(self, parts: list[str], text: str) -> list[Any]:
        curr = parts[-1] if not text.endswith(" ") else ""
        return [(f, d) for f, d in AUDIT_DECRYPT_FLAGS if f.startswith(curr)]

    def _svc(self, ctx: ShellContext) -> AuditService:
        from trace_core.core.database.session import get_db

        return AuditService(get_db(ctx))

    def execute(self, action: str, args: list[str], ctx: ShellContext) -> bool:
        svc = self._svc(ctx)
        act = action.lower()
        if act == "show":
            self._show(svc, args, ctx)
            return True
        if act == "verify":
            self._verify(svc, args)
            return True
        if act == "export":
            self._export(svc, args)
            return True
        if act == "decrypt":
            self._decrypt(svc, args)
            return True
        return self.unknown_action(act)

    def _show(self, svc: AuditService, args: list[str], ctx: ShellContext | None = None) -> None:
        from trace_core.core.cli.args import extract_positional

        seq_raw = extract_flag_value(args, "--seq")
        if seq_raw is not None:
            self._show_seq(svc, args, seq_raw)
            return
        positional = extract_positional(args, *_AUDIT_VALUE_FLAGS)
        if not has_flag(args, "--case"):
            if positional:
                args = args + ["--case", positional[0]]
            elif ctx and ctx.active_case and not any(a.startswith("-") for a in args):
                args = args + ["--case", ctx.active_case.number]
                console.print(f"[dim]Scoped to active case {escape(ctx.active_case.number)}[/dim]")
        self._show_list(svc, args)

    def _show_seq(self, svc: AuditService, args: list[str], seq_raw: str) -> None:
        from trace_core.audit.helpers import show_seq_view

        try:
            seq = int(seq_raw)
        except ValueError:
            render_error_card("Invalid seq", f"--seq '{seq_raw}' is not a number.")
            return
        with capture_cli_errors("Audit Show", exit_on_error=False):
            show_seq_view(svc, seq, parse_output_format(args))

    def _show_list(self, svc: AuditService, args: list[str]) -> None:
        from trace_core.audit.domain import AuditAction
        from trace_core.core.cli.args import extract_int_flag
        from trace_core.core.domain import parse_enum_value

        case_number = extract_flag_value(args, "--case")
        action_raw = extract_flag_value(args, "--action")
        actor = extract_flag_value(args, "--actor")
        search = extract_flag_value(args, "--search", "-q")
        output = parse_output_format(args)
        limit = extract_int_flag(args, 50, "--limit")
        offset = extract_int_flag(args, 0, "--offset")
        act = None
        if action_raw:
            act = parse_enum_value(AuditAction, action_raw)
            if act is None:
                render_error_card("Unknown Action", f"Unknown action '{action_raw}'.")
                return
        f = AuditFilterDto(case_number=case_number, action=act, actor=actor, search=search, limit=limit, offset=offset)
        with capture_cli_errors("Audit Show", exit_on_error=False):
            from trace_core.audit.helpers import do_show_list

            do_show_list(svc, f, case_number, output)

    def _verify(self, svc: AuditService, args: list[str]) -> None:
        output = parse_output_format(args)
        anchor = extract_flag_value(args, "--anchor")
        with capture_cli_errors("Audit Verify", exit_on_error=False):
            from trace_core.audit.helpers import do_verify

            do_verify(svc, output, anchor)

    def _export(self, svc: AuditService, args: list[str]) -> None:
        out = extract_flag_value(args, "--out")
        if not out:
            render_error_card("Missing Output", "Pass --out FILE for the export bundle.")
            return
        with capture_cli_errors("Audit Export", exit_on_error=False):
            from trace_core.audit.helpers import check_export_dest, do_export, do_export_encrypted, prompt_passphrase
            from trace_core.core.ui.renderers import render_success

            check_export_dest(out, has_flag(args, "--force", "-f"))
            if has_flag(args, "--encrypt"):
                path = do_export_encrypted(svc, out, prompt_passphrase())
            else:
                path = do_export(svc, out)
            render_success("Audit bundle exported.")
            console.print(f"[dim]{path}[/dim]")

    def _decrypt(self, svc: AuditService, args: list[str]) -> None:
        _ = svc
        inp = extract_flag_value(args, "--in")
        out = extract_flag_value(args, "--out")
        if not inp or not out:
            render_error_card("Missing Input", "Pass --in FILE --out FILE to open a sealed bundle.")
            return
        with capture_cli_errors("Audit Decrypt", exit_on_error=False):
            from trace_core.audit.helpers import check_export_dest, do_decrypt, prompt_passphrase
            from trace_core.core.ui.renderers import render_success

            check_export_dest(out, has_flag(args, "--force", "-f"))
            path = do_decrypt(inp, out, prompt_passphrase())
            render_success("Bundle decrypted.")
            console.print(f"[dim]{path}[/dim]")
