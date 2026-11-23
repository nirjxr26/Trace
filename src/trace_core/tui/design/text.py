from rich.text import Text

from trace_core.core.ui.renderers import sanitize_terminal
from trace_core.tui.design.tokens import LABEL_MD, SECTION_STYLE

NO_SELECTION_CASE = "Select a case first."
NO_SELECTION_DEVICE = "Select a device first."


def section_head(body: Text, title: str) -> None:
    body.append(f"\n{title}\n", style=SECTION_STYLE)


def kv_row(body: Text, label: str, value: str, width: int = LABEL_MD) -> None:
    body.append(f"{label:<{width}}", style="dim")
    body.append(f"{sanitize_terminal(value) if value else chr(0x2014)}\n")


def unknown_command_text(command: str) -> str:
    return f"Command '{command}' is not available on this tab."
