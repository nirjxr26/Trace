"""Shared TUI widget behavior: scroll panes, table headers, cursor repaints.

One rule engine per behavior: dividers, header mounting, O(1) selection
repaint, cursor-to-item resolution.
"""

from collections.abc import Callable, Sequence
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import DataTable, Static

from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.tui.theme import table_head_text


class DossierScroll(VerticalScroll):
    """Scrollable dossier pane with live-width muted dividers. Single source."""

    def rule_width(self) -> int:
        try:
            width = self.scrollable_content_region.width
        except Exception:
            width = 60
        return max(20, min(66, width - 2))

    def divider(self) -> Text:
        """Muted rule sized to this pane. Recalculated on every render."""
        return Text("─" * self.rule_width(), style=THEME_TOKENS["border"])


def mount_header_table(view: Widget, table_id: str, header_id: str, columns: Sequence[tuple[str, int]]) -> DataTable:
    """Set the manual header row and fixed columns from one constant.

    Single source for the Cases/Audit left tables (header text lives outside
    the DataTable next to a full-width Rule, because box borders on
    .datatable--header are ignored by Textual).
    """
    view.query_one(f"#{header_id}", Static).update(table_head_text(list(columns)))
    table = view.query_one(f"#{table_id}", DataTable)
    for label, width in columns:
        table.add_column(label, width=width)
    return table


def repaint_selection(
    table: DataTable,
    old: int | None,
    new: int,
    row_cells: Callable[[int, bool], Sequence[Any]],
) -> None:
    """O(1) › repaint: touch the old and new rows only, so the arrow tracks the cursor.

    Single source for the Cases/Audit tables. Callers own the cursor state and
    pass a per-row cell builder; failures are swallowed row by row (a stale
    cursor must never crash the view).
    """
    if old == new:
        return
    count = table.row_count
    if old is not None and 0 <= old < count:
        for col, value in enumerate(row_cells(old, False)):
            try:
                table.update_cell_at(Coordinate(old, col), value)
            except Exception:
                pass
    if 0 <= new < count:
        for col, value in enumerate(row_cells(new, True)):
            try:
                table.update_cell_at(Coordinate(new, col), value)
            except Exception:
                pass


def selected_item[T](table: DataTable, items: Sequence[T]) -> T | None:
    """Cursor row to item, or None when nothing is selected. Single source."""
    idx = table.cursor_row
    if idx is None or idx >= len(items):
        return None
    return items[idx]
