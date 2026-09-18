"""Integrity tab: chain confidence at a glance. Verdict first, numbers after."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static

from trace_core.audit.anchor import verify_against_anchor
from trace_core.audit.dto import VerifyResultDto
from trace_core.audit.service import AuditService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.tui.actions import confirm_overwrite, run_guarded

ANCHOR_INPUT = "verify-anchor"
EXPORT_INPUT = "verify-out"
VERIFY_RESULT = "verify-result"


class VerifyView(Vertical):
    """Big verdict, then the numbers. Anchor picker + export, no flags to memorize."""

    BINDINGS = [
        Binding("a", "anchor", "Anchor file"),
        Binding("e", "export", "Export"),
    ]

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._anchor: str | None = None
        self._last_key: tuple | None = None
        self._last_verdict: Text | None = None

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll

        with VerticalScroll(id="integrity-scroll"):
            with Vertical(id="integrity-status", classes="card"):
                yield Static("Chain status", classes="card-title")
                yield Static("Checking…", id=VERIFY_RESULT)
            with Vertical(id="integrity-anchor", classes="card"):
                yield Static("Anchor check", classes="card-title")
                yield Static("Compare the live tip against an off-host anchor file.", classes="muted")
                with Horizontal(classes="input-row"):
                    yield Input(placeholder="anchor file (optional)…", id=ANCHOR_INPUT)
                    yield Button("Verify", variant="primary", id="verify-run")
            with Vertical(id="integrity-export", classes="card"):
                yield Static("Export bundle", classes="card-title")
                yield Static("Header + JSONL, offline-verifiable. Copy it off-host.", classes="muted")
                with Horizontal(classes="input-row"):
                    yield Input(placeholder="export bundle to…", id=EXPORT_INPUT)
                    yield Button("Export", id="verify-export")

    def on_mount(self) -> None:
        self.refresh_data()

    def focus_default(self) -> None:
        """Focus the anchor input. Called by the shell when this tab activates."""
        self.query_one(f"#{ANCHOR_INPUT}", Input).focus()

    def refresh_data(self) -> None:
        """Re-run verification. Called on mount and tab switch."""
        self._run_verify()

    def _run_verify(self) -> None:
        svc = AuditService(self._manager)
        try:
            head = svc.head()
            key = (head[0], head[1], self._anchor)
            if key == self._last_key and self._last_verdict is not None:
                # Ledger tip unchanged: full rescan would recompute the same verdict.
                self.query_one(f"#{VERIFY_RESULT}", Static).update(self._last_verdict)
                return
            res = svc.verify()
            if self._anchor:
                verify_against_anchor(svc, res, self._anchor)
        except Exception as exc:  # boundary: every service failure becomes a toast, never a crash
            self.query_one(f"#{VERIFY_RESULT}", Static).update(Text(str(exc), style="#D06A73"))
            return
        self._last_key, self._last_verdict = key, self._verdict(res)
        self.query_one(f"#{VERIFY_RESULT}", Static).update(self._last_verdict)

    @staticmethod
    def _verdict(res: VerifyResultDto) -> Text:
        body = Text()
        if res.is_valid:
            body.append("✓ VALID\n", style="bold #5FD18A")
            body.append(
                f"{res.events_verified} events · seq {res.first_seq} → {res.last_seq}\n"
                if res.first_seq
                else "Empty ledger — nothing to check.\n"
            )
            gaps = ", ".join(str(g) for g in res.sequence_gaps) if res.sequence_gaps else "none"
            body.append(f"Gaps: {gaps}\n", style="dim")
        else:
            body.append("✗ TAMPER DETECTED\n", style="bold #D06A73")
            body.append(f"First mismatch at seq {res.first_mismatch_seq} ({res.mismatch_type}).\n")
        return body

    def run_command(self, command: str) -> None:
        """Entry for the palette."""
        if command == "anchor":
            self.action_anchor()
        elif command == "export":
            self.query_one(f"#{EXPORT_INPUT}", Input).focus()
        else:
            self.app.notify(f"Command '{command}' is not available on this tab.", severity="warning")

    def action_anchor(self) -> None:
        self.query_one(f"#{ANCHOR_INPUT}", Input).focus()

    def action_export(self) -> None:
        self.query_one(f"#{EXPORT_INPUT}", Input).focus()

    @on(Button.Pressed, "#verify-run")
    @on(Input.Submitted, f"#{ANCHOR_INPUT}")
    def _verify_pressed(self) -> None:
        path = self.query_one(f"#{ANCHOR_INPUT}", Input).value.strip() or None
        self._anchor = path
        self._run_verify()

    @on(Button.Pressed, "#verify-export")
    @on(Input.Submitted, f"#{EXPORT_INPUT}")
    def _export_pressed(self) -> None:
        path = self.query_one(f"#{EXPORT_INPUT}", Input).value.strip()
        if not path:
            self.app.notify("Enter an export path first.", severity="warning")
            return
        confirm_overwrite(self, path, lambda: self._do_export(path))

    def _do_export(self, path: str) -> None:
        def _export() -> str:
            out = AuditService(self._manager).export(path)
            return f"Exported to {out}. Copy it off-host."

        run_guarded(self, _export)
