"""Reusable Rich presentation components for CLI output."""

import json
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from trace_core.application.dto import CaseResponseDto
from trace_core.domain.models.case import CaseStatus

console = Console()


def format_status_badge(status: str | CaseStatus, is_deleted: bool = False) -> Text:
    """Format a consistent color-coded status badge."""
    if is_deleted:
        return Text("[ARCHIVED / DELETED]", style="bold red")

    status_str = status.value if hasattr(status, "value") else str(status)
    display_name = status_str.replace("_", " ")

    badge_styles = {
        "OPEN": "bold green",
        "UNDER_REVIEW": "bold yellow",
        "CLOSED": "bold red",
        "ARCHIVED": "dim white",
        "ACTIVE": "bold green",
        "VERIFIED": "bold green",
        "FAILED": "bold red",
        "QUARANTINED": "bold red on yellow",
    }
    style = badge_styles.get(status_str, "white")
    return Text(f"[{display_name}]", style=style)


def render_entity_panel(
    title: str,
    fields: list[tuple[str, Any]],
    sections: list[tuple[str, str]] | None = None,
    border_style: str = "bright_blue",
) -> None:
    """Generic reusable card/panel renderer with clean visual separation."""
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(style="bold cyan", width=18)
    grid.add_column(style="white")

    for label, val in fields:
        val_text = val if isinstance(val, Text) else Text(str(val))
        grid.add_row(f"{label}:", val_text)

    elements: list[Any] = [grid]

    if sections:
        for sec_title, sec_content in sections:
            if sec_content:
                elements.append(Rule(title=f"[bold white]{sec_title}[/bold white]", style="cyan"))
                elements.append(Text(sec_content, style="white"))

    panel = Panel(
        Group(*elements),
        title=f"[bold white] {title} [/bold white]",
        border_style=border_style,
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    )
    console.print(panel)


def render_table(
    title: str,
    columns: list[tuple[str, dict[str, Any]]],
    rows: list[list[Any]],
    empty_message: str = "No records found.",
    caption: str | None = None,
) -> None:
    """Generic reusable table renderer with rounded border and clean styling."""
    if not rows:
        console.print(f"[dim]{empty_message}[/dim]")
        return

    table = Table(
        title=title,
        title_style="bold cyan",
        border_style="bright_blue",
        header_style="bold white on blue",
        box=box.ROUNDED,
        expand=True,
        caption=caption,
        caption_style="dim italic",
    )

    for col_name, col_opts in columns:
        table.add_column(col_name, **col_opts)

    for row in rows:
        formatted_row = [cell if isinstance(cell, Text) else str(cell) for cell in row]
        table.add_row(*formatted_row)

    console.print(table)


def render_json(data: Any) -> None:
    """Print clean formatted JSON to console."""
    if hasattr(data, "model_dump_json"):
        console.print(data.model_dump_json(indent=2))
    elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
        console.print(json.dumps([item.model_dump(mode="json") for item in data], indent=2))
    else:
        console.print(json.dumps(data, indent=2, default=str))


def render_case_table(cases: list[CaseResponseDto]) -> None:
    """Render table of cases with clear column formatting and row separation."""
    columns: list[tuple[str, dict[str, Any]]] = [
        ("Case Number", {"style": "bold cyan", "no_wrap": True}),
        ("Title", {"style": "white"}),
        ("Lead Examiner", {"style": "magenta"}),
        ("Status", {"justify": "center"}),
        ("Tags", {"style": "dim cyan"}),
        ("Opened (UTC)", {"style": "dim"}),
    ]
    rows = [
        [
            c.number,
            c.title,
            c.lead_examiner,
            format_status_badge(c.status, c.is_deleted),
            "  ".join(f"#{t}" for t in c.tags) if c.tags else "-",
            c.opened_at.strftime("%Y-%m-%d %H:%M"),
        ]
        for c in cases
    ]
    render_table(
        title="Forensic Cases Registry",
        columns=columns,
        rows=rows,
        empty_message="No cases found matching criteria.",
        caption=f"Total Cases: {len(cases)}",
    )


def render_case_detail(case: CaseResponseDto) -> None:
    """Render detailed card for a case with structured visual sections."""
    # 1. Identity & Status Header Grid
    header_grid = Table.grid(expand=True, padding=(0, 2))
    header_grid.add_column(style="bold cyan", width=18)
    header_grid.add_column(style="bold white")
    header_grid.add_column(style="bold cyan", width=16)
    header_grid.add_column()

    record_state = (
        Text("[DELETED / ARCHIVED]", style="bold red") if case.is_deleted else Text("[ACTIVE]", style="bold green")
    )
    header_grid.add_row("Case Number:", case.number, "Status:", format_status_badge(case.status, case.is_deleted))
    header_grid.add_row("UUID:", str(case.id), "Record State:", record_state)

    # 2. Case Overview Grid
    overview_grid = Table.grid(expand=True, padding=(0, 2))
    overview_grid.add_column(style="bold cyan", width=18)
    overview_grid.add_column(style="white")

    overview_grid.add_row("Title:", case.title)
    overview_grid.add_row("Lead Examiner:", case.lead_examiner)
    if case.tags:
        tags_styled = "  ".join(f"[bold cyan]#{t}[/bold cyan]" for t in case.tags)
        overview_grid.add_row("Tags:", tags_styled)
    else:
        overview_grid.add_row("Tags:", "[dim]None[/dim]")

    # 3. Forensic Timeline Grid
    time_grid = Table.grid(expand=True, padding=(0, 2))
    time_grid.add_column(style="bold cyan", width=18)
    time_grid.add_column(style="white")

    time_grid.add_row("Opened (UTC):", case.opened_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    time_grid.add_row("Last Updated:", case.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    if case.closed_at:
        time_grid.add_row("Closed (UTC):", case.closed_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    else:
        time_grid.add_row("Closed (UTC):", "[dim]-- (Case is active / not closed)[/dim]")

    # Assemble structured visual components
    elements: list[Any] = [
        header_grid,
        Rule(title="[bold white]Investigation Overview[/bold white]", style="cyan"),
        overview_grid,
        Rule(title="[bold white]Forensic Timeline[/bold white]", style="cyan"),
        time_grid,
    ]

    if case.description:
        elements.append(Rule(title="[bold white]Description[/bold white]", style="cyan"))
        elements.append(Text(case.description, style="white"))

    if case.notes:
        elements.append(Rule(title="[bold white]Investigation Notes[/bold white]", style="cyan"))
        elements.append(Text(case.notes, style="white"))

    panel = Panel(
        Group(*elements),
        title=f"[bold white] Forensic Case Details: {case.number} [/bold white]",
        border_style="bright_blue",
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    )
    console.print(panel)
