"""Shared TUI widget behavior: scroll panes, table headers, cursor repaints.

One rule engine per behavior: dividers, header mounting, O(1) selection
repaint, cursor-to-item resolution.
"""

from collections.abc import Callable, Sequence
from typing import Any

from rich.text import Text
from textual import on
from textual.containers import Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static

from trace_core.core.ui.theme import THEME_TOKENS
from trace_core.tui.theme import table_head_text


class DossierScroll(VerticalScroll):
    """Scrollable dossier pane with live-width muted dividers. Single source."""

    def rule_width(self) -> int:
        from trace_core.core.ui.renderers import rule_width

        try:
            width = self.scrollable_content_region.width
        except Exception:
            width = 60
        return rule_width(width, 66)

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


class PagedTable(DataTable):
    """DataTable that reports vertical scrolling to a callback."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.on_scrolled: Callable[[], None] | None = None

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if round(old_value) == round(new_value):
            return
        if self.on_scrolled is not None:
            self.on_scrolled()


class TablePane[T](Vertical):
    """Filterable list pane shared by the Cases/Audit tabs. Single source for the table.

    Subclasses declare the four ids and the column widths, then supply the item list,
    the per-row cells, and the detail render. Everything else — header mount, cursor
    repaint, selection, focus, and the search debounce — lives here so the two tabs
    cannot drift apart again.
    """

    TABLE_ID: str = ""
    HEADER_ID: str = ""
    DETAIL_ID: str = ""
    SEARCH_ID: str = ""
    COLUMNS: Sequence[tuple[str, int]] = ()

    def __init__(self) -> None:
        super().__init__()
        self._items: list[T] = []
        self._search_timer: Timer | None = None
        self._last_cursor: int | None = None

    def row_cells(self, item: T, selected: bool) -> Sequence[Any]:
        raise NotImplementedError

    def render_detail(self) -> None:
        raise NotImplementedError

    def _table(self) -> DataTable:
        return self.query_one(f"#{self.TABLE_ID}", DataTable)

    def on_mount(self) -> None:
        mount_header_table(self, self.TABLE_ID, self.HEADER_ID, self.COLUMNS)
        self.refresh_data()

    def focus_default(self) -> None:
        self._table().focus()

    def displayed_count(self) -> int:
        return len(self._items)

    def _update_header(self) -> None:
        from trace_core.tui.theme import header_with_count

        self.query_one(f"#{self.HEADER_ID}", Static).update(header_with_count(self.COLUMNS, self.displayed_count()))

    def fill_table(self, rows: Sequence[T], keys: Sequence[str]) -> None:
        """Replace the table body and restore the cursor onto the same row index."""
        self._items = list(rows)
        table = self._table()
        table.clear()
        cursor = table.cursor_row if table.cursor_row is not None else 0
        for idx, row in enumerate(self._items):
            table.add_row(*self.row_cells(row, idx == cursor), key=keys[idx])
        try:
            if self._items:
                table.move_cursor(row=min(cursor, len(self._items) - 1))
        except Exception:
            pass
        self._last_cursor = table.cursor_row if table.cursor_row is not None else 0
        self._update_header()
        self.render_detail()

    def refresh_data(self) -> None:
        raise NotImplementedError

    def append_rows(self, rows: Sequence[T], keys: Sequence[str]) -> None:
        """Extend the table body without clearing or moving the cursor."""
        if not rows:
            return
        table = self._table()
        cursor = table.cursor_row if table.cursor_row is not None else 0
        start = len(self._items)
        self._items.extend(rows)
        for offset, row in enumerate(rows):
            table.add_row(*self.row_cells(row, start + offset == cursor), key=keys[offset])
        self._update_header()

    def _repaint_selection(self) -> None:
        table = self._table()
        if not self._items:
            return
        cursor = table.cursor_row if table.cursor_row is not None else 0
        repaint_selection(table, self._last_cursor, cursor, lambda idx, sel: self.row_cells(self._items[idx], sel))
        self._last_cursor = cursor

    def _selected(self) -> T | None:
        return selected_item(self._table(), self._items)

    @on(DataTable.RowHighlighted)
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == self.TABLE_ID:
            self._repaint_selection()
            self.render_detail()

    @on(DataTable.RowSelected)
    def _opened(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == self.TABLE_ID:
            self.query_one(f"#{self.DETAIL_ID}").focus()

    @on(Input.Changed)
    def _searched(self, event: Input.Changed) -> None:
        if event.input.id == self.SEARCH_ID:
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.25, self.refresh_data)

    def action_search(self) -> None:
        self.query_one(f"#{self.SEARCH_ID}", Input).focus()
