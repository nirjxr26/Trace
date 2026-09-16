import json
import sys
import textwrap
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


def _enable_windows_vt() -> None:
    """Enable VT processing on Windows cmd so ANSI passes through instead of ?[ leaks."""
    import os

    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


_enable_windows_vt()

console = Console()


def clear_screen() -> None:
    """Clear terminal without leaking ANSI on legacy cmd. Single source for cls/clear."""
    import os

    try:
        if os.name == "nt" and not os.environ.get("WT_SESSION"):
            os.system("cls")
            return
        console.clear()
    except Exception:
        try:
            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass


IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# 4 Responsive Breakpoints:
# XS: Compact / Extra-Small (< 80 cols) — split panes, narrow windows, vertical stacking
# MD: Standard / Medium (80 to 119 cols) — classic 80-column standard terminal
# LG: Wide / Large (120 to 159 cols) — multi-column expanded view
# XL: Ultra-Wide (160+ cols) — full workstation dashboard
BREAKPOINTS: list[tuple[str, int, int]] = [
    ("XS", 0, 79),
    ("MD", 80, 119),
    ("LG", 120, 159),
    ("XL", 160, 9999),
]

MAX_TABLE_WIDTH = 116

COLUMN_CASE_NUMBER = "Case #"


def get_breakpoint(width: int | None = None) -> str:
    """Return responsive breakpoint name: XS (<80), MD (80-119), LG (120-159), XL (160+)."""
    w = width if width is not None else console.width
    try:
        w = int(w)
    except Exception:
        w = 80
    for name, lo, hi in BREAKPOINTS:
        if lo <= w <= hi:
            return name
    return "MD"


def breakpoint_width(width: int | None = None) -> tuple[str, int]:
    """Return (breakpoint_name, actual_width)."""
    bp = get_breakpoint(width)
    w = width if width is not None else console.width
    try:
        w = int(w)
    except Exception:
        w = 80
    return bp, w


def is_compact_height(height: int | None = None) -> bool:
    """Return True if terminal height is <= 24 rows (classic VT100 / short pane)."""
    h = height if height is not None else console.height
    try:
        return int(h) <= 24
    except Exception:
        return True


def fit_text(text: str, max_width: int) -> str:
    """Truncate text to max_width with ellipsis. Single source for previews/titles."""
    if len(text) <= max_width or max_width < 4:
        return text[:max_width] if len(text) > max_width else text
    try:
        return textwrap.shorten(text, width=max_width, placeholder="…")
    except Exception:
        return text[: max_width - 1] + "…"


def rule_line(term_w: int, max_len: int = 66) -> str:
    """Single source for horizontal rule length across banner/dossier/timeline."""
    return "  " + (get_rule_char() * max(20, min(max_len, term_w - 4)))


def table_padding(bp: str) -> tuple[int, int]:
    """Single source for table padding: tight except XL workstation."""
    return (0, 2) if bp == "XL" else (0, 1)


def kv_width(bp: str, narrow: int = 14, default: int = 19) -> int:
    """Single source for key-value label width: narrow on XS."""
    return narrow if bp == "XS" else default


def is_compact_view(bp: str | None = None) -> bool:
    """Single source for compact decision: short height or XS width."""
    return is_compact_height() or (bp or get_breakpoint()) == "XS"


def title_max_width(bp: str, term_w: int) -> int | None:
    """Single source for title truncation budget per breakpoint. None means full."""
    if bp == "XS":
        return max(14, term_w - 32)
    if bp == "MD":
        return max(20, min(36, term_w - 56))
    if bp == "LG":
        return max(28, min(48, term_w - 62))
    return None


def page_rows(rows: list[list[Any]], limit: int = 10) -> tuple[list[list[Any]], int]:
    """Truncate rows on short terminals. Returns (visible, hidden_count)."""
    if is_compact_height() and len(rows) > limit:
        return rows[:limit], len(rows) - limit
    return rows, 0


def split_hash(value: str, term_w: int) -> str:
    """Split 64-char hashes on narrow terminals. Single source for dossiers."""
    text = value.strip() if isinstance(value, str) else str(value)
    if term_w < 70 and len(text) == 64 and " " not in text:
        return f"{text[:32]}\n    {text[32:]}"
    return value


def render_output(output: str, json_data: Any, table_fn: Any) -> None:
    """JSON-vs-table dispatch single source. table_fn is a zero-arg closure."""
    if output.lower() == "json":
        render_json(json_data)
    else:
        table_fn()


_STATUS_STYLES: dict[str, tuple[str, str]] = {}


def _status_styles() -> dict[str, tuple[str, str]]:
    """Lazily built status -> (text_style, border_color) map reusing theme tokens."""
    global _STATUS_STYLES
    if not _STATUS_STYLES:
        _STATUS_STYLES = {
            "OPEN": (THEME_TOKENS["status_open"], THEME_TOKENS["border_open"]),
            "UNDER_REVIEW": (THEME_TOKENS["status_review"], THEME_TOKENS["border_review"]),
            "CLOSED": (THEME_TOKENS["status_closed"], THEME_TOKENS["border_closed"]),
            "ARCHIVED": (THEME_TOKENS["status_archived"], THEME_TOKENS["border_archived"]),
            "ACTIVE": (THEME_TOKENS["record_active"], THEME_TOKENS["border_open"]),
            "VERIFIED": (THEME_TOKENS["status_open"], THEME_TOKENS["border_open"]),
            "FAILED": (THEME_TOKENS["status_archived"], THEME_TOKENS["border_archived"]),
            "QUARANTINED": (THEME_TOKENS["warning"], THEME_TOKENS["border_review"]),
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


def format_ledger_time(ts: Any) -> str:
    """Compact table time for ledger rows, falling back to full datetime."""
    try:
        return format_india_table_time(ts)  # type: ignore[arg-type]
    except Exception:
        return format_india_datetime(ts)  # type: ignore[arg-type]


def format_utc_zulu(ts: Any) -> str:
    """UTC Zulu string for court-facing timestamps."""
    try:
        return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ts)


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
    """Format a consistent color-coded status badge. Single label/style source."""
    label, style, _ = get_status_style_and_label(status, is_deleted)
    return Text(f"[{label}]", style=style)


def render_status_badge_panel(status: Any, is_deleted: bool = False) -> Panel:
    """Reusable rounded status pill panel for dossier headers."""
    badge = format_status_badge(status, is_deleted)
    _, _, border = get_status_style_and_label(status, is_deleted)
    label = badge.plain.strip().strip("[]")
    width = 10 if len(label) <= 6 else len(label) + 4
    return Panel(
        Text(f" {label} ", style=badge.style, justify="center"),
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
    total: int | None = None,
    show_count: bool = True,
    tight: bool = False,
) -> None:
    """Render streamlined table with a clean single-rule header and record count.

    tight=True hugs content instead of stretching to terminal width.
    """
    if not rows:
        _print_empty_message(empty_message)
        return

    bp, term_w = breakpoint_width()
    visible, hidden = page_rows(rows)
    shown = total if total is not None else len(rows)
    header_grid = Table.grid(expand=True)
    header_grid.add_column(justify="left")
    header_grid.add_column(justify="right")
    count_label = ""
    if show_count:
        count_label = f"{shown} records  " if bp != "XS" else f"{shown}  "
    header_grid.add_row(
        Text(f"  {title}", style=THEME_TOKENS["title"]),
        Text(count_label, style=THEME_TOKENS["muted"]),
    )

    rule_char = get_rule_char()
    header_box = box.Box(f"    \n    \n{rule_char * 4}\n    \n    \n    \n    \n    \n")

    table_kwargs: dict[str, Any] = {
        "box": header_box,
        "show_edge": False,
        "pad_edge": False,
        "padding": table_padding(bp),
        "border_style": THEME_TOKENS["border"],
        "expand": False,
    }
    if not tight:
        table_kwargs["width"] = max(20, min(term_w - 2, MAX_TABLE_WIDTH))
    table = Table(**table_kwargs)  # type: ignore[arg-type]
    for col_name, col_opts in columns:
        table.add_column(col_name, **col_opts)

    for row in visible:
        table.add_row(*_format_table_cells(row))

    console.print("")
    console.print(header_grid, width=max(20, min(term_w, MAX_TABLE_WIDTH + 2)))
    console.print("")
    console.print(table)
    if hidden:
        console.print(Text(f"  … {hidden} more (short screen — use --limit to page)", style=THEME_TOKENS["muted"]))
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


def create_dual_key_value_grid(
    rows: list[tuple[str, Any]],
    width: int = 16,
    padding: tuple[int, int] = (0, 3),
) -> Table:
    """Construct a 4-column balanced key-value Table grid (Key1, Val1, Key2, Val2) for wide viewports."""
    grid = Table.grid(padding=padding)
    grid.add_column(style=THEME_TOKENS["label"], width=width)
    grid.add_column(style=THEME_TOKENS["value"])
    grid.add_column(style=THEME_TOKENS["label"], width=width)
    grid.add_column(style=THEME_TOKENS["value"])

    # Clean out empty separator rows when laying out dual column
    clean_rows = [(k, v) for k, v in rows if k != ""]
    for i in range(0, len(clean_rows), 2):
        k1, v1 = clean_rows[i]
        v1_txt = v1 if isinstance(v1, Text) else Text(str(v1))
        if i + 1 < len(clean_rows):
            k2, v2 = clean_rows[i + 1]
            v2_txt = v2 if isinstance(v2, Text) else Text(str(v2))
            grid.add_row(f"  {k1}", v1_txt, f"{k2}", v2_txt)
        else:
            grid.add_row(f"  {k1}", v1_txt, "", "")
    return grid


def _dossier_heading(
    header_prefix: str,
    identifier: str,
    title: str,
    subtitle: str | None,
    status_badge: Panel | Text | None,
    bp: str,
    term_w: int,
) -> Text:
    """Identity block: PREFIX id + badge / title / subtitle. Truncates on XS."""
    shown_title = fit_text(title, max(20, term_w - 6)) if bp == "XS" else title
    shown_sub = fit_text(subtitle, max(20, term_w - 4)) if subtitle and bp == "XS" else subtitle
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
    left_text.append(f"\n  {shown_title}\n\n", style=THEME_TOKENS["value"])
    if shown_sub:
        left_text.append(f"  {shown_sub}", style=THEME_TOKENS["muted"])
    return left_text


def _render_dossier_sections(sections: list[tuple[str, str | None]], term_w: int) -> None:
    """Section blocks with narrow-terminal hash splitting."""
    for sec_title, sec_content in sections:
        console.print(Text(f"  {sec_title}", style=THEME_TOKENS["accent"]))
        if sec_content:
            # Break 64-char hashes cleanly into two 32-char lines on narrow terminals
            display_content = split_hash(sec_content, term_w)
        else:
            display_content = "--"
        console.print(
            Text(
                f"    {display_content}\n",
                style=THEME_TOKENS["value"] if sec_content else THEME_TOKENS["muted"],
            )
        )


def render_dossier(
    header_prefix: str,
    identifier: str,
    title: str,
    subtitle: str | None,
    status_badge: Panel | Text | None,
    fields: list[tuple[str, Any]],
    sections: list[tuple[str, str | None]] | None = None,
) -> None:
    """Render streamlined forensic dossier with clean whitespace and responsive layout."""
    bp, term_w = breakpoint_width()
    rule_str = rule_line(term_w)

    console.print("")
    console.print(_dossier_heading(header_prefix, identifier, title, subtitle, status_badge, bp, term_w))
    console.print("")
    console.print(Text(rule_str, style=THEME_TOKENS["border"]))

    if bp in ("LG", "XL"):
        details_grid = create_dual_key_value_grid(fields, width=16)
    else:
        details_grid = create_key_value_grid(fields, width=kv_width(bp), padding=table_padding(bp))

    console.print(details_grid)
    console.print(Text(rule_str, style=THEME_TOKENS["border"]))

    if sections:
        _render_dossier_sections(sections, term_w)


def render_detail_header(prefix: str, identifier: str, title: str, meta: str | Text) -> None:
    """Single identity block shared by case/audit dossiers: PREFIX id / title / meta."""
    header = Text()
    header.append(f"  {prefix} ", style=THEME_TOKENS["title"])
    header.append(f"{identifier}  ", style=THEME_TOKENS["accent"])
    header.append(f"\n  {title}", style=THEME_TOKENS["value"])
    if isinstance(meta, Text):
        header.append("\n")
        header.append_text(meta)
    else:
        header.append(f"\n  {meta}", style=THEME_TOKENS["muted"])
    console.print("")
    console.print(header)
    console.print("")


def render_section_title(title: str, style: str | None = None) -> None:
    """Uppercase section header shared by dossier proof blocks (CHANGES/INTEGRITY/…)."""
    console.print(Text(f"  {title}", style=style or THEME_TOKENS["accent"]))


def render_raw_tip(tip: str) -> None:
    """Closing pointer shared by detail views. Caller passes the full tip text."""
    console.print(f"[dim]Tip: {tip}[/dim]\n")


def render_key_value_grid(title: str | None, rows: list[tuple[str, Any]], width: int | None = None) -> None:
    """Render a clean frameless key-value grid with optional title."""
    bp, _ = breakpoint_width()
    w = width if width is not None else kv_width(bp)
    console.print("")
    if title:
        console.print(Text(f"  {title}\n", style=THEME_TOKENS["title"]))
    grid = create_key_value_grid(rows=rows, width=w, padding=table_padding(bp))
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
    bp, term_w = breakpoint_width()
    console.print("")
    header = Text()
    header.append(f"  {fit_text(title, max(20, term_w - 6))}", style=THEME_TOKENS["accent"])
    if bp == "XS":
        header.append("\n", style=THEME_TOKENS["muted"])
        header.append(f"  {fit_text(note, max(20, term_w - 4))}\n", style=THEME_TOKENS["muted"])
    else:
        header.append(f" — {note}\n", style=THEME_TOKENS["muted"])
    console.print(header)


def render_entity_panel(
    title: str,
    fields: list[tuple[str, Any]],
    sections: list[tuple[str, str]] | None = None,
    border_style: str | None = None,
) -> None:
    """Generic reusable card/panel renderer with clean visual separation and breathing room."""
    bp, term_w = breakpoint_width()
    border = border_style or THEME_TOKENS["border_card"]
    grid = Table.grid(expand=True, padding=table_padding(bp))
    grid.add_column(style=THEME_TOKENS["label"], width=kv_width(bp, narrow=12, default=20))
    grid.add_column(style=THEME_TOKENS["value"], overflow="fold", max_width=max(20, term_w - 30))

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
        title=f"[{THEME_TOKENS['title_hero']}] {fit_text(title, max(20, term_w - 10))} [/{THEME_TOKENS['title_hero']}]",
        border_style=border,
        box=box.ROUNDED,
        padding=(0, 1) if bp == "XS" else (1, 3),
        expand=False,
        width=max(20, term_w - 2),
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

    bp, term_w = breakpoint_width()
    visible, hidden = page_rows(rows)
    table = Table(
        title=f"\n[{THEME_TOKENS['title_hero']}]{fit_text(title, max(20, term_w - 10))}[/{THEME_TOKENS['title_hero']}]\n",
        title_style=THEME_TOKENS["title_hero"],
        border_style=THEME_TOKENS["border_card"],
        header_style=f"{THEME_TOKENS['section_title']} on #1E2833",
        box=box.ROUNDED,
        padding=table_padding(bp),
        expand=False,
        width=max(20, min(term_w - 2, MAX_TABLE_WIDTH)),
        caption=f"[{THEME_TOKENS['muted']} italic]{caption}[/{THEME_TOKENS['muted']} italic]\n" if caption else None,
    )

    for col_name, col_opts in columns:
        table.add_column(col_name, **col_opts)

    for row in visible:
        table.add_row(*_format_table_cells(row))

    console.print("")
    console.print(table)
    if hidden:
        console.print(Text(f"  … {hidden} more (short screen — use --limit to page)", style=THEME_TOKENS["muted"]))
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


def render_success(message: str) -> None:
    """Single source for success confirmations. Caller passes plain text only."""
    from rich.markup import escape

    console.print("")
    console.print(f"  [{THEME_TOKENS['success']}]{get_success_icon()} {escape(message)}[/{THEME_TOKENS['success']}]")
    console.print("")


def render_error_card(title: str, message: str, remediation: str | None = None) -> None:
    """Render a clean, frameless error notice with immediate focal point and actionable tip."""
    from rich.markup import escape

    bp, term_w = breakpoint_width()
    icon = get_error_icon()
    arrow = get_arrow_char()
    pad = "  " if bp == "XS" else "    "
    shown_title = fit_text(title, max(20, term_w - 6)) if bp == "XS" else title

    console.print("")
    console.print(f"  [{THEME_TOKENS['danger']}]{icon} {escape(shown_title)}[/{THEME_TOKENS['danger']}]")
    console.print("")
    console.print(f"{pad}[{THEME_TOKENS['value']}]{escape(message)}[/{THEME_TOKENS['value']}]")
    if remediation:
        console.print(
            f"{pad}[{THEME_TOKENS['muted']}]{arrow}[/{THEME_TOKENS['muted']}] [{THEME_TOKENS['warning']}]{escape(remediation)}[/{THEME_TOKENS['warning']}]"
        )
    console.print("")
