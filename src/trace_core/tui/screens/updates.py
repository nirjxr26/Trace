from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.updates.service import UpdateService

UPDATES_DETAIL_SELECTOR = "#updates-detail"
UPDATES_STATUS_SELECTOR = "#updates-status"


class UpdatesView(Vertical):
    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager

    def focus_default(self) -> None:
        self.query_one("#updates-check", Button).focus()

    def compose(self) -> ComposeResult:
        yield Static("Updates", classes="card-title")
        yield Static("No updates checked yet.", id="updates-status")
        yield Button("Check", id="updates-check")
        yield Static("", id="updates-detail")

    def refresh_data(self) -> None:
        from trace_core.core.ui.renderers import sanitize_terminal

        svc = UpdateService(self._manager)
        marker = svc.read_result_marker()
        if marker:
            prev = marker.get("previous_version") or "unknown"
            target = marker.get("target_version") or "unknown"
            lines = [
                f"{prev} → {target}",
                f"result: {marker.get('result') or '—'}",
                f"release: {marker.get('release_id') or '—'}",
                f"migration: {marker.get('migration_range') or '—'}",
                f"health: {marker.get('health_check_result') or '—'}",
            ]
            self.query_one(UPDATES_DETAIL_SELECTOR, Static).update(sanitize_terminal("\n".join(lines)))
            self.query_one(UPDATES_STATUS_SELECTOR, Static).update(sanitize_terminal(f"{prev} → {target}"))
            return
        history = svc.list_history(limit=5)
        if history:
            rows = [f"{h.from_version} → {h.to_version} ({h.result})" for h in history]
            self.query_one(UPDATES_DETAIL_SELECTOR, Static).update(sanitize_terminal("\n".join(rows)))
            self.query_one(UPDATES_STATUS_SELECTOR, Static).update(f"{len(history)} update(s) recorded")
        self._maybe_refresh_hint()

    def _maybe_refresh_hint(self) -> None:
        # Sync by design: Textual calls refresh_data on the UI thread.
        # cached_check is ETag-cached (1 h) so repeat polls are local reads;
        # first remote fetch is bounded by HttpManifestSource timeout + 3 retries.
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
        pill = f"● Update {payload['target']} available"
        try:
            self.app.query_one("#hint", Static).update(pill)
        except Exception:
            pass

    def _check_text(self) -> str:
        from trace_core.updates.checker import cached_check, resolve_channel, resolve_manifest_target

        channel = resolve_channel(None)
        try:
            target = resolve_manifest_target(None, channel)
        except Exception:
            return "No update manifest configured (TRACE_UPDATE_MANIFEST)."
        payload = cached_check(target, channel)
        if not payload["available"]:
            return f"Up to date ({payload['current']}, {channel})."
        lines = [f"{payload['target']} available (current {payload['current']}, {channel})"]
        if payload["security_update"]:
            lines.append("Security update")
        if payload["minimum_supported_version"]:
            lines.append(f"Minimum supported version: {payload['minimum_supported_version']}")
        if payload["restart_required"]:
            lines.append("Trace will restart to complete this update.")
        if not payload["installable"]:
            lines.append(f"Deferred: {payload['block_reason']}")
        return "\n".join(lines)

    @on(Button.Pressed, "#updates-check")
    def _check_pressed(self) -> None:
        from trace_core.core.ui.renderers import sanitize_terminal

        try:
            text = self._check_text()
        except Exception as exc:
            self.app.notify(str(exc)[:500], severity="error")
            return
        self.query_one(UPDATES_DETAIL_SELECTOR, Static).update(sanitize_terminal(text))
        self.query_one(UPDATES_STATUS_SELECTOR, Static).update(sanitize_terminal(text.splitlines()[0]))
        self._maybe_refresh_hint()

    def run_command(self, command: str) -> None:
        if command == "check":
            self._check_pressed()
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")
