import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from trace_core.core.ui.theme import THEME_TOKENS


def configure_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 where the runtime supports it."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


configure_utf8_streams()


def _supports_char(char: str) -> bool:
    """Check if the active stdout encoding can render a unicode character."""
    try:
        char.encode(getattr(sys.stdout, "encoding", None) or "utf-8")
        return True
    except Exception:
        return False


def get_rule_char() -> str:
    """Return box drawing horizontal bar if supported, else fallback to ASCII dash."""
    return "─" if _supports_char("─") else "-"


def get_error_icon() -> str:
    """Return UTF-8 cross mark if supported, else fallback to ASCII."""
    return "✗" if _supports_char("✗") else "[!]"


def get_arrow_char() -> str:
    """Return UTF-8 right arrow if supported, else fallback to ASCII."""
    return "→" if _supports_char("→") else "->"


def get_success_icon() -> str:
    """Return UTF-8 checkmark if supported, else fallback to ASCII."""
    return "✓" if _supports_char("✓") else "[OK]"


def get_warning_icon() -> str:
    """Return UTF-8 warning symbol if supported, else fallback to ASCII."""
    return "⚠" if _supports_char("⚠") else "[!]"


console = Console()

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

_STATUS_STYLES: dict[str, tuple[str, str]] = {}


def _status_styles() -> dict[str, tuple[str, str]]:
    """Lazily built status -> (text_style, border_color) map reusing theme tokens."""
    global _STATUS_STYLES
    if not _STATUS_STYLES:
        _STATUS_STYLES = {
            "OPEN": (THEME_TOKENS["status_open"], "#5FD18A"),
            "UNDER_REVIEW": (THEME_TOKENS["status_review"], "#D8B56A"),
            "CLOSED": (THEME_TOKENS["status_closed"], "#A88BD6"),
            "ARCHIVED": (THEME_TOKENS["status_archived"], "#D06A73"),
            "ACTIVE": (THEME_TOKENS["record_active"], "#5FD18A"),
            "VERIFIED": (THEME_TOKENS["status_open"], "#5FD18A"),
            "FAILED": (THEME_TOKENS["status_archived"], "#D06A73"),
            "QUARANTINED": (THEME_TOKENS["warning"], "#D8B56A"),
        }
    return _STATUS_STYLES


def _to_ist(dt: datetime) -> datetime:
    """Normalize any datetime to IST, assuming UTC when naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def format_india_datetime(dt: datetime | None, include_seconds: bool = True) -> str:
    """Format UTC datetime into Indian Standard Time (IST) format (DD-MM-YYYY hh:mm:ss AM/PM IST)."""
    if dt is None:
        return "-"
    ist_dt = _to_ist(dt)
    if include_seconds:
        return ist_dt.strftime("%d-%m-%Y %I:%M:%S %p IST")
    return ist_dt.strftime("%d-%m-%Y %I:%M %p IST")


def format_india_table_time(dt: datetime | None) -> str:
    """Format UTC datetime into concise Indian table format (DD-MM %I:%M %p)."""
    if dt is None:
        return "-"
    return _to_ist(dt).strftime("%d-%m %I:%M %p")


def get_status_style_and_label(status: Any, is_deleted: bool = False) -> tuple[str, str, str]:
    """Return (label, text_style, border_color) for any status representation."""
    if is_deleted:
        return "ARCHIVED", THEME_TOKENS["status_archived"], "#D06A73"

    status_str = status.value if hasattr(status, "value") else str(status)
    status_upper = status_str.upper()

    style, border = _status_styles().get(status_upper, (THEME_TOKENS["value"], THEME_TOKENS["border"]))
    label = "REVIEW" if status_upper == "UNDER_REVIEW" else status_upper.replace("_", " ")
    return label, style, border


def format_status_badge(status: Any, is_deleted: bool = False) -> Text:
    """Format a consistent color-coded status badge matching theme tokens."""
    if is_deleted:
        return Text("[ARCHIVED / DELETED]", style=THEME_TOKENS["status_archived"])
    status_str = status.value if hasattr(status, "value") else str(status)
    display_name = status_str.replace("_", " ")
    _, style, _ = get_status_style_and_label(status, is_deleted)
    return Text(f"[{display_name}]", style=style)


def render_status_badge_panel(status: Any, is_deleted: bool = False) -> Panel:
    """Reusable rounded status pill panel for dossier headers."""
    label, style, border = get_status_style_and_label(status, is_deleted)
    width = 10 if len(label) <= 6 else len(label) + 4
    return Panel(
        Text(f" {label} ", style=style, justify="center"),
        box=box.ROUNDED,
        border_style=border,
        padding=(0, 0),
        width=width,
        expand=False,
    )


def _print_empty_message(empty_message: str) -> None:
    """Print standardized empty-collection notice shared by table renderers."""
    console.print(f"\n[{THEME_TOKENS['muted']} italic]{empty_message}[/{THEME_TOKENS['muted']} italic]\n")


def _format_table_cells(row: list[Any]) -> list[Any]:
    """Coerce row cells to Text-or-string form shared by table renderers."""
    return [cell if isinstance(cell, Text) else str(cell) for cell in row]


def render_minimalist_table(
    title: str,
    columns: list[tuple[str, dict[str, Any]]],
    rows: list[list[Any]],
    empty_message: str = "No records found matching criteria.",
) -> None:
    """Render streamlined table with a clean single-rule header and record count."""
    if not rows:
        _print_empty_message(empty_message)
        return

    header_grid = Table.grid(expand=True)
    header_grid.add_column(justify="left")
    header_grid.add_column(justify="right")
    header_grid.add_row(
        Text(f"  {title}", style=THEME_TOKENS["title"]),
        Text(f"{len(rows)} records  ", style=THEME_TOKENS["muted"]),
    )

    rule_char = get_rule_char()
    header_box = box.Box(f"    \n    \n{rule_char * 4}\n    \n    \n    \n    \n    \n")

    table = Table(
        box=header_box,
        show_edge=False,
        pad_edge=False,
        padding=(0, 2),
        border_style=THEME_TOKENS["border"],
        expand=False,
    )
    for col_name, col_opts in columns:
        table.add_column(col_name, **col_opts)

    for row in rows:
        table.add_row(*_format_table_cells(row))

    console.print("")
    console.print(header_grid)
    console.print("")
    console.print(table)
    console.print("")


def create_key_value_grid(
    rows: list[tuple[str, Any]],
    width: int = 19,
    padding: tuple[int, int] = (0, 2),
) -> Table:
    """Construct a clean frameless key-value Table grid for layout assembly."""
    grid = Table.grid(padding=padding)
    grid.add_column(style=THEME_TOKENS["label"], width=width)
    grid.add_column(style=THEME_TOKENS["value"])
    for label, val in rows:
        if label == "":
            grid.add_row("", "")
        else:
            val_text = val if isinstance(val, Text) else Text(str(val))
            grid.add_row(f"  {label}", val_text)
    return grid


def render_dossier(
    header_prefix: str,
    identifier: str,
    title: str,
    subtitle: str | None,
    status_badge: Panel | Text | None,
    fields: list[tuple[str, Any]],
    sections: list[tuple[str, str | None]] | None = None,
) -> None:
    """Render streamlined forensic dossier with clean whitespace and focal point."""
    rule_char = get_rule_char()
    rule_line = "  " + (rule_char * 66)

    left_text = Text()
    left_text.append(f"  {header_prefix} ", style=THEME_TOKENS["title"])
    left_text.append(f"{identifier}  ", style=THEME_TOKENS["accent"])
    if status_badge:
        if isinstance(status_badge, Panel) and isinstance(status_badge.renderable, Text):
            raw = status_badge.renderable.plain.strip()
            style = status_badge.renderable.style or THEME_TOKENS["value"]
            left_text.append(f"[{raw}]", style=style)
        elif isinstance(status_badge, Text):
            left_text.append_text(status_badge)
        else:
            left_text.append(str(status_badge))
    left_text.append(f"\n  {title}\n\n", style=THEME_TOKENS["value"])
    if subtitle:
        left_text.append(f"  {subtitle}", style=THEME_TOKENS["muted"])

    console.print("")
    console.print(left_text)
    console.print("")
    console.print(Text(rule_line, style=THEME_TOKENS["border"]))

    details_grid = create_key_value_grid(fields, width=19)

    console.print(details_grid)
    console.print(Text(rule_line, style=THEME_TOKENS["border"]))

    if sections:
        for sec_title, sec_content in sections:
            console.print(Text(f"  {sec_title}", style=THEME_TOKENS["accent"]))
            console.print(
                Text(
                    f"    {sec_content or '--'}\n",
                    style=THEME_TOKENS["value"] if sec_content else THEME_TOKENS["muted"],
                )
            )


def render_key_value_grid(title: str | None, rows: list[tuple[str, Any]], width: int = 19) -> None:
    """Render a clean frameless key-value grid with optional title."""
    console.print("")
    if title:
        console.print(Text(f"  {title}\n", style=THEME_TOKENS["title"]))
    grid = create_key_value_grid(rows=rows, width=width)
    console.print(grid)
    console.print("")


def prompt_required(label: str, error_msg: str) -> str:
    """Prompt for a required non-empty string input."""
    from rich.prompt import Prompt

    val = ""
    while not val:
        val = Prompt.ask(f"  [{THEME_TOKENS['label']}]{label}[/{THEME_TOKENS['label']}]").strip()
        if not val:
            console.print(f"    [{THEME_TOKENS['danger']}][!] {error_msg}[/{THEME_TOKENS['danger']}]")
    return val


def prompt_optional(label: str, hint: str = "optional", default: str = "") -> str:
    """Prompt for an optional string input."""
    from rich.prompt import Prompt

    hint_str = f"({hint})" if hint else ""
    return Prompt.ask(
        f"  [{THEME_TOKENS['label']}]{label}[/{THEME_TOKENS['label']}][{THEME_TOKENS['muted']}]{hint_str}[/{THEME_TOKENS['muted']}]",
        default=default,
    )


def prompt_confirm(message: str, is_danger: bool = False, default: bool = False) -> bool:
    """Display themed confirmation prompt."""
    from rich.prompt import Confirm

    color = THEME_TOKENS["danger"] if is_danger else THEME_TOKENS["warning"]
    return Confirm.ask(f"  [{color}]{message}[/{color}]", default=default)


def render_wizard_header(title: str, note: str = "fields marked * are required") -> None:
    """Render standardized wizard initiation header."""
    console.print("")
    header = Text()
    header.append(f"  {title}", style=THEME_TOKENS["accent"])
    header.append(f" — {note}\n", style=THEME_TOKENS["muted"])
    console.print(header)


def render_entity_panel(
    title: str,
    fields: list[tuple[str, Any]],
    sections: list[tuple[str, str]] | None = None,
    border_style: str | None = None,
) -> None:
    """Generic reusable card/panel renderer with clean visual separation and breathing room."""
    border = border_style or THEME_TOKENS["border_card"]
    grid = Table.grid(expand=True, padding=(0, 3))
    grid.add_column(style=THEME_TOKENS["label"], width=20)
    grid.add_column(style=THEME_TOKENS["value"])

    for label, val in fields:
        val_text = val if isinstance(val, Text) else Text(str(val))
        grid.add_row(f"{label}:", val_text)

    elements: list[Any] = [grid]

    if sections:
        for sec_title, sec_content in sections:
            if sec_content:
                elements.append(Text(""))
                elements.append(
                    Rule(
                        title=f"[{THEME_TOKENS['section_title']}] {sec_title} [/{THEME_TOKENS['section_title']}]",
                        characters="-",
                        style=THEME_TOKENS["border_primary"],
                    )
                )
                elements.append(Text(sec_content, style=THEME_TOKENS["value"]))

    panel = Panel(
        Group(*elements),
        title=f"[{THEME_TOKENS['title_hero']}] {title} [/{THEME_TOKENS['title_hero']}]",
        border_style=border,
        box=box.ROUNDED,
        padding=(1, 3),
        expand=False,
    )
    console.print("")
    console.print(panel)
    console.print("")


def render_table(
    title: str,
    columns: list[tuple[str, dict[str, Any]]],
    rows: list[list[Any]],
    empty_message: str = "No records found.",
    caption: str | None = None,
) -> None:
    """Generic reusable table renderer with rounded border, spacious padding, and clean styling."""
    if not rows:
        _print_empty_message(empty_message)
        return

    table = Table(
        title=f"\n[{THEME_TOKENS['title_hero']}]{title}[/{THEME_TOKENS['title_hero']}]\n",
        title_style=THEME_TOKENS["title_hero"],
        border_style=THEME_TOKENS["border_card"],
        header_style=f"{THEME_TOKENS['section_title']} on #1E2833",
        box=box.ROUNDED,
        padding=(0, 2),
        expand=True,
        caption=f"[{THEME_TOKENS['muted']} italic]{caption}[/{THEME_TOKENS['muted']} italic]\n" if caption else None,
    )

    for col_name, col_opts in columns:
        table.add_column(col_name, **col_opts)

    for row in rows:
        table.add_row(*_format_table_cells(row))

    console.print("")
    console.print(table)
    console.print("")


def render_json(data: Any) -> None:
    """Print clean formatted JSON to console with breathing room."""
    console.print("")
    if hasattr(data, "model_dump_json"):
        console.print(data.model_dump_json(indent=2))
    elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
        console.print(json.dumps([item.model_dump(mode="json") for item in data], indent=2))
    else:
        console.print(json.dumps(data, indent=2, default=str))
    console.print("")


def render_error_card(title: str, message: str, remediation: str | None = None) -> None:
    """Render a clean, frameless error notice with immediate focal point and actionable tip."""
    icon = get_error_icon()
    arrow = get_arrow_char()

    console.print("")
    console.print(f"  [{THEME_TOKENS['danger']}]{icon} {title}[/{THEME_TOKENS['danger']}]")
    console.print("")
    console.print(f"    [{THEME_TOKENS['value']}]{message}[/{THEME_TOKENS['value']}]")
    if remediation:
        console.print(
            f"    [{THEME_TOKENS['muted']}]{arrow}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['warning']}]{remediation}[/{THEME_TOKENS['warning']}]"
        )
    console.print("")
