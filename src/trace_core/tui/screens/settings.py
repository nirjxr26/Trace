"""Settings tab: left section list + right detail. Cases/Audit untouched.

Sections reuse the exact service calls behind the old Integrity/Database/Updates
tabs plus read-only app facts. No new backend, no duplicated verification logic.
"""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ListItem, ListView, Rule, Static

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.updates.stages import STAGE_ORDER, Stage, StageStatus

TABLE_ID = "settings-sections"
DETAIL_ID = "settings-detail"

SECTIONS = (
    "Database",
    "Updates",
    "Integrity",
    "Storage & Paths",
    "Operator & Env",
    "Diagnostics",
    "About",
)


class _TuiProgress:
    def __init__(self, view: "SettingsView") -> None:
        self._view = view

    def on_bytes(self, read: int, total: int) -> None:
        _ = (read, total)

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
                yield Button("Update", id="update-apply")

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
        self._maybe_refresh_hint()

    def _render_detail(self) -> None:

        section = self._selected_section()
        try:
            pane_width = self.query_one("#settings-right", Vertical).size.width
        except Exception:
            pane_width = 60
        from trace_core.core.ui.theme import THEME_TOKENS

        body = Text()
        body.append(f"{section}\n", style="#72B7D3")
        rule_width = max(20, min(60, int(pane_width or 60) - 2))
        body.append_text(Text("─" * rule_width, style=THEME_TOKENS["border"]))
        body.append("\n")
        renderer = {
            "Database": self._database_body,
            "Updates": self._updates_body,
            "Integrity": self._integrity_body,
            "Storage & Paths": self._storage_body,
            "Operator & Env": self._operator_body,
            "Diagnostics": self._diagnostics_body,
            "About": self._about_body,
        }.get(section, self._about_body)
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
        from trace_core.core.database.health import fetch_db_snapshot, migration_entries
        from trace_core.core.ui.renderers import fit_text, sanitize_terminal

        mgr = self._manager
        try:
            snap = fetch_db_snapshot(mgr)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        if not snap.healthy:
            body.append("× ", style="#D06A73")
            body.append("Offline\n", style="bold")
            body.append("Unable to connect to database\n", style="dim")
            return
        body.append("● ", style="#5FD18A")
        body.append("Online\n", style="bold")
        body.append(f"{sanitize_terminal(fit_text(snap.masked_url, max(20, width - 4)))}\n", style="dim")
        body.append("\nMigrations\n", style="#72B7D3")
        name_budget = max(16, min(42, width - 16))
        for version, name, state, _ in migration_entries(snap.applied, snap.pending):
            mark = "●" if state == "Applied" else "○"
            color = "#5FD18A" if state == "Applied" else "#D8B56A"
            body.append(f"{mark} ", style=color)
            body.append(f"{version:<4} {sanitize_terminal(fit_text(name, name_budget))}\n")

    def _updates_body(self, body: Text, width: int) -> None:
        from trace_core.core.ui.renderers import sanitize_terminal
        from trace_core.core.ui.theme import THEME_TOKENS
        from trace_core.tui.theme import update_status_text

        if self._checking:
            body.append("Checking…\n", style="dim")
            return
        if self._installing:
            self._install_lines(body)
            return
        if self._kind == "idle":
            # First paint uses the cached check so the tab never opens empty.
            try:
                prev, current, kind, extra = self._check_text()
            except Exception as exc:
                prev, current, kind, extra = "", "—", "failed", str(exc)[:300]
            self._prev, self._current, self._kind, self._extra = prev, current, kind, extra
        current = sanitize_terminal(self._current or "—")
        body.append("Current version\n", style="dim")
        body.append(f"{current}\n")
        if self._kind != "available" or not self._current:
            body.append(f"{'Status':<10} ", style="dim")
            body.append_text(update_status_text(self._kind))
            body.append("\n")
            if self._extra:
                body.append(f"{sanitize_terminal(self._extra)}\n", style="dim")
            return
        rule = "─" * max(20, min(66, int(width or 60) - 2))
        body.append(Text(rule + "\n", style=THEME_TOKENS["border"]))
        body.append("Update available\n")
        body.append(f"{current}\n")
        body.append("\nNew version available.\n", style="dim")
        if self._extra:
            body.append(f"{sanitize_terminal(self._extra)}\n", style="dim")
        body.append("\nPress u or pick Update below to install.\n")
        body.append(Text(rule + "\n", style=THEME_TOKENS["border"]))
        body.append("\nRecent activity\n", style="#72B7D3")
        self._recent_lines(body)

    def _recent_lines(self, body: Text) -> None:
        from trace_core.tui.theme import DOT_BAD, DOT_OK
        from trace_core.updates.service import UpdateService

        try:
            rows = UpdateService(self._manager).list_history(limit=3, offset=0)
        except Exception:
            return
        for row in rows:
            ok = str(row.result) == "SUCCESS"
            body.append("✓ " if ok else "✕ ", style=DOT_OK if ok else DOT_BAD)
            body.append(f"{row.from_version} → {row.to_version}    {row.result}\n", style="dim")

    def _install_lines(self, body: Text) -> None:
        from trace_core.tui.theme import stage_line
        from trace_core.updates.stages import STAGE_ACTIVE_LABEL, STAGE_DONE_LABEL, StageStatus

        prev = self._prev or "?"
        current = self._current or "?"
        body.append(f"Updating Trace v{prev} → v{current}\n")
        body.append("\n")
        for stage in STAGE_ORDER:
            status = self._install_state.get(stage, StageStatus.PENDING)
            if status == StageStatus.PENDING:
                continue
            if status == StageStatus.DONE:
                label = STAGE_DONE_LABEL[stage]
            elif status == StageStatus.FAILED:
                label = STAGE_DONE_LABEL[stage]
            else:
                label = STAGE_ACTIVE_LABEL[stage]
            body.append_text(stage_line(status.value, label))
            body.append("\n")

    def _integrity_body(self, body: Text, width: int) -> None:
        from trace_core.audit.service import AuditService
        from trace_core.tui.theme import DOT_BAD, DOT_OK

        _ = width
        svc = AuditService(self._manager)
        try:
            res = svc.verify()
        except Exception as exc:
            body.append(f"Version unavailable ({exc})", style="dim")
            return
        if res.is_valid:
            body.append("● ", style=DOT_OK)
            body.append("VALID · VERIFIED\n", style=f"bold {DOT_OK}")
            if res.first_seq:
                body.append("Chain Status       VERIFIED\n", style="dim")
                body.append(f"Events Checked     {res.events_verified}\n")
                body.append(f"Chain Breaks       {len(res.sequence_gaps)}\n")
            else:
                body.append("No audit events found\n", style="dim")
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
        body.append("\nSelected Event\n", style="#72B7D3")
        body.append(f"Seq {event.seq}  {event.subject_case_number}\n", style="dim")
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

    def _operator_body(self, body: Text, width: int) -> None:
        from trace_core.core.operators import current_identity
        from trace_core.core.settings import settings
        from trace_core.core.ui.renderers import sanitize_terminal

        _ = width
        user, host = current_identity()
        role = "—"
        try:
            from trace_core.core.database.session import db_manager

            mgr = self._manager or db_manager
            with mgr.session() as session:
                from trace_core.core.operators import current_operator

                role = current_operator(session).role
        except Exception:
            pass
        from trace_core.tui.theme import append_kv

        for label, value in (
            ("Operator", f"{user}@{host}"),
            ("Role", role),
            ("Env", settings.env),
            ("Version", settings.version),
        ):
            append_kv(body, label, sanitize_terminal(str(value)))

    def _diagnostics_body(self, body: Text, width: int) -> None:
        from trace_core.core.cli.doctor import _python_check, _storage_check
        from trace_core.core.database.health import fetch_db_snapshot

        _ = width
        checks: list[tuple[str, bool, str]] = []
        name, detail, passed = _python_check()
        checks.append((name, passed, detail))
        try:
            snap = fetch_db_snapshot(self._manager)
        except Exception as exc:
            checks.append(("Database", False, str(exc)))
            snap = None
        else:
            checks.append(("Database", snap.healthy, "Online" if snap.healthy else snap.message))
            if snap is not None and snap.healthy:
                if snap.pending:
                    checks.append(("Migrations", False, f"{len(snap.pending)} pending"))
                else:
                    checks.append(("Migrations", True, f"{len(snap.applied)} applied"))
        name, detail, passed = _storage_check()
        checks.append((name, passed, detail))
        for label, ok, detail in checks:
            body.append("● " if ok else "× ", style="#5FD18A" if ok else "#D06A73")
            body.append(f"{label:<12} ", style="bold")
            body.append(f"{'PASS' if ok else 'FAIL'}  {detail}\n", style="dim")

    def _about_body(self, body: Text, width: int) -> None:
        from trace_core.core.settings import settings
        from trace_core.core.ui.renderers import fit_text, sanitize_terminal
        from trace_core.tui.theme import append_kv

        for label, value in (
            ("Trace", f"v{settings.version}"),
            ("Channel", settings.update_channel),
            ("Manifest", settings.update_manifest or "—"),
        ):
            append_kv(body, label, sanitize_terminal(fit_text(str(value), max(20, width - 14))))
        body.append("\nOperational screens live here; Cases and Audit are unchanged.\n", style="dim")

    # --- actions ---

    def _check_text(self) -> tuple[str, str, str, str]:
        from trace_core.updates.checker import (
            cached_check,
            get_installed_version,
            resolve_channel,
            resolve_manifest_target,
        )

        channel = resolve_channel(None)
        try:
            target = resolve_manifest_target(None, channel)
        except Exception:
            return get_installed_version(), "—", "failed", "No update manifest configured (TRACE_UPDATE_MANIFEST)."
        payload = cached_check(target, channel)
        prev = str(payload.get("current") or get_installed_version())
        if not payload["available"]:
            return prev, prev, "current", ""
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

    def _maybe_refresh_hint(self) -> None:
        from textual.widgets import Static

        from trace_core.updates.checker import cached_check, resolve_channel, resolve_manifest_target

        try:
            channel = resolve_channel(None)
            target = resolve_manifest_target(None, channel)
        except Exception:
            return
        try:
            payload = cached_check(target, channel)
        except Exception:
            return
        if not payload["available"]:
            return
        try:
            self.app.query_one("#hint", Static).update(f"↑ Update {payload['target']} available")
        except Exception:
            pass

    def action_check(self) -> None:
        if self._selected_section() != "Updates":
            self.app.notify("Select Updates first.", severity="warning")
            return
        self._checking = True
        self._render_detail()
        try:
            prev, current, kind, extra = self._check_text()
        except Exception as exc:
            from trace_core.updates.checker import get_installed_version

            try:
                prev = get_installed_version()
            except Exception:
                prev = ""
            self._prev, self._current, self._kind, self._extra = prev, "—", "failed", str(exc)[:500]
            self.app.notify(str(exc)[:500], severity="error")
        else:
            self._prev, self._current, self._kind, self._extra = prev, current, kind, extra
        finally:
            self._checking = False
        self._render_detail()
        self._maybe_refresh_hint()

    def action_install(self) -> None:
        if self._selected_section() != "Updates":
            self.app.notify("Select Updates first.", severity="warning")
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
        self._render_detail()
        self.app.run_worker(self._install_worker())

    async def _install_worker(self) -> None:
        import asyncio
        import uuid

        from trace_core.updates.commands import prepare_install
        from trace_core.updates.lifecycle import UpdateLifecycle

        def sync_install():  # type: ignore[no-untyped-def]
            m, _target, _current, artifact_path, entry, channel = prepare_install(None, None)
            return UpdateLifecycle(str(uuid.uuid4())).run(
                m, artifact_path, channel=channel, preverified_sha256=entry.sha256, progress=_TuiProgress(self)
            )

        try:
            dto = await asyncio.to_thread(sync_install)
        except Exception as exc:
            self._installing = False
            self.app.notify(str(exc)[:300], severity="error")
            self.action_check()
            return
        self._installing = False
        self.app.notify(f"Trace updated to v{dto.to_version}.")
        self.action_check()

    def _on_update_stage(self, stage: Stage, status: StageStatus) -> None:
        try:
            self._install_state[stage] = status
            self._render_detail()
        except Exception:
            pass

    @on(Button.Pressed, "#update-apply")
    def _apply_pressed(self) -> None:
        self.action_install()

    def action_migrate(self) -> None:
        if self._selected_section() != "Database":
            self.app.notify("Select Database first.", severity="warning")
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
        if self._selected_section() != "Integrity":
            self.app.notify("Select Integrity first.", severity="warning")
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
