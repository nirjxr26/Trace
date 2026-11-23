"""Settings tab: left section list + right detail. Cases/Audit untouched.

Sections reuse the exact service calls behind the old Integrity/Database/Updates
tabs plus read-only app facts. No new backend, no duplicated verification logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import ListItem, ListView, Static

from trace_core.audit.dto import VerifyResultDto
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.design.widgets import sync_detail_width, unknown_command
from trace_core.tui.widgets import active_tab

if TYPE_CHECKING:
    from trace_core.core.database.health import DbSnapshot

TABLE_ID = "settings-sections"
DETAIL_ID = "settings-detail"

# Display cap for raw exception text in section bodies and notifications.
MAX_ERROR_DETAIL = 500

SECTIONS = (
    "Database",
    "Updates",
    "Audit Integrity",
    "Storage & Paths",
    "Diagnostics",
)

SUBTITLES = {
    "Database": "Connection & migrations",
    "Updates": "Version & status",
    "Audit Integrity": "Ledger & signature",
    "Storage & Paths": "Read-only locations",
    "Diagnostics": "Component checks",
}


class SettingsView(Vertical):
    """Left: fixed section list. Right: selected section detail."""

    BINDINGS = [
        Binding("m", "migrate", "Migrate"),
        Binding("c", "check", "Check updates"),
        Binding("v", "verify", "Verify chain"),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._index = 0
        self._prev: str | None = None
        self._current: str | None = None
        self._kind = "idle"
        self._extra = ""
        self._checking = False
        self._detail_width: int | None = None
        self._db_snapshot: DbSnapshot | None = None
        self._verified: tuple[tuple[int, str], VerifyResultDto] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="settings-top", classes="pane-host"):
            with Vertical(id="settings-left", classes="pane pane-left"):
                yield Static("Settings", classes="card-title")
                yield Static("System configuration", classes="card-subtitle")
                yield ListView(
                    *[ListItem(Static(f"  {name}"), id=f"sec-{i}") for i, name in enumerate(SECTIONS)],
                    id=TABLE_ID,
                )
            with Vertical(id="settings-right", classes="pane pane-right"):
                yield Static("", id=DETAIL_ID)

    def on_mount(self) -> None:
        active = active_tab(self)
        parent_id = getattr(self.parent, "id", None)
        if parent_id is None or active is None or parent_id == active:
            self.refresh_data()

    def focus_default(self) -> None:
        self.query_one(f"#{TABLE_ID}", ListView).focus()

    def _selected_index(self) -> int:
        try:
            view = self.query_one(f"#{TABLE_ID}", ListView)
            highlighted = view.highlighted_child
            if highlighted is not None:
                return list(view.children).index(highlighted)
        except Exception:
            pass
        return self._index

    def _selected_section(self) -> str:
        idx = self._selected_index()
        if idx >= len(SECTIONS):
            return SECTIONS[0]
        return SECTIONS[idx]

    def _paint_item(self, idx: int, selected: bool) -> None:
        """O(1) › repaint: touch one item only, highlight itself is instant CSS."""
        from trace_core.tui.theme import SELECT_PREFIX

        try:
            view = self.query_one(f"#{TABLE_ID}", ListView)
            item = view.children[idx]
            item.query_one(Static).update(f"{SELECT_PREFIX if selected else '  '}{SECTIONS[idx]}")
        except Exception:
            pass

    def refresh_data(self) -> None:
        try:
            view = self.query_one(f"#{TABLE_ID}", ListView)
            view.index = max(0, min(self._index, len(SECTIONS) - 1))
        except Exception:
            pass
        self._index = self._selected_index()
        self._db_snapshot = None
        self._kind = "idle"
        for idx in range(len(SECTIONS)):
            self._paint_item(idx, idx == self._index)
        self._render_detail()
        self._refresh_hint()

    def on_resize(self, event: Resize) -> None:
        """Dividers are baked for one width; rebuild them when the width moves."""
        if not sync_detail_width(self, "settings-right", Vertical):
            return
        self._render_detail()

    def _render_detail(self) -> None:

        section = self._selected_section()
        try:
            pane_width = self.query_one("#settings-right", Vertical).size.width
        except Exception:
            pane_width = 60
        from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS

        body = Text()
        body.append(f"{section}\n", style=THEME_HEX["blue"])
        body.append(f"{SUBTITLES.get(section, '')}\n\n", style=THEME_TOKENS["muted"])
        renderer = {
            "Database": self._database_body,
            "Updates": self._updates_body,
            "Audit Integrity": self._integrity_body,
            "Storage & Paths": self._storage_body,
            "Diagnostics": self._diagnostics_body,
        }.get(section, self._database_body)
        try:
            renderer(body, pane_width)
        except Exception as exc:
            body.append(f"Could not render this section ({exc})", style="dim")
        self.query_one(f"#{DETAIL_ID}", Static).update(body)

    @staticmethod
    def _setting_row(body: Text, label: str, value: str, width: int = 60) -> None:
        from trace_core.core.ui.renderers import fit_text

        body.append(f"{label:<22}", style="dim")
        body.append(f"{fit_text(value, max(10, width - 22))}\n")

    # --- section bodies (each reuses one service, no view-to-view imports) ---

    def _snapshot(self) -> DbSnapshot:
        from trace_core.core.database.health import fetch_db_snapshot

        if self._db_snapshot is None:
            self._db_snapshot = fetch_db_snapshot(self._manager)
        return self._db_snapshot

    def _database_body(self, body: Text, width: int) -> None:
        from trace_core.core.ui.renderers import fit_text, sanitize_terminal
        from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        def _unreachable(message: str) -> None:
            body.append("× ", style=DOT_BAD)
            body.append("Database unreachable\n", style="bold")
            body.append(f"{sanitize_terminal(message)}\n", style="dim")
            body.append("Next: check TRACE_DATABASE_URL, then run `trace doctor`.\n", style="dim")

        try:
            snap = self._snapshot()
        except Exception as exc:
            _unreachable(str(exc))
            return
        if not snap.healthy:
            _unreachable(snap.message)
            return
        body.append("● ", style=DOT_OK)
        body.append("Connected\n", style=f"bold {THEME_HEX['green']}")
        body.append(f"{sanitize_terminal(fit_text(snap.masked_url, max(20, width - 4)))}\n", style="dim")
        body.append("\nMigrations\n", style=THEME_HEX["blue"])
        if snap.pending:
            body.append("○ ", style=THEME_TOKENS["warning"])
            body.append(f"{len(snap.pending)} pending — press m to apply\n")
        else:
            body.append("● ", style=DOT_OK)
            body.append("Migration complete\n")

    def _updates_body(self, body: Text, width: int) -> None:
        from trace_core.core.ui.renderers import sanitize_terminal
        from trace_core.core.ui.theme import THEME_HEX

        if self._checking:
            body.append("Checking for updates...\n", style="dim")
            return
        if self._kind == "idle":
            # First paint uses the cached check so the tab never opens empty.
            try:
                prev, current, kind, extra = self._check_text()
            except Exception as exc:
                prev, current, kind, extra = "", "—", "failed", str(exc)[:MAX_ERROR_DETAIL]
            self._prev, self._current, self._kind, self._extra = prev, current, kind, extra
        from datetime import UTC, datetime

        from trace_core.updates.cache import read_check_cache

        current = sanitize_terminal(self._current or "—")
        installed = sanitize_terminal(self._prev or "—")
        available = current if self._kind in {"available", "deferred"} else "—"
        status = {
            "available": "Available",
            "deferred": "Deferred",
            "failed": "Check failed",
            "unchecked": "Not checked",
            "current": "Up to date",
        }.get(self._kind, "Not checked")
        cache = read_check_cache(max_age=10**12)
        checked = "—"
        if cache is not None:
            try:
                checked = datetime.fromtimestamp(float(cache.get("checked_at", 0)), UTC).strftime("%d %b %Y, %H:%M UTC")
            except (TypeError, ValueError, OSError, OverflowError):
                pass
        self._setting_row(body, "Installed version", installed, width)
        self._setting_row(body, "Available version", available, width)
        self._setting_row(body, "Update status", status, width)
        self._setting_row(body, "Last checked", checked, width)
        if self._kind == "available":
            body.append("\nupdate the trace via standalone CLI\n", style="dim")
            body.append("trace update install\n", style=THEME_HEX["blue"])
        elif self._kind == "unchecked":
            body.append("\nPress c to check for updates.\n", style="dim")
        if self._extra and self._kind != "available":
            body.append(f"\n{sanitize_terminal(self._extra)}\n", style="dim")

    def _verified_ledger(self) -> VerifyResultDto:
        from trace_core.audit.service import AuditService

        svc = AuditService(self._manager)
        head = svc.head()
        if self._verified is not None and self._verified[0] == head:
            return self._verified[1]
        res = svc.verify()
        self._verified = (svc.head(), res)
        return res

    def _integrity_body(self, body: Text, width: int) -> None:
        from trace_core.audit.service import AuditService
        from trace_core.core.ui.renderers import format_india_datetime
        from trace_core.tui.theme import DOT_BAD

        svc = AuditService(self._manager)
        try:
            res = self._verified_ledger()
        except Exception as exc:
            body.append(f"Couldn't check your records ({exc})\n", style="dim")
            return
        key_problem = res.mismatch_type in ("signing_key", "insecure_key")
        if not res.first_seq:
            chain = "Empty"
        elif key_problem or res.is_valid:
            chain = "Valid"
        else:
            chain = "Mismatch"
        if key_problem:
            signature = "Development key" if res.mismatch_type == "insecure_key" else "Key unavailable"
        elif not res.first_seq or not res.is_valid:
            signature = "Not established"
        else:
            signature = "Active key"
        verified = "—"
        try:
            seq, _chain = svc.head()
            head = svc.get_by_seq(seq)
            if head is not None:
                verified = format_india_datetime(head.ts)
        except Exception:
            pass
        self._setting_row(body, "Chain status", chain, width)
        self._setting_row(body, "Events checked", str(res.events_verified), width)
        self._setting_row(body, "Chain breaks", str(len(res.sequence_gaps)), width)
        self._setting_row(body, "Signature status", signature, width)
        self._setting_row(body, "Last verified", verified, width)
        body.append("\nHash-chain validity is not independent authenticity.\n", style="dim")
        if key_problem:
            body.append("This is a key problem, not evidence of tampering.\n", style=DOT_BAD)

    def _storage_body(self, body: Text, width: int) -> None:
        from trace_core.core.settings import settings
        from trace_core.core.ui.renderers import sanitize_terminal

        rows = [("Storage root", str(settings.storage_root))]
        try:
            from trace_updater import updater as updater_mod

            rows.append(("Install root", str(updater_mod.install_root())))
        except Exception:
            rows.append(("Install root", "—"))
        try:
            from trace_core.updates.trust import trust_root

            rows.append(("Trust root", str(trust_root())))
        except Exception:
            rows.append(("Trust root", "—"))
        rows.append(("Access", "read-only in TUI"))

        for label, value in rows:
            self._setting_row(body, label, sanitize_terminal(value), width)

    def _db_checks(self) -> list[tuple[str, bool, str]]:
        try:
            snap = self._snapshot()
        except Exception as exc:
            return [("Database", False, str(exc))]
        checks = [("Database", snap.healthy, "Online" if snap.healthy else snap.message)]
        if snap.healthy:
            if snap.pending:
                checks.append(("Migrations", False, f"{len(snap.pending)} pending"))
            else:
                checks.append(("Migrations", True, f"{len(snap.applied)} applied"))
        return checks

    def _diagnostics_body(self, body: Text, _width: int) -> None:
        """Uniform section signature (body, width); this section ignores width."""
        from trace_core.core.cli.doctor import _python_check, _storage_check

        checks: list[tuple[str, bool, str]] = []
        name, detail, passed = _python_check()
        checks.append((name, passed, detail))
        checks.extend(self._db_checks())
        name, detail, passed = _storage_check(probe=False)
        checks.append((name, passed, detail))
        from trace_core.core.ui.theme import THEME_HEX
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        for label, ok, _detail in checks:
            body.append("● " if ok else "× ", style=DOT_OK if ok else DOT_BAD)
            body.append(f"{label:<16} ", style="bold")
            body.append(f"{'PASS' if ok else 'FAIL'}\n", style=THEME_HEX["green"] if ok else "dim")

    # --- actions ---

    def _describe_update(self, prev: str, payload: dict) -> tuple[str, str, str, str]:  # type: ignore[no-untyped-def]
        current = str(payload.get("target") or "—")
        if not payload.get("installable"):
            parts = []
            if payload.get("block_reason"):
                parts.append(f"Deferred: {payload['block_reason']}")
            if payload.get("notes"):
                parts.append(str(payload["notes"]))
            return prev, current, "deferred", " ".join(parts)
        if payload.get("security_update"):
            return prev, current, "available", "Security update"
        return prev, current, "available", ""

    def _check_text(self) -> tuple[str, str, str, str]:
        """Cached state only. Painting the tab must never touch the network; a live
        check runs on the user's action (action_check) in a worker thread."""
        from trace_core.updates.cache import read_check_cache
        from trace_core.updates.checker import get_installed_version

        prev = str(get_installed_version())
        cached = read_check_cache()
        payload = (cached or {}).get("payload") or {}
        if payload.get("available") and payload.get("target"):
            return self._describe_update(prev, payload)
        if cached is None:
            return prev, prev, "unchecked", ""
        return prev, prev, "current", ""

    def _refresh_hint(self) -> None:
        """Cached only: a paint never touches the network (H-65 shape)."""
        from textual.widgets import Static

        from trace_core.updates.checker import peek_cached_update

        payload = peek_cached_update()
        if payload is None:
            return
        try:
            self.app.query_one("#hint", Static).update(f"↑ Update {payload['target']} available")
        except Exception:
            pass

    def _live_check(self) -> tuple[str, str, str, str]:
        from trace_core.updates.checker import (
            cached_check,
            get_installed_version,
            resolve_channel,
            resolve_manifest_target,
        )

        channel = resolve_channel(None)
        target = resolve_manifest_target(None)
        payload = cached_check(target, channel)
        prev = str(payload.get("current") or get_installed_version())
        if not payload["available"]:
            return prev, prev, "current", ""
        return self._describe_update(prev, payload)

    def _require_section(self, section: str) -> bool:
        if self._selected_section() != section:
            self.app.notify(f"Select {section} first.", severity="warning")
            return False
        return True

    def action_check(self) -> None:
        if not self._require_section("Updates"):
            return
        if self._checking:
            return
        self._checking = True
        self._render_detail()
        self.app.run_worker(self._check_worker())

    async def _check_worker(self) -> None:
        import asyncio

        from trace_core.updates.checker import get_installed_version

        try:
            result = await asyncio.to_thread(self._live_check)
        except Exception as exc:
            try:
                prev = get_installed_version()
            except Exception:
                prev = ""
            self._prev, self._current, self._kind, self._extra = prev, "—", "failed", str(exc)[:MAX_ERROR_DETAIL]
            self.app.notify(str(exc)[:MAX_ERROR_DETAIL], severity="error")
        else:
            self._prev, self._current, self._kind, self._extra = result
        self._checking = False
        self._render_detail()
        self._refresh_hint()

    def action_migrate(self) -> None:
        if not self._require_section("Database"):
            return
        from trace_core.core.database.migrations import apply_migrations
        from trace_core.tui.actions import run_guarded

        def _migrate() -> str:
            mgr = self._manager
            if mgr is None:
                from trace_core.core.database.session import db_manager

                mgr = db_manager
            applied = apply_migrations(mgr.engine)
            return f"Applied {len(applied)} migration(s)." if applied else "Already up to date."

        run_guarded(self, _migrate)

    def action_verify(self) -> None:
        if not self._require_section("Audit Integrity"):
            return
        self._verified = None
        self._render_detail()

    def run_command(self, command: str) -> None:
        if command in ("check", "updates-check"):
            self.action_check()
        elif command in ("migrate", "database-migrate"):
            self.action_migrate()
        elif command in ("verify", "anchor"):
            self.action_verify()
        else:
            unknown_command(self, command)

    @on(ListView.Highlighted)
    def _highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != TABLE_ID:
            return
        try:
            new = list(event.list_view.children).index(event.item) if event.item is not None else 0
        except Exception:
            new = 0
        old = self._index
        self._index = new
        if old != new:
            self._paint_item(old, False)
            self._paint_item(new, True)
            try:
                from trace_core.tui.app import TAB_HINTS

                self.app.query_one("#hint", Static).update(TAB_HINTS["settings"])
            except Exception:
                pass
        self._render_detail()

    @on(ListView.Selected)
    def _opened(self, event: ListView.Selected) -> None:
        if event.list_view.id == TABLE_ID and self._selected_section() == "Updates":
            self.action_check()
