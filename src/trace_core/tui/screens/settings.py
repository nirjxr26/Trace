"""Settings tab: left section list + right detail. Cases/Audit untouched.

Sections reuse the exact service calls behind the old Integrity/Database/Updates
tabs plus read-only app facts. No new backend, no duplicated verification logic.
"""

from time import monotonic

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Button, ListItem, ListView, Rule, Static

from trace_core.audit.renderers import subject_case_label
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.updates.stages import STAGE_ORDER, Stage, StageStatus, stage_glyph, stage_is_spinning

TABLE_ID = "settings-sections"
DETAIL_ID = "settings-detail"

# Display cap for raw exception text in section bodies and notifications.
MAX_ERROR_DETAIL = 500

# Matches the install loop cadence in install.sh / install.ps1 and the update display.
SPIN_INTERVAL = 0.12

SECTIONS = (
    "Database",
    "Updates",
    "Integrity",
    "Storage & Paths",
    "Diagnostics",
)


class _TuiProgress:
    def __init__(self, view: "SettingsView") -> None:
        self._view = view

    def on_bytes(self, read: int, total: int) -> None:
        view = self._view
        try:
            view.app.call_from_thread(view._update_download, read, total)
        except Exception:
            pass

    def on_stage(self, stage: Stage, status: StageStatus) -> None:
        view = self._view
        try:
            view.app.call_from_thread(view._on_update_stage, stage, status)
        except Exception:
            pass


class SettingsView(Vertical):
    """Left: fixed section list. Right: selected section detail."""

    BINDINGS = [
        Binding("m", "migrate", "Migrate"),
        Binding("c", "check", "Check updates"),
        Binding("u", "install", "Install update"),
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
        self._installing = False
        self._install_state = {stage: StageStatus.PENDING for stage in STAGE_ORDER}
        self._dl_read = 0
        self._dl_total = 0
        self._active_since: float | None = None
        self._spin = 0
        self._spin_timer: Timer | None = None

    def compose(self) -> ComposeResult:
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
                yield Button("⬇  Install update", id="update-apply", variant="primary")

    def on_mount(self) -> None:
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
        for idx in range(len(SECTIONS)):
            self._paint_item(idx, idx == self._index)
        self._render_detail()
        self._refresh_hint()

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
        body.append("\n")
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
            body.append(f"Version unavailable ({exc})", style="dim")
        self.query_one(f"#{DETAIL_ID}", Static).update(body)
        try:
            show_apply = (
                section == "Updates" and self._kind == "available" and bool(self._current) and not self._installing
            )
            self.query_one("#update-apply", Button).display = show_apply
        except Exception:
            pass

    # --- section bodies (each reuses one service, no view-to-view imports) ---

    def _database_body(self, body: Text, width: int) -> None:
        from trace_core.core.database.health import fetch_db_snapshot
        from trace_core.core.ui.renderers import fit_text, sanitize_terminal
        from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        def _unreachable(message: str) -> None:
            body.append("× ", style=DOT_BAD)
            body.append("Database unreachable\n", style="bold")
            body.append(f"{sanitize_terminal(message)}\n", style="dim")
            body.append("Next: check TRACE_DATABASE_URL, then run `trace doctor`.\n", style="dim")

        try:
            snap = fetch_db_snapshot(self._manager)
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
        from trace_core.core.ui.renderers import sanitize_terminal, step_line
        from trace_core.core.ui.theme import THEME_HEX
        from trace_core.updates.stages import StageStatus

        if self._checking:
            body.append_text(step_line(StageStatus.ACTIVE, "Checking for updates…"))
            body.append("\n")
            return
        if self._installing:
            self._install_lines(body)
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
        elif self._kind == "available" and self._current:
            body.append(f"↑ Update available → v{current}\n", style=THEME_HEX["blue"])
        else:
            body.append("✓ You're up to date\n", style=THEME_HEX["green"])
        if self._extra:
            body.append(f"\n{sanitize_terminal(self._extra)}\n", style="dim")
        if self._kind == "available" and self._current:
            body.append("\nPress u or pick Update below to install.\n", style="dim")

    def _install_lines(self, body: Text) -> None:
        from trace_core.core.ui.renderers import done_line, step_line
        from trace_core.tui.theme import download_bar
        from trace_core.updates.stages import Stage, StageStatus, stage_label

        prev = self._prev or "?"
        current = self._current or "?"
        body.append(f"Updating Trace v{prev} → v{current}\n")
        body.append("\n")
        failed = False
        for stage in STAGE_ORDER:
            status = self._install_state.get(stage, StageStatus.PENDING)
            body.append_text(step_line(status, stage_label(stage), glyph=stage_glyph(status, self._spin)))
            body.append("\n")
            if status == StageStatus.FAILED:
                failed = True
            if stage == Stage.DOWNLOAD and status == StageStatus.ACTIVE and self._dl_total > 0:
                body.append_text(download_bar(self._dl_read, self._dl_total))
                body.append("\n")
        if not failed and all(self._install_state.get(s) == StageStatus.DONE for s in STAGE_ORDER):
            body.append_text(done_line())
            body.append("\n")

    def _integrity_body(self, body: Text, _width: int) -> None:
        """Uniform section signature (body, width); this section ignores width."""
        from trace_core.audit.service import AuditService
        from trace_core.core.ui.theme import THEME_HEX
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        svc = AuditService(self._manager)
        try:
            res = svc.verify()
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
        from trace_core.core.database.health import fetch_db_snapshot

        try:
            snap = fetch_db_snapshot(self._manager)
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
        from trace_core.updates.checker import get_installed_version, peek_cached_update

        prev = str(get_installed_version())
        payload = peek_cached_update()
        if payload is None or not payload["available"]:
            return prev, prev, "current", ""
        return self._describe_update(prev, payload)

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

    def action_install(self) -> None:
        if not self._require_section("Updates"):
            return
        if self._kind != "available" or not self._current:
            self.app.notify("Nothing to install.", severity="warning")
            return
        from trace_core.tui.forms import YesNoModal

        prev = self._prev or "?"
        self.app.push_screen(YesNoModal(f"Install update {prev} → {self._current}?"), self._install_confirmed)

    def _install_confirmed(self, ok: bool | None) -> None:
        if not ok:
            return
        self._install_state = {stage: StageStatus.PENDING for stage in STAGE_ORDER}
        self._installing = True
        self._dl_read = 0
        self._dl_total = 0
        self._active_since = None
        self._spin = 0
        self._start_spin()
        self._render_detail()
        self.app.run_worker(self._install_worker())

    async def _install_worker(self) -> None:
        import asyncio
        import uuid

        from trace_core.updates.commands import prepare_install
        from trace_core.updates.lifecycle import UpdateLifecycle

        def sync_install():  # type: ignore[no-untyped-def]
            m, _target, _current, artifact_path, _entry, channel = prepare_install(None, None)
            return UpdateLifecycle(str(uuid.uuid4())).run(
                m, artifact_path, channel=channel, progress=_TuiProgress(self)
            )

        try:
            dto = await asyncio.to_thread(sync_install)
        except Exception as exc:
            self._stop_spin()
            self._installing = False
            self.app.notify(str(exc)[:MAX_ERROR_DETAIL], severity="error")
            self.action_check()
            return
        self._stop_spin()
        self._installing = False
        self.app.notify(f"Trace updated to v{dto.to_version}.")
        self.action_check()

    def _on_update_stage(self, stage: Stage, status: StageStatus) -> None:
        self._install_state[stage] = status
        if status is StageStatus.ACTIVE:
            self._active_since = monotonic()
        elif status is not StageStatus.PENDING:
            self._active_since = None
            self._spin = 0
        try:
            self._render_detail()
        except Exception:
            pass

    def _start_spin(self) -> None:
        self._stop_spin()
        self._spin_timer = self.set_interval(SPIN_INTERVAL, self._tick_spin)

    def _stop_spin(self) -> None:
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

    def _tick_spin(self) -> None:
        """Advance the glyph while a step is running.

        The panel only redrew when the worker reported progress, so a long step that emits
        nothing — verifying, installing, the health check — sat on one static glyph for its
        whole duration. The gate is the shared one, so a step under the delay still holds
        still here exactly as it does in the installer and the update display.
        """
        if self._active_since is None or not stage_is_spinning(self._active_since, monotonic()):
            return
        self._spin += 1
        try:
            self._render_detail()
        except Exception:
            pass

    def _update_download(self, read: int, total: int) -> None:
        self._dl_read = read
        self._dl_total = total
        try:
            self._render_detail()
        except Exception:
            pass

    @on(Button.Pressed, "#update-apply")
    def _apply_pressed(self) -> None:
        self.action_install()

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
        self._render_detail()

    def run_command(self, command: str) -> None:
        if command in ("check", "updates-check"):
            self.action_check()
        elif command in ("install", "updates-install"):
            self.action_install()
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
