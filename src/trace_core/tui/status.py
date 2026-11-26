"""Palette-triggered system status popup with in-place detail views."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

from trace_core.core.ui.renderers import sanitize_terminal
from trace_core.tui.forms import _BaseModal
from trace_core.tui.palette import PALETTE_CSS
from trace_core.tui.theme import DOT_BAD, DOT_OK

if TYPE_CHECKING:
    from trace_core.core.database.session import DatabaseSessionManager

MAX_ERROR_DETAIL = 500
CHECKING = "Checking…"
CHECKING_UPDATES = "Checking for updates…"


class StatusModal(_BaseModal, ModalScreen[None]):
    """Read-only status rows. Updates and System status drill in place."""

    CSS = (
        PALETTE_CSS
        + """
    StatusModal { align: center middle; }
    #status-title { width: 1fr; color: $accent; padding-left: 1; }
    #status-detail { height: auto; color: $muted; padding-left: 1; display: none; }
    .cmd-value { width: auto; max-width: 32; text-align: right; color: $muted; }
    """
    )

    BINDINGS = [
        Binding("escape", "back_or_cancel", "Back"),
        Binding("down", "list_down", "Next", priority=True),
        Binding("up", "list_up", "Prev", priority=True),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._detail: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            with Horizontal(id="palette-head"):
                yield Static("Settings", id="status-title")
                yield Static("esc", id="palette-esc")
            yield ListView(
                ListItem(
                    Horizontal(
                        Static("Migrate DB", classes="cmd-label"),
                        Static(CHECKING, classes="cmd-value"),
                        classes="cmd-columns",
                    ),
                    id="row-database",
                    disabled=True,
                ),
                ListItem(
                    Horizontal(
                        Static("Check updates", classes="cmd-label"),
                        Static(CHECKING, classes="cmd-value"),
                        classes="cmd-columns",
                    ),
                    id="row-updates",
                ),
                ListItem(
                    Horizontal(
                        Static("System status", classes="cmd-label"),
                        Static(CHECKING, classes="cmd-value"),
                        classes="cmd-columns",
                    ),
                    id="row-system",
                ),
                ListItem(
                    Horizontal(
                        Static("Audit integrity", classes="cmd-label"),
                        Static(CHECKING, classes="cmd-value"),
                        classes="cmd-columns",
                    ),
                    id="row-integrity",
                    disabled=True,
                ),
                id="palette-list",
            )
            yield Static("", id="status-detail")

    async def on_mount(self) -> None:
        from trace_core.updates.checker import peek_cached_update

        self._set_value("row-integrity", CHECKING)
        self._set_value("row-system", CHECKING)
        try:
            cached = peek_cached_update()
        except Exception as exc:
            self._set_value("row-updates", self._bad(f"Check failed · {_detail(exc)}"))
        else:
            self._set_value("row-updates", self._update_label(cached))
        self.app.run_worker(self._load_all(), name="status-all")

    def _set_value(self, row_id: str, value: str | Text) -> None:
        try:
            self.query_one(f"#{row_id} .cmd-value", Static).update(value)
        except Exception:
            pass

    @staticmethod
    def _update_label(cached: dict[str, Any] | None) -> str | Text:
        if cached is None:
            return "Not checked"
        target = str(cached.get("target") or "")
        if target:
            return f"Available {target}"
        return "Up to date"

    @staticmethod
    def _bad(message: str) -> Text:
        return Text(message, style=DOT_BAD)

    @staticmethod
    def _good(message: str) -> Text:
        return Text(message, style=DOT_OK)

    async def _load_all(self) -> None:
        from trace_core.audit.service import AuditService
        from trace_core.core.database.health import fetch_db_snapshot

        def gather() -> tuple[Any, bool, Any, int | None]:
            snapshot = fetch_db_snapshot(self._manager)
            healthy, _ = health_rows(self._manager)
            result = AuditService(self._manager).verify()
            mismatch = result.first_mismatch_seq if not result.is_valid else None
            return snapshot, healthy, result, mismatch

        try:
            snapshot, healthy, result, mismatch = await asyncio.to_thread(gather)
        except Exception as exc:
            message = self._bad(f"Check failed · {_detail(exc)}")
            for row_id in ("row-database", "row-system", "row-integrity"):
                self.call_later(self._set_value, row_id, message)
            return
        database = self._good("Connected") if snapshot.healthy else self._bad(f"Unreachable · {snapshot.message}")
        system = self._good("Healthy") if healthy else self._bad("Unhealthy")
        if result.is_valid:
            integrity = self._good("Valid") if result.events_verified else Text("Empty", style="muted")
        elif mismatch is not None:
            integrity = self._bad(f"Mismatch · seq {mismatch}")
        else:
            integrity = self._bad("Mismatch")
        self.call_later(self._set_value, "row-database", database)
        self.call_later(self._set_value, "row-system", system)
        self.call_later(self._set_value, "row-integrity", integrity)

    @on(ListView.Selected, "#palette-list")
    def _selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        if event.item.id == "row-updates":
            self._open_detail("updates", "Settings", CHECKING_UPDATES)
            self.app.run_worker(self._load_updates(), name="status-updates")
        elif event.item.id == "row-system":
            self._open_detail("system", "Settings", CHECKING)
            self.app.run_worker(self._load_health(), name="status-health")

    def _open_detail(self, name: str, title: str, detail: str) -> None:
        self._detail = name
        self.query_one("#status-title", Static).update(title)
        self.query_one("#palette-list", ListView).display = False
        target = self.query_one("#status-detail", Static)
        target.update(detail)
        target.display = True

    def action_back_or_cancel(self) -> None:
        if self._detail is None:
            self.dismiss(None)
            return
        self._detail = None
        self.query_one("#status-title", Static).update("Settings")
        self.query_one("#status-detail", Static).display = False
        view = self.query_one("#palette-list", ListView)
        view.display = True
        view.focus()

    def action_list_down(self) -> None:
        if self._detail is None:
            self.query_one("#palette-list", ListView).action_cursor_down()

    def action_list_up(self) -> None:
        if self._detail is None:
            self.query_one("#palette-list", ListView).action_cursor_up()

    def _update_detail(self, value: str | Text) -> None:
        if self._detail is not None:
            self.query_one("#status-detail", Static).update(value)

    async def _load_updates(self) -> None:
        from trace_core.updates.checker import peek_cached_update

        await asyncio.sleep(0.15)
        try:
            payload = peek_cached_update()
        except Exception as exc:
            self.call_later(self._update_detail, self._bad(f"Check failed · {_detail(exc)}"))
            return
        target = str((payload or {}).get("target") or "")
        detail = (
            f"Update available to {target}\nInstall with: trace update install" if target else "Update not available"
        )
        self.call_later(self._update_detail, detail)

    async def _load_health(self) -> None:
        try:
            _, rows = await asyncio.to_thread(health_rows, self._manager)
        except Exception as exc:
            self.call_later(self._update_detail, self._bad(f"Check failed · {_detail(exc)}"))
            return
        body = Text()
        for index, (_, _, passed) in enumerate(rows):
            if index:
                body.append("  ")
            body.append("PASS" if passed else "FAIL", style=DOT_OK if passed else DOT_BAD)
        self.call_later(self._update_detail, body)


def health_rows(manager: DatabaseSessionManager | None) -> tuple[bool, list[tuple[str, str, bool]]]:
    from trace_core.core.cli.doctor import (
        _ledger_check,
        _protection_check,
        _python_check,
        _signing_key_check,
        _storage_check,
    )
    from trace_core.core.database.health import fetch_db_snapshot
    from trace_core.core.database.session import db_manager

    manager = manager or db_manager
    rows: list[tuple[str, str, bool]] = []
    for check in (_python_check, _signing_key_check):
        try:
            rows.append(check())
        except Exception as exc:
            rows.append((check.__name__.strip("_").replace("_check", "").title(), _detail(exc), False))
    try:
        snapshot = fetch_db_snapshot(manager)
    except Exception as exc:
        rows.append(("Database", _detail(exc), False))
    else:
        rows.append(("Database", sanitize_terminal(snapshot.message)[:MAX_ERROR_DETAIL], snapshot.healthy))
        if snapshot.healthy:
            pending = len(snapshot.pending)
            rows.append(("Migrations", f"{pending} pending" if pending else "up to date", pending == 0))
        else:
            rows.append(("Migrations", "skipped", True))
    try:
        rows.append(_ledger_check(manager))
    except Exception as exc:
        rows.append(("Records", _detail(exc), False))
    try:
        rows.append(_protection_check(manager))
    except Exception as exc:
        rows.append(("Records Protected", _detail(exc), False))
    try:
        rows.append(_storage_check(probe=False))
    except Exception as exc:
        rows.append(("Storage", _detail(exc), False))
    return all(passed for _, _, passed in rows), rows


def _detail(exc: Exception) -> str:
    return sanitize_terminal(str(exc))[:MAX_ERROR_DETAIL]
