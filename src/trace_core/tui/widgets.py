"""Shared scroll panes for dossier views. One rule engine for every divider."""

from rich.text import Text
from textual.containers import VerticalScroll

from trace_core.core.ui.theme import THEME_TOKENS


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
