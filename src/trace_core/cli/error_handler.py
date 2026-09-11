"""User-facing actionable error handling and remediation cards."""

from rich.console import Console
from rich.panel import Panel

console = Console(stderr=True)


def render_error_card(title: str, message: str, remediation: str | None = None) -> None:
    """Render a clean, helpful error panel without leaking internal stack traces."""
    content = f"[bold red]{message}[/bold red]"
    if remediation:
        content += f"\n\n[bold yellow]Remediation:[/bold yellow]\n{remediation}"

    panel = Panel(
        content,
        title=f"[bold red][ERROR] {title}[/bold red]",
        border_style="red",
        expand=False,
    )
    console.print(panel)
