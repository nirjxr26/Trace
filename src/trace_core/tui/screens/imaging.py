import asyncio
import threading
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.notifications import SeverityLevel
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static

from trace_core.cases.dto import CaseFilterDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.devices.renderers import format_bytes
from trace_core.imaging.domain import ImagingInterruptedError, ImagingOperation, ImagingSourceKind, ImagingState
from trace_core.imaging.service import ImagingService
from trace_core.tui.actions import run_guarded
from trace_core.tui.design.text import kv_row, section_head
from trace_core.tui.design.tokens import LABEL_LG, STAGE_TONES
from trace_core.tui.design.widgets import ListDetailPane, ModalFrame, SegmentedProgress
from trace_core.tui.forms import CasePicker, TextInputModal, YesNoModal, _BaseModal
from trace_core.tui.theme import SELECT_PREFIX, detail_placeholder
from trace_core.tui.widgets import TablePane

TABLE_ID = "imaging-table"
HEADER_ID = "imaging-header"
DETAIL_ID = "imaging-dossier"
TABLE_COLUMNS = (("Case", 14), ("Status", 12))
UTC_TIMESTAMP_FORMAT = "%d %b %Y, %H:%M UTC"
BYTE_VERIFIED_REQUIRED = "Select a byte-verified image first."

_STATE_STYLE = {
    ImagingState.PREPARING: THEME_TOKENS["muted"],
    ImagingState.ACQUIRING: THEME_HEX["blue"],
    ImagingState.VERIFYING: THEME_HEX["amber"],
    ImagingState.BYTE_VERIFIED: THEME_HEX["green"],
    ImagingState.INTERRUPTED: THEME_HEX["amber"],
    ImagingState.FAILED: THEME_HEX["red"],
    ImagingState.QUARANTINED: THEME_HEX["red"],
}


class ImagingProgressModal(_BaseModal):
    """Closeable progress popup. Closing it never cancels the acquisition."""

    CSS = """
    ImagingProgressModal { align: center middle; }
    #progress-box { width: 78; max-width: 100%; height: auto; border: none; background: $surface-elevated; padding: 0; }
    #progress-head { height: auto; align: center middle; background: $form-bg; padding: 1 3; }
    #progress-title { width: 1fr; height: 1; color: $accent; text-style: bold; }
    #progress-esc { width: auto; height: 1; color: $muted; text-align: right; }
    #progress-software { height: 1; color: $warning; text-style: bold; }
    .progress-body { height: auto; padding: 1 3 1 3; }
    #progress-device { height: 1; color: $text; text-style: bold; text-wrap: nowrap; }
    #progress-case { height: 1; color: $accent; }
    #progress-bytes { height: 1; color: $text; text-style: bold; text-wrap: nowrap; margin-top: 1; }
    #progress-track { height: 1; align: center middle; margin-top: 1; }
    #progress-bar { width: 44; height: 1; }
    #progress-status { width: auto; height: 1; color: $muted; margin-left: 2; text-align: left; }
    #progress-metrics { height: 3; margin-top: 1; }
    .metric { width: 1fr; }
    .metric-label { height: 1; color: $muted; }
    .metric-value { height: 1; color: $text; }
    #progress-destination-label { height: 1; color: $muted; }
    #progress-destination { height: 1; color: $text; }
    #progress-note { height: auto; color: $muted; margin-top: 1; }
    """

    def __init__(
        self,
        preview: bool = False,
        *,
        device: str = "—",
        case: str = "—",
        destination: str = "—",
        stage: str = "acquiring",
        software_only: bool = False,
    ) -> None:
        super().__init__()
        self._preview = preview
        self._device = device
        self._case = case
        self._destination = destination
        self._stage = stage
        self._software_only = software_only
        self._note = ""
        self._timer: Timer | None = None
        self._done = 0
        self._total = 0
        self._started = monotonic()
        self._preview_target = 4_992_899_481
        self._preview_total = 8_053_063_680

    def compose(self) -> ComposeResult:
        with ModalFrame(widget_id="progress-box", elevated=True):
            with Horizontal(id="progress-head"):
                yield Static("Evidence Acquisition", id="progress-title")
                yield Static("Esc", id="progress-esc")
            with Vertical(id="progress-body", classes="progress-body"):
                if self._software_only:
                    yield Static("SOFTWARE-ONLY · NOT EVIDENTIARY", id="progress-software")
                yield Static(self._device, id="progress-device")
                yield Static(self._case, id="progress-case")
                yield Static("", id="progress-bytes")
                with Horizontal(id="progress-track"):
                    yield SegmentedProgress(id="progress-bar")
                    yield Static("", id="progress-status")
                with Horizontal(id="progress-metrics"):
                    for label, value_id in (
                        ("Read Speed", "progress-speed"),
                        ("Elapsed", "progress-elapsed"),
                        ("Bad regions", "progress-bad"),
                    ):
                        with Vertical(classes="metric"):
                            yield Static(label, classes="metric-label")
                            yield Static("—", id=value_id, classes="metric-value")
                yield Static("Destination", id="progress-destination-label")
                yield Static(self._destination, id="progress-destination")
                yield Static("", id="progress-note")

    def on_mount(self) -> None:
        self.query_one("#progress-note", Static).display = False
        self.update_progress(0, self._preview_total if self._preview else 1)
        if self._preview:
            self._timer = self.set_interval(0.02, self._preview_tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _preview_tick(self) -> None:
        step = self._preview_target / 60
        done = min(self._preview_target, self._done + step)
        self.update_progress(int(done), self._preview_total)
        if done >= self._preview_target and self._timer is not None:
            self._timer.stop()
            self._timer = None

    def set_stage(self, stage: str, note: str = "") -> None:
        self._stage = stage if stage in STAGE_TONES else "acquiring"
        self._note = note
        note_widget = self.query_one("#progress-note", Static)
        note_widget.update(note)
        note_widget.display = bool(note)
        self.update_progress(self._done, self._total)

    def update_progress(self, done: int, total: int) -> None:
        self._done = done
        self._total = total
        elapsed = max(0, int(monotonic() - self._started))
        if self._preview:
            ratio = min(1.0, done / self._preview_target) if self._preview_target else 0.0
            elapsed = round(38 * ratio)
            eta = round(62 - 38 * ratio)
            speed = "124 MB/s"
            bad = "0"
        else:
            rate = done / elapsed if elapsed > 0 else 0.0
            speed = f"{format_bytes(int(rate))}/s" if rate > 0 else "—"
            eta = int(max(0, total - done) / rate) if rate > 0 else 0
            bad = "—"
        percent = round(done * 100 / total) if total else 0
        status = {
            "preflight": "0% | checking",
            "verifying": f"{percent}% | verifying",
            "success": "100% | verified",
            "sealed": "100% | sealed",
            "failed": f"{percent}% | failed",
            "cancelled": f"{percent}% | stopped",
            "quarantined": f"{percent}% | quarantined",
        }.get(self._stage, f"{percent}% | ETA: {eta}s")
        color = STAGE_TONES.get(self._stage, STAGE_TONES["acquiring"])
        self.query_one("#progress-bytes", Static).update(f"{format_bytes(done)} / {format_bytes(total)}")
        self.query_one("#progress-bar", SegmentedProgress).set_progress(done / total if total else 0.0, color)
        status_widget = self.query_one("#progress-status", Static)
        status_widget.update(status)
        status_widget.styles.color = color
        self.query_one("#progress-elapsed", Static).update(f"{elapsed // 60:02d}:{elapsed % 60:02d}")
        self.query_one("#progress-speed", Static).update(speed)
        self.query_one("#progress-bad", Static).update(bad)


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
        Binding("ctrl+d", "toggle_preview", "Preview data", show=False),
        Binding("ctrl+a", "toggle_advanced", "Advanced details", show=False),
        Binding("ctrl+g", "preview_progress", "Progress popup preview", show=False),
        Binding("alt+s", "acquire_software", "Software-block acquire", show=False),
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
        self._progress_modal: ImagingProgressModal | None = None
        self._active_token: object | None = None
        self._closing = False
        self._preview = False
        self._advanced = False

    @property
    def _service(self) -> ImagingService:
        return ImagingService(self._manager)

    def compose(self):  # type: ignore[no-untyped-def]
        yield ListDetailPane(
            top_id="imaging-top",
            left_id="imaging-left",
            right_id="imaging-right",
            detail_id=DETAIL_ID,
            detail_text="Select an operation…",
            search_id="imaging-search",
            search_placeholder="Search case, node, serial...",
            header_id=HEADER_ID,
            table_factory=lambda: DataTable(id=TABLE_ID, cursor_type="row", show_header=False, classes="pane-table"),
        )

    def on_mount(self) -> None:
        super().on_mount()

    def on_unmount(self) -> None:
        self._closing = True
        if self._cancel is not None:
            self._cancel.set()
        self.workers.cancel_group(self, "imaging")
        self.workers.cancel_group(self, "imaging-actions")
        super().on_unmount()

    def _safe_refresh(self) -> None:
        if not self._closing and self.is_mounted:
            self.refresh_data()

    def _safe_render(self) -> None:
        if not self._closing and self.is_mounted:
            self.render_detail()

    def set_case(self, case_number: str) -> None:
        self._case_number = case_number
        self._preview = False
        self._progress = None
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
        return [
            f"{prefix}{operation.case_number}",
            state,
        ]

    def _selected_operation(self) -> ImagingOperation | None:
        return self._selected()

    def render_detail(self) -> None:
        operation = self._selected_operation()
        if operation is None and not self._preview:
            self.query_one(f"#{DETAIL_ID}", Static).update(
                detail_placeholder(bool(self._items), "No imaging operations.")
            )
            return
        body = Text()
        if self._preview:
            sample = self._sample_operation()
            body.append("SAMPLE — NOT EVIDENCE\n", style=f"bold {THEME_HEX['amber']}")
            self._append_full_dossier(body, sample, self._sample_manifest(), None, self._advanced)
        else:
            assert operation is not None
            self._append_full_dossier(
                body, operation, self._manifest_for_render(operation, False), self._progress, self._advanced
            )
        body.append(
            f"\nCtrl+A — {'collapse' if self._advanced else 'expand'} advanced details\n",
            style="dim",
        )
        self.query_one(f"#{DETAIL_ID}", Static).update(body)

    def action_toggle_preview(self) -> None:
        self._preview = not self._preview
        self.render_detail()

    def action_toggle_advanced(self) -> None:
        self._advanced = not self._advanced
        self.render_detail()

    @staticmethod
    def _sample_operation() -> ImagingOperation:
        digest = "9f2c1a7b4e6d5830f1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708"
        when = datetime(2026, 11, 21, 9, 15, tzinfo=UTC)
        return ImagingOperation(
            id=UUID("c68aac89-bd30-4c73-91ca-4d878e09c370"),
            case_id=UUID("21b9a1c2-3d4e-4f50-8a61-7b2c3d4e5f60"),
            case_number="2026-CR-0001",
            state=ImagingState.BYTE_VERIFIED,
            created_at=when,
            created_by="examiner@trace.local",
            updated_at=when,
            source_node="\\\\.\\PhysicalDrive1",
            source_kind=ImagingSourceKind.OS,
            source_serial="4C530001234567891234",
            source_model="SanDisk Cruzer Blade",
            source_size_bytes=8_000_000_000,
            source_protection="READ_ONLY (hardware blocker)",
            source_adapter="win32",
            source_inspected_at=when,
            expected_bytes=8_000_000_000,
            copied_bytes=7_812_345_678,
            acquisition_sha256=digest,
            readback_sha256=digest,
            image_relpath="cases/2026-CR-0001/imaging/sample/image.raw",
            manifest_relpath="cases/2026-CR-0001/imaging/sample/manifest.json",
            started_at=when,
            finished_at=datetime(2026, 11, 21, 9, 18, 42, tzinfo=UTC),
        )

    @staticmethod
    def _sample_manifest() -> dict[str, object]:
        digest = "9f2c1a7b4e6d5830f1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708"
        return {
            "manifest_version": "trace-imaging-manifest-v1",
            "format": "RAW",
            "byte_integrity": "verified",
            "tool_version": "0.4.0",
            "expected_bytes": 8_000_000_000,
            "copied_bytes": 7_812_345_678,
            "acquisition_sha256": digest,
            "readback_sha256": digest,
            "image_relpath": "cases/2026-CR-0001/imaging/sample/image.raw",
            "created_at": "2026-11-21T09:18:42+00:00",
            "finished_at": "2026-11-21T09:18:42+00:00",
            "piecewise": {
                "algorithm": "SHA-256",
                "chunk_size": 4_194_304,
                "count": 1908,
                "hashes": [digest, digest],
            },
            "bad_regions": [{"offset": 2_145_677_312, "length": 512, "cause": "SOURCE_READ_FAILED"}],
            "encryption": {
                "algorithm": "AES-256-GCM/PBKDF2-SHA256-600k",
                "sealed_relpath": "cases/2026-CR-0001/imaging/sample/image.raw.enc",
                "plaintext_sha256": digest,
                "sealed_size_bytes": 7_812_346_192,
            },
            "limitations": [
                "Byte verification proves only that the destination matches the bytes returned by the source reader.",
                "It does not prove source authenticity, physical write protection, or admissibility.",
            ],
        }

    def _append_full_dossier(
        self,
        body: Text,
        operation: ImagingOperation,
        manifest: dict[str, object],
        progress: tuple[int, int] | None,
        advanced: bool,
    ) -> None:
        expected = operation.expected_bytes or 0
        copied = operation.copied_bytes or 0
        bad = manifest.get("bad_regions")
        bad_regions = [region for region in bad if isinstance(region, dict)] if isinstance(bad, list) else []
        zero_filled = sum(int(region.get("length", 0)) for region in bad_regions)
        piece_raw = manifest.get("piecewise")
        piece = piece_raw if isinstance(piece_raw, dict) else {}
        encryption_raw = manifest.get("encryption")
        encryption = encryption_raw if isinstance(encryption_raw, dict) else {}
        digest = str(manifest.get("acquisition_sha256") or operation.acquisition_sha256 or "")
        readback = str(manifest.get("readback_sha256") or operation.readback_sha256 or "")
        verified = bool(digest and readback and digest == readback and operation.state is ImagingState.BYTE_VERIFIED)
        image_path = str(manifest.get("image_relpath") or operation.image_relpath or "")
        manifest_path = operation.manifest_relpath or ""
        sealed = str(encryption.get("sealed_relpath", ""))
        stopped = operation.finished_at.strftime(UTC_TIMESTAMP_FORMAT) if operation.finished_at else "—"

        self._dossier_header(
            body,
            operation,
            manifest,
            progress,
            expected,
            copied,
            bad_regions,
            digest,
            readback,
            verified,
            stopped,
        )
        self._dossier_source(body, operation, manifest)
        self._dossier_results(body, copied, expected, zero_filled, bad_regions)
        self._dossier_artifacts(body, image_path, manifest_path, sealed, encryption)
        if advanced:
            self._dossier_advanced(
                body,
                operation,
                manifest,
                piece,
                encryption,
                digest,
                readback,
                verified,
                image_path,
                manifest_path,
                sealed,
                stopped,
            )

    def _dossier_header(
        self,
        body: Text,
        operation: ImagingOperation,
        manifest: dict[str, object],
        progress: tuple[int, int] | None,
        expected: int,
        copied: int,
        bad_regions: list[dict],
        digest: str,
        readback: str,
        verified: bool,
        stopped: str,
    ) -> None:
        completion = copied * 100 / expected if expected else 0.0
        verdict = "MATCH REPORTED" if verified else "MISMATCH REPORTED"
        verdict_style = THEME_HEX["green"] if verified else THEME_HEX["red"]
        complete = operation.state is ImagingState.BYTE_VERIFIED and copied == expected and not bad_regions
        limit_reached = "Acquisition limit reached" if copied < expected else "—"
        if operation.failure_category:
            termination = operation.failure_category.value.replace("_", " ").title()
        else:
            termination = limit_reached

        body.append(f"{operation.source_model or '—'}\n", style=f"bold {THEME_HEX['title']}")
        body.append(f"RAW acquisition · {operation.case_number}\n\n", style=THEME_TOKENS["accent"])
        body.append(
            "COMPLETE" if complete else "PARTIAL",
            style=f"bold {THEME_HEX['green'] if complete else THEME_HEX['amber']}",
        )
        body.append(f" · {verdict}   ", style=f"bold {verdict_style}")
        body.append(f"{completion:.2f}%\n\n", style=f"bold {THEME_HEX['title']}")
        if progress is not None:
            done, total = progress
            percent = done * 100 // total if total else 0
            body.append(f"Progress {percent}% · {format_bytes(done)}/{format_bytes(total)}\n\n", style="dim")
        section_head(body, "ACQUISITION DETAILS")
        kv_row(body, "Format", str(manifest.get("format", "RAW")), LABEL_LG)
        kv_row(body, "Acquisition ID", str(operation.id), LABEL_LG)
        kv_row(body, "Examiner", operation.created_by, LABEL_LG)
        kv_row(
            body,
            "Started",
            operation.started_at.strftime(UTC_TIMESTAMP_FORMAT) if operation.started_at else "",
            LABEL_LG,
        )
        kv_row(body, "Stopped", stopped, LABEL_LG)
        kv_row(body, "Termination", termination, LABEL_LG)

    def _dossier_source(self, body: Text, operation: ImagingOperation, manifest: dict[str, object]) -> None:
        section_head(body, "SOURCE EVIDENCE")
        kv_row(body, "Device", operation.source_node or "", LABEL_LG)
        kv_row(body, "Serial", operation.source_serial or "", LABEL_LG)
        kv_row(body, "Capacity", f"{(operation.source_size_bytes or 0):,} bytes", LABEL_LG)
        kv_row(body, "Write protection", operation.source_protection or "", LABEL_LG)
        evidence_class = str(manifest.get("evidence_class") or "")
        limitations_raw = manifest.get("limitations")
        limitations = limitations_raw if isinstance(limitations_raw, list) else []
        limitations_text = " ".join(str(item) for item in limitations if isinstance(item, str))
        software_only = evidence_class == "SOFTWARE_ONLY" or "SOFTWARE-ONLY · NOT EVIDENTIARY" in limitations_text
        kv_row(
            body,
            "Evidence class",
            evidence_class or ("SOFTWARE_ONLY" if software_only else "UNCLASSIFIED"),
            LABEL_LG,
        )
        if software_only:
            body.append("\nSOFTWARE-ONLY · NOT EVIDENTIARY\n\n", style=f"bold {THEME_HEX['red']}")
        elif evidence_class == "UNVERIFIED_WRITE_PROTECTION":
            body.append("\nUNVERIFIED WRITE PROTECTION · NOT EVIDENTIARY\n\n", style=f"bold {THEME_HEX['red']}")

    def _dossier_results(
        self,
        body: Text,
        copied: int,
        expected: int,
        zero_filled: int,
        bad_regions: list[dict],
    ) -> None:
        section_head(body, "ACQUISITION RESULTS")
        kv_row(body, "Source read", f"{copied - zero_filled:,} bytes", LABEL_LG)
        kv_row(body, "Image written", f"{copied:,} bytes", LABEL_LG)
        kv_row(body, "Unacquired", f"{expected - copied:,} bytes", LABEL_LG)
        kv_row(body, "Zero-filled", f"{zero_filled:,} bytes", LABEL_LG)
        kv_row(body, "Coverage base", "image extent / source capacity", LABEL_LG)
        section_head(body, "ACQUISITION EXCEPTIONS")
        if bad_regions:
            count = len(bad_regions)
            label = "unreadable region" if count == 1 else "unreadable regions"
            body.append(f"{count} {label}\n\n", style=THEME_HEX["amber"])
            for region in bad_regions[:8]:
                kv_row(body, "Offset", f"{int(region.get('offset', 0)):,} bytes", LABEL_LG)
                kv_row(body, "Length", f"{int(region.get('length', 0)):,} bytes", LABEL_LG)
                kv_row(body, "Recovery", "Zero-filled", LABEL_LG)
                kv_row(body, "Original data", "Not recovered", LABEL_LG)
        else:
            body.append("No acquisition exceptions recorded\n", style="dim")

    def _dossier_artifacts(
        self,
        body: Text,
        image_path: str,
        manifest_path: str,
        sealed: str,
        encryption: dict,
    ) -> None:
        section_head(body, "EVIDENCE ARTIFACTS")
        kv_row(body, "Image", image_path.rsplit("/", 1)[-1], LABEL_LG)
        kv_row(body, "Manifest", manifest_path.rsplit("/", 1)[-1], LABEL_LG)
        kv_row(body, "Sealed image", sealed.rsplit("/", 1)[-1], LABEL_LG)
        kv_row(body, "Encryption", str(encryption.get("algorithm", "")).split("/")[0], LABEL_LG)

    def _dossier_advanced(
        self,
        body: Text,
        operation: ImagingOperation,
        manifest: dict[str, object],
        piece: dict,
        encryption: dict,
        digest: str,
        readback: str,
        verified: bool,
        image_path: str,
        manifest_path: str,
        sealed: str,
        stopped: str,
    ) -> None:
        section_head(body, "ADVANCED DETAILS")
        section_head(body, "Integrity & Verification")
        kv_row(body, "Acquisition SHA-256", digest, LABEL_LG)
        kv_row(body, "Read-back SHA-256", readback, LABEL_LG)
        kv_row(
            body,
            "Comparison",
            "Match — reported" if verified and digest == readback else "Not verified",
            LABEL_LG,
        )
        kv_row(body, "Method", "Saved image read-back", LABEL_LG)
        kv_row(body, "Verified at", stopped, LABEL_LG)
        kv_row(body, "Piece size", f"{int(piece.get('chunk_size', 0)):,} bytes (4 MiB)" if piece else "", LABEL_LG)
        kv_row(body, "Piece count", str(piece.get("count", "")) if piece else "", LABEL_LG)
        kv_row(body, "Piece hashes", f"Recorded ({int(piece.get('count', 0)):,})" if piece else "", LABEL_LG)
        section_head(body, "Manifest, Encryption & Paths")
        kv_row(body, "Manifest version", str(manifest.get("manifest_version", "")), LABEL_LG)
        kv_row(body, "Manifest created", str(manifest.get("created_at", "")), LABEL_LG)
        kv_row(body, "Tool version", str(manifest.get("tool_version", "")), LABEL_LG)
        kv_row(body, "Cipher", "AES-256-GCM", LABEL_LG)
        kv_row(body, "Key derivation", "PBKDF2-HMAC-SHA256", LABEL_LG)
        kv_row(body, "Iterations", "600,000", LABEL_LG)
        kv_row(body, "Sealed size", f"{int(encryption.get('sealed_size_bytes', 0)):,} bytes", LABEL_LG)
        kv_row(body, "Image path", image_path, LABEL_LG)
        kv_row(body, "Manifest path", manifest_path, LABEL_LG)
        kv_row(body, "Sealed path", sealed, LABEL_LG)
        section_head(body, "Source Diagnostics & Audit")
        kv_row(body, "Source kind", operation.source_kind.value if operation.source_kind else "", LABEL_LG)
        kv_row(body, "Adapter", operation.source_adapter or "", LABEL_LG)
        kv_row(
            body,
            "Inspected",
            operation.source_inspected_at.strftime(UTC_TIMESTAMP_FORMAT) if operation.source_inspected_at else "",
            LABEL_LG,
        )
        synthetic = manifest.get("synthetic")
        if not isinstance(synthetic, bool):
            synthetic = (operation.source_serial or "").startswith("SYNTH-")
        kv_row(body, "Synthetic", "yes" if synthetic else "no", LABEL_LG)
        kv_row(body, "Audit references", "Acquisition events in Audit tab", LABEL_LG)

    def _manifest_for_render(self, operation: ImagingOperation, sample: bool) -> dict[str, object]:
        if sample:
            return self._sample_manifest()
        try:
            return self._service.manifest_for(operation.id)
        except Exception:
            return {}

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

    def action_preview_progress(self) -> None:
        self.app.push_screen(
            ImagingProgressModal(
                preview=True,
                device="SanDisk Cruzer Blade",
                case="2026-CR-0001 · RAW",
                destination=r"D:\evidence\2026-CR-0001\SanDisk-Cruzer-Blade.raw",
            )
        )

    def action_acquire(self) -> None:
        self._begin_acquisition(physical=False)

    def action_acquire_physical(self) -> None:
        self._begin_acquisition(physical=True, hardware_write_block=True)

    def action_acquire_software(self) -> None:
        self._begin_acquisition(physical=True, software_write_block=True)

    def _begin_acquisition(
        self, *, physical: bool, software_write_block: bool = False, hardware_write_block: bool = False
    ) -> None:
        operation = self._selected_operation()
        if operation is None:
            self.app.notify("Select an imaging operation first.", severity="warning")
            return
        if operation.state not in {ImagingState.PREPARING, ImagingState.INTERRUPTED}:
            self.app.notify("Only a reservation or an interrupted image can be acquired.", severity="warning")
            return
        title = "Physical device node" if physical else "Fixture source path"
        if software_write_block:
            hint = "Linux device, e.g. /dev/sdb · SOFTWARE-ONLY · NOT EVIDENTIARY"
        elif physical:
            hint = "device node, e.g. \\\\.\\PhysicalDrive1"
        else:
            hint = "file to acquire"
        self.app.push_screen(
            TextInputModal(title, hint, required=True),
            lambda path: self._start_acquisition(
                operation.id,
                path,
                physical=physical,
                software_write_block=software_write_block,
                hardware_write_block=hardware_write_block,
            ),
        )

    def _start_acquisition(
        self,
        operation_id: UUID,
        path: str | None,
        *,
        physical: bool,
        software_write_block: bool = False,
        hardware_write_block: bool = False,
    ) -> None:
        if not path:
            return
        prior_cancel = self._cancel
        if prior_cancel is not None:
            prior_cancel.set()
        prior_modal = self._progress_modal
        if prior_modal is not None and prior_modal.is_mounted:
            prior_modal.dismiss(None)
        self._progress = None
        token = object()
        self._active_token = token
        self._cancel = threading.Event()
        self._preview = False
        operation = self._selected_operation()
        self._progress_modal = ImagingProgressModal(
            device=(operation.source_model if operation is not None else None) or "—",
            case=f"{operation.case_number} · RAW" if operation is not None and operation.case_number else "RAW",
            destination=path,
            software_only=software_write_block,
        )
        self.app.push_screen(self._progress_modal)
        self.run_worker(
            self._acquire_worker(
                operation_id, path, physical, self._cancel, token, software_write_block, hardware_write_block
            ),
            name="imaging-acquire",
            group="imaging",
            exclusive=True,
        )

    def _active_modal(self, token: object) -> ImagingProgressModal | None:
        if token is not self._active_token:
            return None
        modal = self._progress_modal
        return modal if modal is not None and modal.is_mounted else None

    def _set_acquire_stage(self, token: object, stage: str, note: str = "") -> None:
        modal = self._active_modal(token)
        if modal is not None:
            modal.set_stage(stage, note)

    async def _show_acquire_outcome(
        self,
        token: object,
        stage: str,
        note: str,
        message: str,
        severity: SeverityLevel,
        delay: float,
    ) -> None:
        if token is self._active_token:
            self._cancel = None
        self._set_acquire_stage(token, stage, note)
        self.app.notify(message, severity=severity)
        await asyncio.sleep(delay)

    async def _acquire_worker(
        self,
        operation_id: UUID,
        path: str,
        physical: bool,
        cancel: threading.Event,
        token: object,
        software_write_block: bool = False,
        hardware_write_block: bool = False,
    ) -> None:
        import time as _time

        last = [0.0]

        def _progress(done: int, total: int) -> None:
            now = _time.monotonic()
            if now - last[0] < 0.25 and done != total:
                return
            last[0] = now
            self.app.call_from_thread(self._update_progress, done, total, token)

        self._set_acquire_stage(token, "preflight")
        await asyncio.sleep(0.15)
        try:
            if cancel.is_set():
                await self._show_acquire_outcome(
                    token,
                    "cancelled",
                    "Acquisition stopped before it began.",
                    "Acquisition stopped before it began.",
                    "warning",
                    1.0,
                )
                return
            self._set_acquire_stage(token, "acquiring")
            operation = await asyncio.to_thread(
                self._service.acquire,
                operation_id,
                path,
                allow_real_hardware=physical,
                allow_software_write_block=software_write_block,
                attest_hardware_write_block=hardware_write_block,
                progress=_progress,
                cancelled=cancel.is_set,
            )
        except ImagingInterruptedError:
            await self._show_acquire_outcome(
                token,
                "cancelled",
                "Acquisition stopped. Partial image kept for resume.",
                "Acquisition stopped; partial image kept for resume.",
                "warning",
                1.0,
            )
        except Exception as exc:
            await self._show_acquire_outcome(token, "failed", str(exc), str(exc), "error", 1.2)
        else:
            if token is self._active_token:
                self._cancel = None
            if operation.case_number:
                self._case_number = operation.case_number
            await self._show_acquire_outcome(token, "success", "", "Image byte-verified.", "information", 0.9)
        finally:
            if token is self._active_token:
                self._cancel = None
                self._clear_progress(token)
                self._active_token = None
            self._safe_refresh()

    def _update_progress(self, done: int, total: int, token: object | None = None) -> None:
        if token is not None and token is not self._active_token:
            return
        self._progress = (done, total)
        if token is not None:
            modal = self._active_modal(token)
            if modal is not None:
                modal.update_progress(done, total)
        self._safe_render()

    def _clear_progress(self, token: object | None = None) -> None:
        if token is not None and token is not self._active_token:
            return
        self._progress = None
        modal = self._progress_modal
        if modal is not None and modal.is_mounted:
            modal.dismiss(None)
        self._progress_modal = None
        self._safe_render()

    def action_verify(self) -> None:
        operation = self._selected_operation()
        if operation is None or operation.state is not ImagingState.BYTE_VERIFIED:
            self.app.notify(BYTE_VERIFIED_REQUIRED, severity="warning")
            return
        self.run_worker(
            self._verify_worker(operation.id), name="imaging-verify", group="imaging-actions", exclusive=True
        )

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
            self.app.notify(BYTE_VERIFIED_REQUIRED, severity="warning")
            return
        self.app.push_screen(
            TextInputModal("Seal passphrase", "passphrase", required=True, password=True, confirm=True),
            lambda passphrase: self._seal(operation.id, passphrase),
        )

    def _seal(self, operation_id: UUID, passphrase: str | None) -> None:
        if not passphrase:
            return
        self.run_worker(
            self._seal_worker(operation_id, passphrase), name="imaging-seal", group="imaging-actions", exclusive=True
        )

    async def _seal_worker(self, operation_id: UUID, passphrase: str) -> None:
        try:
            await asyncio.to_thread(self._service.seal_image, operation_id, passphrase)
        except Exception as exc:
            self.app.notify(str(exc), severity="error")
        else:
            self.app.notify("Image sealed.")
        self._safe_refresh()

    def action_unseal(self) -> None:
        operation = self._selected_operation()
        if operation is None or operation.state is not ImagingState.BYTE_VERIFIED:
            self.app.notify(BYTE_VERIFIED_REQUIRED, severity="warning")
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
            group="imaging-actions",
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
            "imaging-progress-preview": self.action_preview_progress,
        }
        action = actions.get(command)
        if action is not None:
            action()
