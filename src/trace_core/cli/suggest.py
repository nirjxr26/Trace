"""Prompt-toolkit suggest + completer for the interactive shell. Split from shell.py by job."""

from typing import TYPE_CHECKING, Any

from prompt_toolkit.auto_suggest import AutoSuggest, AutoSuggestFromHistory, Suggestion
from prompt_toolkit.completion import Completer, Completion

if TYPE_CHECKING:
    from trace_core.cli.shell import InteractiveShell

_CASE_SHOW = "case show"
_AUDIT_SHOW = "audit show"
_MANUAL_META = "Display command manual"


class TraceAutoSuggest(AutoSuggest):
    """Context-aware inline ghost command suggestion generator."""

    def __init__(self, shell: "InteractiveShell") -> None:
        self.shell = shell
        self.history_suggest = AutoSuggestFromHistory()
        self.default_suggestions = [
            "case list",
            "case create",
            _CASE_SHOW,
            "case select",
            "case deselect",
            "case edit",
            "case close",
            "case delete",
            "case restore",
            "device list",
            "device inspect",
            "device check",
            _AUDIT_SHOW,
            "audit verify",
            "list cases",
            "create case",
            "show case",
            "select case",
            "deselect case",
            "status",
            "clear",
            "help",
            "exit",
            "update check",
            "update history",
            "uninstall",
        ]

    def _suggest_from_history(self, buffer: Any, document: Any) -> Suggestion | None:
        if buffer is not None and hasattr(buffer, "history"):
            return self.history_suggest.get_suggestion(buffer, document)
        return None

    def _suggest_from_defaults(self, text: str) -> Suggestion | None:
        # rank: active-aware defaults first
        ranked = []
        if self.shell.active_case:
            ranked = [
                _CASE_SHOW,
                f"{_AUDIT_SHOW} --case {self.shell.active_case.number}",
                "case edit",
                "case list",
            ]
        lowered = text.lower()
        for cmd in ranked + self.default_suggestions:
            if cmd.startswith(lowered) and len(cmd) > len(text):
                return Suggestion(cmd[len(text) :])
        return None

    def _suggest_from_active_case(self, text: str) -> Suggestion | None:
        if text.startswith("case ") and self.shell.active_case:
            active_num = self.shell.active_case.number
            case_prefixes = (
                "case show ",
                "case select ",
                "case edit ",
                "case close ",
                "case delete ",
                "case restore ",
            )
            if any(text == p for p in case_prefixes):
                return Suggestion(active_num)
        if text.startswith(_AUDIT_SHOW) and self.shell.active_case and "--case" not in text:
            # ghost: audit show → audit show --case <active>
            if text.strip() == _AUDIT_SHOW:
                return Suggestion(f" --case {self.shell.active_case.number}")
        return None

    def get_suggestion(self, buffer: Any, document: Any) -> Suggestion | None:
        if (hist := self._suggest_from_history(buffer, document)) is not None:
            return hist

        text = document.text.lstrip()
        if not text:
            # ghost most logical next based on context
            return self._suggest_from_defaults(text)

        return self._suggest_from_defaults(text) or self._suggest_from_active_case(text)


class TraceShellCompleter(Completer):
    """Context-aware command autocompleter for the interactive shell."""

    def __init__(self, shell: "InteractiveShell") -> None:
        self.shell = shell

    _ROOT_EXTRAS: list[tuple[str, str]] = [
        ("status", "Display system & database status"),
        ("clear", "Clear screen & re-render banner"),
        ("cls", "Clear screen & re-render banner"),
        ("help", _MANUAL_META),
        ("?", _MANUAL_META),
        ("exit", "Exit interactive console"),
        ("quit", "Exit interactive console"),
        ("select", "Set active case context"),
        ("use", "Set active case context"),
        ("deselect", "Clear active case context"),
        ("unuse", "Clear active case context"),
        ("ls", "List cases (short)"),
        ("sh", "Show case (short)"),
        ("ed", "Edit case (short)"),
        ("recent", "Recent cases"),
        ("back", "Back to general"),
    ]

    @classmethod
    def _root_options(cls, shell: "InteractiveShell") -> list[tuple[str, str]]:
        """Registered command names and their aliases, plus the console-only verbs.

        Derived from the registry so a newly registered handler is completable without
        a second edit here; the list was previously a hand-copy that had already drifted.
        """
        options: list[tuple[str, str]] = []
        for handler in shell.registry.all_handlers():
            options.append((handler.command_name, f"{handler.command_name} commands"))
            for alias in handler.aliases:
                if " " not in alias:
                    options.append((alias, f"{alias} (alias)"))
        return [*options, *cls._ROOT_EXTRAS]

    def _root_completions(self, text: str, word: str) -> Any:
        from trace_core.core.cli.completion import filter_completions

        # One list always: hiding mutating verbs on empty input hid `case create`
        # exactly when an active case made it most likely. Delegated completions
        # below already stay context-aware.
        for cmd, meta in filter_completions(self._root_options(self.shell), text.lower(), limit=8):
            yield Completion(cmd, start_position=-len(word), display_meta=meta)

    def _delegated_completions(self, text: str, word: str) -> Any:
        ctx = self.shell.context
        for handler in self.shell.registry.all_handlers():
            for completion in handler.get_completions(text, ctx):
                if isinstance(completion, tuple):
                    val, meta = completion
                else:
                    val, meta = completion, ""
                # case/audit previews already contain number · status · title -> show as main display, not duplicate left
                if meta and "·" in meta:
                    yield Completion(val, start_position=-len(word), display=meta)
                elif not val and meta:
                    # header separator like "── CR ──"
                    yield Completion(val, start_position=-len(word), display=meta)
                else:
                    yield Completion(val, start_position=-len(word), display_meta=meta)

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        text = document.text_before_cursor.lstrip()
        word = document.get_word_before_cursor()

        if " " not in text:
            yield from self._root_completions(text, word)
            return

        yield from self._delegated_completions(text, word)
