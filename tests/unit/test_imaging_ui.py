from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import Static
from typer.testing import CliRunner

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.main import app
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import ApplicationError
from trace_core.devices import synthetic
from trace_core.imaging.domain import ImagingState
from trace_core.imaging.service import ImagingService
from trace_core.tui.app import TraceApp

pytestmark = pytest.mark.unit


def test_cli_lists_and_abandons_reservation(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    operation = ImagingService(session_manager).reserve(case.number)
    runner = CliRunner()

    listed = runner.invoke(app, ["case", "imaging", case.number, "--output", "json"])
    assert listed.exit_code == 0
    assert str(operation.id) in listed.stdout
    assert "PREPARING" in listed.stdout

    abandoned = runner.invoke(app, ["case", "imaging-abandon", str(operation.id), "--yes"])
    assert abandoned.exit_code == 0
    assert "abandoned" in abandoned.stdout
    assert service.close_case(case.number, reason="finished").status.value == "CLOSED"


def test_cli_reserves_and_acquires_a_fixture(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    monkeypatch.setattr("trace_core.core.service.db_manager", manager)
    case = CaseService(manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=2048)
    runner = CliRunner()

    reserved = runner.invoke(app, ["case", "imaging-reserve", case.number, "--yes"])
    assert reserved.exit_code == 0
    operation = ImagingService(manager).list_for_case(case.number)[0]

    acquired = runner.invoke(app, ["case", "imaging-acquire", str(operation.id), "--source", str(source), "--yes"])
    assert acquired.exit_code == 0
    assert "byte-verified" in acquired.stdout
    assert ImagingService(manager).list_for_case(case.number)[0].state is ImagingState.BYTE_VERIFIED


def test_cli_declined_abandon_leaves_reservation_active(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    operation = ImagingService(session_manager).reserve(case.number)

    result = CliRunner().invoke(app, ["case", "imaging-abandon", str(operation.id)], input="n\n")

    assert result.exit_code == 0
    assert ImagingService(session_manager).list_for_case(case.number)[0].state.value == "PREPARING"


def test_cli_rejects_invalid_imaging_output(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))

    result = CliRunner().invoke(app, ["case", "imaging", case.number, "--output", "invalid"])

    assert result.exit_code != 0
    assert "Invalid output format" in result.stdout


@pytest.mark.anyio
async def test_case_dossier_labels_reservation_as_not_an_image(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    operation = ImagingService(session_manager).reserve(case.number)
    tui = TraceApp(session_manager)

    async with tui.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        content = tui.query_one("#case-dossier", Static).render()
        text = content.plain if isinstance(content, Text) else str(content)
        assert "IMAGING" in text
        assert "reservation only; no image acquired" in text
        assert str(operation.id) in text


@pytest.mark.anyio
async def test_case_dossier_refresh_reloads_imaging_status(
    service: CaseService, session_manager: DatabaseSessionManager
) -> None:
    from trace_core.tui.screens.cases import CasesView

    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    tui = TraceApp(session_manager)
    async with tui.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        operation = ImagingService(session_manager).reserve(case.number)
        tui.query_one(CasesView).refresh_data()
        await pilot.pause()
        content = tui.query_one("#case-dossier", Static).render()
        text = content.plain if isinstance(content, Text) else str(content)
        assert str(operation.id) in text


@pytest.mark.anyio
async def test_case_view_reserves_and_acquires_a_fixture(
    tmp_path: Path, temp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import Input, TabbedContent

    from trace_core.tui.screens.imaging import ImagingView

    manager = DatabaseSessionManager(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    manager.init_schema()
    case = CaseService(manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    source = synthetic.write_disk(tmp_path / "fixture.dd", size=2048)
    tui = TraceApp(manager)
    notices: list[tuple[str, dict]] = []

    async with tui.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(tui, "notify", lambda message, **kwargs: notices.append((message, kwargs)))
        await pilot.press("i")
        await pilot.pause()
        assert tui.query_one(TabbedContent).active == "imaging"
        assert tui.query_one(ImagingView)._case_number == case.number

        await pilot.press("n")
        await pilot.pause()
        operations = ImagingService(manager).list_for_case(case.number)
        assert len(operations) == 1
        assert operations[0].state is ImagingState.PREPARING

        await pilot.press("a")
        await pilot.pause()
        tui.screen.query_one("#text-input", Input).value = str(source)
        await pilot.press("enter")
        for _ in range(80):
            await pilot.pause()
            if ImagingService(manager).list_for_case(case.number)[0].state is ImagingState.BYTE_VERIFIED:
                break

    stored = ImagingService(manager).list_for_case(case.number)[0]
    assert stored.state is ImagingState.BYTE_VERIFIED
    assert stored.copied_bytes == 2048
    assert any("byte-verified" in message for message, _ in notices)


@pytest.mark.anyio
async def test_case_view_abandons_an_unresolved_operation(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import Button, TabbedContent

    from trace_core.tui.screens.imaging import ImagingView

    case = service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))
    ImagingService(session_manager).reserve(case.number)
    tui = TraceApp(session_manager)
    notices: list[tuple[str, dict]] = []

    async with tui.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(tui, "notify", lambda message, **kwargs: notices.append((message, kwargs)))
        await pilot.press("i")
        await pilot.pause()
        assert tui.query_one(TabbedContent).active == "imaging"
        assert tui.query_one(ImagingView)._selected_operation() is not None

        await pilot.press("x")
        await pilot.pause()
        tui.screen.query_one("#yes", Button).press()
        for _ in range(40):
            await pilot.pause()
            if ImagingService(session_manager).list_for_case(case.number)[0].state is ImagingState.FAILED:
                break

    assert any("abandoned" in message for message, _ in notices)
    assert ImagingService(session_manager).list_for_case(case.number)[0].state is ImagingState.FAILED


@pytest.mark.anyio
async def test_imaging_progress_popup_is_closeable() -> None:
    from textual.widgets import Static

    from trace_core.tui.screens.imaging import ImagingProgressModal

    app = TraceApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(ImagingProgressModal())
        await pilot.pause()
        assert isinstance(app.screen, ImagingProgressModal)
        popup = app.screen
        popup.update_progress(50, 100)
        assert "50 B / 100 B" in str(popup.query_one("#progress-bytes", Static).render())
        assert not popup.query("#progress-close")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ImagingProgressModal)


@pytest.mark.anyio
async def test_imaging_progress_popup_preview_animates_green_fill() -> None:
    from rich.color import Color
    from textual.content import Content
    from textual.widgets import Static

    from trace_core.core.ui.theme import THEME_HEX
    from trace_core.tui.screens.imaging import ImagingProgressModal, SegmentedProgress

    triplet = Color.parse(THEME_HEX["green"]).triplet
    assert triplet is not None
    red, green, blue = triplet
    rgb = f"rgb({red},{green},{blue})"

    def green_count(rendered: Content) -> int:
        return sum(span.end - span.start for span in rendered.spans if rgb in str(span.style))

    app = TraceApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(
            ImagingProgressModal(
                preview=True,
                device="SanDisk Cruzer Blade",
                case="2026-CR-0001 · RAW",
                destination=r"D:\evidence\2026-CR-0001\SanDisk-Cruzer-Blade.raw",
            )
        )
        await pilot.pause()
        popup = app.screen
        assert isinstance(popup, ImagingProgressModal)
        assert "SanDisk Cruzer Blade" in str(popup.query_one("#progress-device", Static).render())
        assert "2026-CR-0001 · RAW" in str(popup.query_one("#progress-case", Static).render())
        assert "SanDisk-Cruzer-Blade.raw" in str(popup.query_one("#progress-destination", Static).render())
        assert "Evidence Acquisition" in str(popup.query_one("#progress-title", Static).render())
        assert str(popup.query_one("#progress-esc", Static).render()) == "Esc"
        assert not popup.query("#progress-close")
        assert popup.query_one("#progress-device", Static).region.height == 1
        assert popup.query_one("#progress-device", Static).region.y > popup.query_one("#progress-head").region.y + 1
        labels = [str(node.render()) for node in popup.query(".metric-label")]
        assert labels == ["Read Speed", "Elapsed", "Bad regions"]
        assert str(popup.query_one("#progress-destination-label", Static).render()) == "Destination"
        bar = popup.query_one("#progress-bar", SegmentedProgress)
        assert popup._timer is not None
        popup._timer.stop()
        popup.update_progress(0, popup._preview_total)
        rendered = bar.render()
        assert isinstance(rendered, Content)
        before = green_count(rendered)
        for _ in range(60):
            popup._preview_tick()
        await pilot.pause()
        rendered = bar.render()
        assert isinstance(rendered, Content)
        after = green_count(rendered)
        assert after > before
        assert len(rendered.plain.splitlines()) == 1
        assert "██" in rendered.plain
        assert str(popup.query_one("#progress-status", Static).render()) == "62% | ETA: 24s"
        assert "4.6 GB / 7.5 GB" in str(popup.query_one("#progress-bytes", Static).render())
        assert "124 MB/s" in str(popup.query_one("#progress-speed", Static).render())
        assert "00:38" in str(popup.query_one("#progress-elapsed", Static).render())
        assert str(popup.query_one("#progress-bad", Static).render()) == "0"


@pytest.mark.anyio
async def test_imaging_dossier_shows_full_operation_detail(session_manager: DatabaseSessionManager) -> None:
    from textual.widgets import Static, TabbedContent

    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.imaging.service import ImagingService
    from trace_core.tui.app import TAB_HINTS
    from trace_core.tui.screens.imaging import ImagingView

    case = CaseService(session_manager).create_case(CaseCreateDto(title="Imaging", lead_examiner="Ex"))
    ImagingService(session_manager).reserve(case.number)
    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        assert app.query_one(TabbedContent).active == "imaging"
        view = app.query_one(ImagingView)
        view._update_progress(50, 100)
        detail = str(app.query_one("#imaging-dossier", Static).render())
        assert case.number in detail
        assert "PREPARING" in detail
        assert "Coverage" in detail
        assert "Acquisition ID" not in detail
        assert "SOURCE EVIDENCE" in detail
        assert "Ctrl+A — expand advanced details" in detail
        view.action_toggle_advanced()
        detail = str(app.query_one("#imaging-dossier", Static).render())
        assert "Acquisition ID" in detail
        assert "Manifest & encryption" in detail

    assert "tab-imaging" not in TAB_HINTS
    assert "Ctrl+P Commands" in TAB_HINTS["imaging"]


@pytest.mark.anyio
async def test_imaging_preview_shows_labelled_sample_data(session_manager: DatabaseSessionManager) -> None:
    from textual.widgets import Static

    from trace_core.tui.screens.imaging import ImagingView

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        view = app.query_one(ImagingView)
        view.action_toggle_preview()
        detail = str(view.query_one("#imaging-dossier", Static).render())
        assert "SAMPLE — NOT EVIDENCE" in detail
        assert "c68aac89-bd30-4c73-91ca-4d878e09c370" not in detail
        assert "SanDisk Cruzer Blade" in detail
        assert "Coverage" in detail
        assert "Source read" in detail
        assert "187,654,322" in detail
        assert "ACQUISITION EXCEPTIONS" in detail
        assert "Original data not recovered" in detail
        view.action_toggle_advanced()
        advanced = str(view.query_one("#imaging-dossier", Static).render())
        assert "c68aac89-bd30-4c73-91ca-4d878e09c370" in advanced
        assert "Integrity & verification" in advanced
        assert "Verification method" in advanced
        assert "Key derivation" in advanced
        assert "9f2c1a7b4e6d5830f1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708" in advanced
        view.action_toggle_preview()
        assert "SAMPLE — NOT EVIDENCE" not in str(view.query_one("#imaging-dossier", Static).render())


@pytest.mark.anyio
async def test_case_dossier_reports_unavailable_imaging_records(
    service: CaseService, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.create_case(CaseCreateDto(title="Imaging", lead_examiner="Examiner"))

    def fail_list(self: ImagingService, case_identifier: str) -> list[object]:
        raise ApplicationError("unavailable")

    monkeypatch.setattr(ImagingService, "list_for_case", fail_list)
    tui = TraceApp(session_manager)
    async with tui.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        content = tui.query_one("#case-dossier", Static).render()
        text = content.plain if isinstance(content, Text) else str(content)
        assert "Imaging records unavailable." in text


@pytest.mark.anyio
async def test_imaging_primary_dossier_uses_forensic_verdicts(session_manager: DatabaseSessionManager) -> None:
    from textual.widgets import Static

    from trace_core.tui.screens.imaging import ImagingView

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        view = app.query_one(ImagingView)
        view.action_toggle_preview()
        detail = str(view.query_one("#imaging-dossier", Static).render())
        for label in ("Acquisition", "Integrity", "Evidence", "Coverage", "Examiner", "Started", "Ended"):
            assert label in detail
        for hidden in ("Acquisition ID", "Image written", "Coverage base", "Cipher", "Manifest version"):
            assert hidden not in detail
        view.action_toggle_advanced()
        advanced = str(view.query_one("#imaging-dossier", Static).render())
        for section in (
            "Integrity & verification",
            "Acquisition metadata",
            "Manifest & encryption",
            "Diagnostics & audit",
        ):
            assert section in advanced


@pytest.mark.anyio
async def test_imaging_inspect_modals_open(session_manager: DatabaseSessionManager) -> None:
    from trace_core.tui.screens.imaging import BadRegionsModal, ImagingView, PieceHashesModal

    app = TraceApp(session_manager)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        view = app.query_one(ImagingView)
        view.action_toggle_preview()
        await pilot.press("ctrl+k")
        await pilot.pause()
        assert isinstance(app.screen, PieceHashesModal)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert isinstance(app.screen, BadRegionsModal)
