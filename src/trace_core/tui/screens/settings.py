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
from textual.widgets import ListItem, ListView, Rule, Static

from trace_core.audit.dto import VerifyResultDto
from trace_core.audit.renderers import subject_case_label
from trace_core.core.database.session import DatabaseSessionManager
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
    "Integrity",
    "Storage & Paths",
    "Diagnostics",
)


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
        from trace_core.tui.widgets import ThothSpinner

        with Horizontal(id="settings-top"):
            with Vertical(id="settings-left"):
                yield Static("Settings", classes="card-title")
                yield Rule()
                yield ListView(
                    *[ListItem(Static(f"  {name}"), id=f"sec-{i}") for i, name in enumerate(SECTIONS)],
                    id=TABLE_ID,
                )
            with Vertical(id="settings-right"):
                yield Static("", id=DETAIL_ID)
                yield ThothSpinner("Checking for updates", id="update-check-spin")

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
        width = self.query_one("#settings-right", Vertical).content_region.width
        if width == self._detail_width:
            return
        self._detail_width = width
        self._render_detail()

    def _render_detail(self) -> None:

        section = self._selected_section()
        try:
            pane_width = self.query_one("#settings-right", Vertical).size.width
        except Exception:
            pane_width = 60
        from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS

        body = Text()
        from trace_core.core.ui.renderers import rule_width as rule_span

        body.append(f"{section}\n", style=THEME_HEX["blue"])
        body.append_text(Text("─" * rule_span(int(pane_width or 60), 60), style=THEME_TOKENS["border"]))
        body.append("\n\n")
        renderer = {
            "Database": self._database_body,
            "Updates": self._updates_body,
            "Integrity": self._integrity_body,
            "Storage & Paths": self._storage_body,
            "Diagnostics": self._diagnostics_body,
        }.get(section, self._database_body)
        try:
            renderer(body, pane_width)
        except Exception as exc:
            body.append(f"Couldn't load this section ({exc})", style="dim")
        self.query_one(f"#{DETAIL_ID}", Static).update(body)
        from trace_core.tui.widgets import ThothSpinner

        try:
            spin = self.query_one("#update-check-spin", ThothSpinner)
            spin.display = self._checking
            if self._checking:
                spin.set_text("Checking for updates")
        except Exception:
            pass

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
        body.append("Online\n", style="bold")
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
            return
        if self._kind == "idle":
            # First paint uses the cached check so the tab never opens empty.
            try:
                prev, current, kind, extra = self._check_text()
            except Exception as exc:
                prev, current, kind, extra = "", "—", "failed", str(exc)[:MAX_ERROR_DETAIL]
            self._prev, self._current, self._kind, self._extra = prev, current, kind, extra
        current = sanitize_terminal(self._current or "—")
        body.append("Current version\n\n", style="dim")
        body.append(f"{current}\n\n", style="bold")
        if self._kind == "failed":
            body.append("✕ Check failed\n", style=THEME_HEX["amber"])
        elif self._kind == "unchecked":
            body.append("○ No recent check result\n", style=THEME_HEX["amber"])
            body.append("\nPress c to check for updates.\n", style="dim")
        elif self._kind == "available" and self._current:
            body.append(f"Update available with version: v{current}\n", style=THEME_HEX["blue"])
            body.append("\nRun this to update:\n\n", style="dim")
            body.append("  trace update install --yes\n", style="bold")
        else:
            body.append("✓ You're up to date\n", style=THEME_HEX["green"])
        if self._extra:
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

    def _integrity_body(self, body: Text, _width: int) -> None:
        """Uniform section signature (body, width); this section ignores width."""
        from trace_core.audit.service import AuditService
        from trace_core.core.ui.theme import THEME_HEX
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        svc = AuditService(self._manager)
        try:
            res = self._verified_ledger()
        except Exception as exc:
            body.append(f"Couldn't check your records ({exc})", style="dim")
            return
        if res.is_valid:
            if not res.first_seq:
                # An empty ledger is not a pass. `verify` returns is_valid=True for zero
                # rows, and a fully truncated ledger looks identical.
                body.append("⚠ ", style=DOT_BAD)
                body.append("EMPTY · NOTHING TO VERIFY\n", style="bold")
                body.append("No audit records are available to verify.\n")
                body.append("This does not prove the ledger is intact.\n", style="dim")
                return
            body.append("● ", style=DOT_OK)
            body.append("VALID · VERIFIED\n", style=f"bold {DOT_OK}")
            body.append("Chain Status       VERIFIED\n", style="dim")
            body.append(f"Events Checked     {res.events_verified}\n")
            body.append(f"Chain Breaks       {len(res.sequence_gaps)}\n")
            body.append("This does not prove no records are missing.\n", style="dim")
        elif res.mismatch_type in ("signing_key", "insecure_key", "tip_key"):
            body.append("⚠ ", style=DOT_BAD)
            body.append("SIGNING KEY PROBLEM\n", style="bold")
            if res.mismatch_type == "insecure_key":
                body.append("Signed with the shipped development key, which is public.\n", style="dim")
            elif res.mismatch_type == "tip_key":
                body.append("The chain head's signature doesn't verify with the active key.\n", style="dim")
            else:
                body.append("The key this ledger was signed with is not the active key.\n", style="dim")
            body.append(f"Events Checked     {res.events_verified}\n")
            body.append("This is a key problem, not evidence of tampering.\n", style="dim")
            return
        else:
            body.append("× ", style=DOT_BAD)
            body.append("TAMPER DETECTED\n", style=f"bold {DOT_BAD}")
            body.append("Chain Status       MISMATCH\n", style="dim")
            body.append(f"Events Checked     {res.events_verified}\n")
            return
        try:
            event = svc.get_by_seq(res.last_seq) if res.last_seq else None
        except Exception:
            event = None
        if event is None:
            return
        body.append("\nSelected Event\n", style=THEME_HEX["blue"])
        body.append(f"Seq {event.seq}  {subject_case_label(event.subject_case_number)}\n", style="dim")
        body.append(f"Payload Hash   {event.payload_hash}\n", style="dim")
        body.append(f"Previous Hash  {event.prev_chain}\n", style="dim")
        body.append(f"Chain Hash     {event.chain_hash}\n", style="dim")

    def _storage_body(self, body: Text, width: int) -> None:
        from trace_core.core.settings import settings
        from trace_core.core.ui.renderers import fit_text, sanitize_terminal

        rows = [("Storage", str(settings.storage_root))]
        try:
            from trace_updater import updater as updater_mod

            rows.append(("Install", str(updater_mod.install_root())))
        except Exception:
            rows.append(("Install", "—"))
        try:
            from trace_core.updates.trust import trust_root

            rows.append(("Trust", str(trust_root())))
        except Exception:
            rows.append(("Trust", "—"))
        from trace_core.tui.theme import append_kv

        for label, value in rows:
            append_kv(body, label, sanitize_terminal(fit_text(value, max(20, width - 14))))
        body.append("\nRead-only paths.\n", style="dim")

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
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        for label, ok, detail in checks:
            body.append("● " if ok else "× ", style=DOT_OK if ok else DOT_BAD)
            body.append(f"{label:<12} ", style="bold")
            body.append(f"{'PASS' if ok else 'FAIL'}  {detail}\n", style="dim")

    # --- actions ---

    def _describe_update(self, prev: str, payload: dict) -> tuple[str, str, str, str]:  # type: ignore[no-untyped-def]
        current = str(payload.get("target") or "—")
        parts = []
        if payload.get("security_update"):
            parts.append("Security update")
        if payload.get("minimum_supported_version"):
            parts.append(f"Minimum supported version: {payload['minimum_supported_version']}")
        if payload.get("restart_required"):
            parts.append("Trace will restart to complete this update.")
        if not payload.get("installable") and payload.get("block_reason"):
            parts.append(f"Deferred: {payload['block_reason']}")
            if payload.get("notes"):
                parts.append(str(payload["notes"]))
        return prev, current, "available", " ".join(parts)

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
        if not self._require_section("Integrity"):
            return
        self._verified = None
        self._render_detail()

    def run_command(self, command: str) -> None:
        if command in ("check", "updates-check"):
            self.action_check()
        elif command in ("install", "updates-install"):
            self.app.notify("Updates install from the CLI: trace update install --yes", severity="warning")
        elif command in ("migrate", "database-migrate"):
            self.action_migrate()
        elif command in ("verify", "anchor"):
            self.action_verify()
        elif command == "uninstall":
            self.app.notify("Run standalone: trace uninstall [--purge-data] [--yes]", severity="warning")
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

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
