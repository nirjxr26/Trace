import asyncio
import threading
from uuid import UUID

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Rule, Static

from trace_core.cases.dto import CaseFilterDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.renderers import sanitize_terminal
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.devices.renderers import format_bytes
from trace_core.imaging.domain import ImagingOperation, ImagingState
from trace_core.imaging.service import ImagingService
from trace_core.tui.actions import run_guarded
from trace_core.tui.forms import CasePicker, TextInputModal, YesNoModal
from trace_core.tui.theme import SELECT_PREFIX, detail_placeholder
from trace_core.tui.widgets import DossierScroll, TablePane

TABLE_ID = "imaging-table"
HEADER_ID = "imaging-header"
DETAIL_ID = "imaging-dossier"
TABLE_COLUMNS = (("Case", 16), ("Status", 18), ("Size", 10), ("Source", 24))

_STATE_STYLE = {
    ImagingState.PREPARING: THEME_TOKENS["muted"],
    ImagingState.ACQUIRING: THEME_HEX["blue"],
    ImagingState.VERIFYING: THEME_HEX["amber"],
    ImagingState.BYTE_VERIFIED: THEME_HEX["green"],
    ImagingState.INTERRUPTED: THEME_HEX["amber"],
    ImagingState.FAILED: THEME_HEX["red"],
    ImagingState.QUARANTINED: THEME_HEX["red"],
}


class ImagingView(TablePane[ImagingOperation]):
    BINDINGS = [
        Binding("n", "reserve", "Reserve"),
        Binding("a", "acquire", "Acquire"),
        Binding("p", "acquire_physical", "Physical"),
        Binding("v", "verify", "Verify"),
        Binding("s", "seal", "Seal"),
        Binding("u", "unseal", "Unseal"),
        Binding("x", "cancel", "Cancel"),
        Binding("c", "change_case", "Case"),
        Binding("slash", "search", "Search"),
    ]

    TABLE_ID = TABLE_ID
    HEADER_ID = HEADER_ID
    DETAIL_ID = DETAIL_ID
    SEARCH_ID = "imaging-search"
    COLUMNS = TABLE_COLUMNS

    def __init__(self, session_manager: DatabaseSessionManager | None = None) -> None:
        super().__init__()
        self._manager = session_manager
        self._case_number: str | None = None
        self._cancel: threading.Event | None = None
        self._progress: tuple[int, int] | None = None

    @property
    def _service(self) -> ImagingService:
        return ImagingService(self._manager)

    def compose(self):  # type: ignore[no-untyped-def]
        with Horizontal(id="imaging-top"):
            with Vertical(id="imaging-left"):
                yield Input(placeholder="Search case, node, serial...", id="imaging-search")
                yield Static("", id=HEADER_ID, classes="table-head")
                yield Rule()
                yield DataTable(id=TABLE_ID, cursor_type="row", show_header=False)
            with DossierScroll(id="imaging-right"):
                yield Static("Select an operation…", id=DETAIL_ID)

    def on_mount(self) -> None:
        super().on_mount()

    def on_unmount(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self.workers.cancel_group(self, "imaging")
        super().on_unmount()

    def set_case(self, case_number: str) -> None:
        self._case_number = case_number
        self._items = []
        self._keys = []
        self.refresh_data()

    def focus_default(self) -> None:
        self._table().focus()

    def displayed_count(self) -> int:
        return len(self._items)

    def refresh_data(self) -> None:
        try:
            operations = (
                self._service.list_for_case(self._case_number) if self._case_number else self._service.list_recent()
            )
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
            return
        query = self.query_one("#imaging-search", Input).value.strip().lower()
        if query:
            operations = [
                operation
                for operation in operations
                if query in operation.case_number.lower()
                or query in (operation.source_node or "").lower()
                or query in (operation.source_serial or "").lower()
                or query in str(operation.id)
            ]
        self.fill_table(operations, [str(operation.id) for operation in operations])

    def row_cells(self, operation: ImagingOperation, selected: bool) -> list[str]:  # type: ignore[no-untyped-def]
        prefix = SELECT_PREFIX if selected else "  "
        state = operation.state.value.replace("_", " ").title()
        size = format_bytes(operation.source_size_bytes or operation.expected_bytes)
        source = operation.source_model or operation.source_node or "—"
        return [
            f"{prefix}{operation.case_number}",
            state,
            size,
            sanitize_terminal(source),
        ]

    def _selected_operation(self) -> ImagingOperation | None:
        return self._selected()

    def render_detail(self) -> None:
        operation = self._selected_operation()
        if operation is None:
            self.query_one(f"#{DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No imaging operations.")
            )
            return
        state = operation.state.value.replace("_", " ").title()
        body = Text()
        self._append_dossier_line(body, "Case", operation.case_number)
        self._append_dossier_line(body, "Status", state, _STATE_STYLE.get(operation.state, THEME_HEX["value"]))
        if self._progress is not None:
            done, total = self._progress
            percent = done * 100 // total if total else 0
            self._append_dossier_line(body, "Progress", f"{percent}% · {format_bytes(done)}/{format_bytes(total)}")
        self.query_one(f"#{DETAIL_ID}", Static).update(body)

    @staticmethod
    def _append_dossier_line(body: Text, label: str, value: str, style: str = "") -> None:
        body.append(f"{label:<10}", style="dim")
        body.append(f"{sanitize_terminal(value)}\n", style=style)

    def action_change_case(self) -> None:
        def _load(term: str) -> list[tuple[str, str]]:
            cases = CaseService(self._manager).list_cases(
                CaseFilterDto(search=term or None, include_deleted=True, limit=100)
            )
            return [(case.number, case.title) for case in cases]

        self.app.push_screen(CasePicker(_load, title="Choose case for imaging"), self._case_chosen)

    def _case_chosen(self, number: str | None) -> None:
        if number:
            self.set_case(number)

    def action_reserve(self) -> None:
        if not self._case_number:
            self.action_change_case()
            self.app.notify("Choose a case first, then press n.", severity="warning")
            return
        self._reserve_for(self._case_number)

    def _reserve_for(self, case_number: str) -> None:
        def _reserve() -> str:
            self._service.reserve(case_number)
            return "Imaging reservation created."

        run_guarded(self, _reserve)

    def action_acquire(self) -> None:
        self._begin_acquisition(physical=False)

    def action_acquire_physical(self) -> None:
        self._begin_acquisition(physical=True)

    def _begin_acquisition(self, *, physical: bool) -> None:
        operation = self._selected_operation()
        if operation is None:
            self.app.notify("Select an imaging operation first.", severity="warning")
            return
        if operation.state not in {ImagingState.PREPARING, ImagingState.INTERRUPTED}:
            self.app.notify("Only a reservation or an interrupted image can be acquired.", severity="warning")
            return
        title = "Physical device node" if physical else "Fixture source path"
        hint = "device node, e.g. \\\\.\\PhysicalDrive1" if physical else "file to acquire"
        self.app.push_screen(
            TextInputModal(title, hint, required=True),
            lambda path: self._start_acquisition(operation.id, path, physical=physical),
        )

    def _start_acquisition(self, operation_id: UUID, path: str | None, *, physical: bool) -> None:
        if not path:
            return
        self._cancel = threading.Event()
        self.run_worker(
            self._acquire_worker(operation_id, path, physical, self._cancel),
            name="imaging-acquire",
            group="imaging",
            exclusive=True,
        )

    async def _acquire_worker(self, operation_id: UUID, path: str, physical: bool, cancel: threading.Event) -> None:
        import time as _time

        last = [0.0]

        def _progress(done: int, total: int) -> None:
            now = _time.monotonic()
            if now - last[0] < 0.25 and done != total:
                return
            last[0] = now
            self.app.call_from_thread(self._update_progress, done, total)

        try:
            operation = await asyncio.to_thread(
                self._service.acquire,
                operation_id,
                path,
                allow_real_hardware=physical,
                progress=_progress,
                cancelled=cancel.is_set,
            )
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
        else:
            self.app.notify("Image byte-verified.")
            if operation.case_number:
                self._case_number = operation.case_number
        finally:
            self._cancel = None
            self._clear_progress()
            self.refresh_data()

    def _update_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)
        self.render_detail()

    def _clear_progress(self) -> None:
        self._progress = None
        self.render_detail()

    def action_verify(self) -> None:
        operation = self._selected_operation()
        if operation is None or operation.state is not ImagingState.BYTE_VERIFIED:
            self.app.notify("Select a byte-verified image first.", severity="warning")
            return
        self.run_worker(self._verify_worker(operation.id), name="imaging-verify", group="imaging", exclusive=True)

    async def _verify_worker(self, operation_id: UUID) -> None:
        try:
            matches = await asyncio.to_thread(self._service.verify_image, operation_id)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
        else:
            if matches:
                self.app.notify("Image matches its manifest.")
            else:
                self.app.notify("Image FAILED verification.", severity="error")

    def action_seal(self) -> None:
        operation = self._selected_operation()
        if operation is None or operation.state is not ImagingState.BYTE_VERIFIED:
            self.app.notify("Select a byte-verified image first.", severity="warning")
            return
        self.app.push_screen(
            TextInputModal("Seal passphrase", "passphrase", required=True, password=True, confirm=True),
            lambda passphrase: self._seal(operation.id, passphrase),
        )

    def _seal(self, operation_id: UUID, passphrase: str | None) -> None:
        if not passphrase:
            return
        self.run_worker(
            self._seal_worker(operation_id, passphrase), name="imaging-seal", group="imaging", exclusive=True
        )

    async def _seal_worker(self, operation_id: UUID, passphrase: str) -> None:
        try:
            await asyncio.to_thread(self._service.seal_image, operation_id, passphrase)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
        else:
            self.app.notify("Image sealed.")
        self.refresh_data()

    def action_unseal(self) -> None:
        operation = self._selected_operation()
        if operation is None or operation.state is not ImagingState.BYTE_VERIFIED:
            self.app.notify("Select a byte-verified image first.", severity="warning")
            return
        self.app.push_screen(
            TextInputModal("Unseal output path", "where to write the raw image", required=True),
            lambda out: self._ask_unseal_passphrase(operation.id, out),
        )

    def _ask_unseal_passphrase(self, operation_id: UUID, out: str | None) -> None:
        if not out:
            return
        self.app.push_screen(
            TextInputModal("Unseal passphrase", "passphrase", required=True, password=True),
            lambda passphrase: self._unseal(operation_id, out, passphrase),
        )

    def _unseal(self, operation_id: UUID, out: str, passphrase: str | None) -> None:
        if not passphrase:
            return
        self.run_worker(
            self._unseal_worker(operation_id, out, passphrase),
            name="imaging-unseal",
            group="imaging",
            exclusive=True,
        )

    async def _unseal_worker(self, operation_id: UUID, out: str, passphrase: str) -> None:
        try:
            path = await asyncio.to_thread(self._service.open_sealed_image, operation_id, passphrase, out)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
        else:
            self.app.notify(f"Image unsealed and verified: {path}.")

    def action_cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self.app.notify("Cancellation requested; partial image kept for resume.")
            return
        operation = self._selected_operation()
        if operation is None or operation.state not in {ImagingState.PREPARING, ImagingState.INTERRUPTED}:
            self.app.notify("No cancelable imaging operation.", severity="warning")
            return
        self.app.push_screen(
            YesNoModal("Abandon this imaging operation?"),
            lambda ok: self._abandon(operation.id) if ok else None,
        )

    def _abandon(self, operation_id: UUID) -> None:
        def _run() -> str:
            self._service.abandon(operation_id)
            return "Imaging operation abandoned."

        run_guarded(self, _run)

    def run_command(self, command: str) -> None:
        actions = {
            "imaging-reserve": self.action_reserve,
            "imaging-acquire": self.action_acquire,
            "imaging-acquire-physical": self.action_acquire_physical,
            "imaging-verify": self.action_verify,
            "imaging-seal": self.action_seal,
            "imaging-unseal": self.action_unseal,
            "imaging-change-case": self.action_change_case,
        }
        action = actions.get(command)
        if action is not None:
            action()
