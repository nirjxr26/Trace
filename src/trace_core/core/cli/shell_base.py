"""Shared shell handler helpers: unknown-action cards and typed confirms."""

from trace_core.core.cli.registry import ShellCommandHandler


class BaseShellHandler(ShellCommandHandler):
    """Feature shell base. Owns shared error cards; subclasses own dispatch."""

    resource: str = "Command"

    def owns_text(self, text: str) -> bool:
        """Whether `text` names this handler's command.

        The shell asks every handler for every line, so a handler that answers a line it
        does not own offers its own actions and flags under someone else's command.
        """
        words = str(text).lstrip().split()
        return bool(words) and words[0].lower() in {self.command_name.lower(), *(a.lower() for a in self.aliases)}

    def unknown_action(self, action: str, detail: str | None = None) -> bool:
        """Render `Unknown <Resource> Action` card. Callers pass their exact message to preserve UX."""
        from trace_core.core.ui.renderers import render_error_card

        msg = detail if detail is not None else f"Action '{action}' not valid. Try `help`."
        render_error_card(f"Unknown {self.resource} Action", msg)
        return False
