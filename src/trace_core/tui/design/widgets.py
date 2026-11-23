from collections.abc import Callable, Sequence

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Rule, Static

from trace_core.core.ui.theme import THEME_HEX
from trace_core.tui.design.text import unknown_command_text
from trace_core.tui.widgets import DossierScroll


class FlatButton(Button):
    def on_mount(self) -> None:
        self.styles.line_pad = 0
        self.styles.height = 3
        self.styles.text_align = "center"
        self.styles.content_align = ("center", "middle")


class ModalFrame(Vertical):
    def __init__(self, *, widget_id: str, elevated: bool = False) -> None:
        classes = "modal-box modal-box-elevated" if elevated else "modal-box"
        super().__init__(id=widget_id, classes=classes)


class ListDetailPane(Horizontal):
    def __init__(
        self,
        *,
        top_id: str,
        left_id: str,
        right_id: str,
        detail_id: str,
        detail_text: str,
        search_id: str,
        search_placeholder: str,
        header_id: str,
        table_factory: Callable[[], Widget],
        left_extra: Sequence[Widget] = (),
    ) -> None:
        super().__init__(id=top_id, classes="pane-host")
        self._left_id = left_id
        self._right_id = right_id
        self._detail_id = detail_id
        self._detail_text = detail_text
        self._search_id = search_id
        self._search_placeholder = search_placeholder
        self._header_id = header_id
        self._table_factory = table_factory
        self._left_extra = list(left_extra)

    def compose(self):  # type: ignore[no-untyped-def]
        with Vertical(id=self._left_id, classes="pane pane-left"):
            yield Input(placeholder=self._search_placeholder, id=self._search_id, classes="pane-search")
            yield from self._left_extra
            yield Static("", id=self._header_id, classes="table-head")
            yield Rule(classes="pane-rule")
            yield self._table_factory()
        with DossierScroll(id=self._right_id, classes="pane pane-right"):
            yield Static(self._detail_text, id=self._detail_id)


class SegmentedProgress(Static):
    WIDTH = 40

    def set_progress(self, ratio: float, color: str = THEME_HEX["green"]) -> None:
        filled = round(max(0.0, min(1.0, ratio)) * self.WIDTH)
        text = Text()
        text.append("[", style=THEME_HEX["muted"])
        text.append("█" * filled, style=f"bold {color}")
        text.append("░" * (self.WIDTH - filled), style=THEME_HEX["disabled"])
        text.append("]", style=THEME_HEX["muted"])
        self.update(text)


def sync_detail_width(view: Widget, pane_id: str, widget_type: type[Widget] = DossierScroll) -> bool:
    width = view.query_one(f"#{pane_id}", widget_type).content_region.width
    if width == getattr(view, "_detail_width", None):
        return False
    view._detail_width = width  # type: ignore[attr-defined]
    return True


def unknown_command(view: Widget, command: str) -> None:
    view.app.notify(unknown_command_text(command), severity="warning")
