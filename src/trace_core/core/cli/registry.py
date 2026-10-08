"""Modular command registry and execution contracts for the interactive shell."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ShellContext:
    """State and execution context provided to interactive shell handlers."""

    active_case: Any | None = None
    service: Any | None = None


class ShellCommandHandler(ABC):
    """Abstract interface for feature-specific interactive shell command handlers."""

    @property
    @abstractmethod
    def command_name(self) -> str:
        """Primary noun/verb for the command group (e.g. 'case', 'audit', 'devices')."""
        raise NotImplementedError

    @property
    def aliases(self) -> list[str]:
        """Natural language aliases or reverse verb-noun syntax (e.g. ['list cases', 'create case'])."""
        return []

    @abstractmethod
    def execute(self, action: str, args: list[str], ctx: ShellContext) -> bool:
        """
        Execute command action.
        Returns True if the command was recognized and handled, False otherwise.
        """
        raise NotImplementedError

    def get_help_entries(self) -> list[tuple[str, str, str]]:
        """Return list of (command_syntax, alias, description) for interactive help."""
        return []

    def get_completions(self, text: str, ctx: ShellContext) -> list[Any]:
        """Provide auto-completion suggestions for prompt-toolkit.

        A `(value, description)` pair per suggestion; the completer renders a bare value
        with an empty description and treats a non-empty description on an empty value as
        a non-insertable group heading.
        """
        return []


class ShellCommandRegistry:
    """Central registry dispatching commands to modular feature handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, ShellCommandHandler] = {}
        self._alias_map: dict[str, tuple[str, str]] = {}

    def register(self, handler: ShellCommandHandler) -> None:
        """Register a feature command handler."""
        self._handlers[handler.command_name.lower()] = handler
        for alias in handler.aliases:
            parts = alias.split(maxsplit=1)
            action = parts[0]
            self._alias_map[alias.lower()] = (handler.command_name.lower(), action)

    def get_handler(self, name: str) -> ShellCommandHandler | None:
        """Lookup handler by command name."""
        return self._handlers.get(name.lower())

    def resolve_alias(self, line: str) -> tuple[str, str, list[str]] | None:
        """Resolve a natural language alias into (command_name, action, remaining_args)."""
        line_clean = line.strip().lower()
        for alias, (cmd, action) in self._alias_map.items():
            if line_clean == alias or line_clean.startswith(alias + " "):
                remainder = line[len(alias) :].strip()
                args = remainder.split() if remainder else []
                return cmd, action, args
        return None

    def all_handlers(self) -> list[ShellCommandHandler]:
        """Return all registered handlers."""
        return list(self._handlers.values())

    def known_words(self) -> list[str]:
        """Every word the shell accepts: command names plus single-word aliases.

        The shell asks this instead of keeping its own list, so registering a handler
        makes its command reachable from the unknown-command suggestion and the root
        completer without a second edit elsewhere.
        """
        words = list(self._handlers)
        for alias in self._alias_map:
            if " " not in alias:
                words.append(alias)
        return words
