"""TUI: the case picker, and the Devices tab link/unlink actions."""

import pytest

pytestmark = pytest.mark.unit

_ROWS = [("2026-CR-0001", "Contract Tampering"), ("2026-CR-0002", "Missing Person")]


@pytest.fixture
def case(session_manager):
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    return CaseService(session_manager).create_case(
        CaseCreateDto(title="Contract Tampering", description="d", lead_examiner="Dana Okafor")
    )


SEEN: list[str] = []


def _load_cases(term: str) -> list[tuple[str, str]]:
    """Stand-in for the service-backed loader; records what it was asked for."""
    SEEN.append(term)
    lowered = term.lower()
    return [row for row in _ROWS if lowered in row[0].lower() or lowered in row[1].lower()]


@pytest.mark.anyio
async def test_the_picker_lists_cases_and_filters_them(session_manager, device_file_env) -> None:
    """Rows carry the title, so the choice is made by name rather than by recalled number."""
    from textual.widgets import Input, ListView

    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="Contract Tampering", description="d", lead_examiner="Dana"))
    svc.create_case(CaseCreateDto(title="Missing Person", description="d", lead_examiner="Sara"))

    app = TraceApp(session_manager)
    chosen: list[str | None] = []
    async with app.run_test() as pilot:
        app.push_screen(CasePicker(_load_cases), chosen.append)
        await pilot.pause()

        listing = app.screen.query_one("#case-pick-list", ListView)
        assert len(listing.children) == 2, "every row must be offered"
        assert SEEN == [""], "the loader is asked for the unfiltered set first"

        import asyncio

        app.screen.query_one("#case-pick-filter", Input).value = "missing"
        await asyncio.sleep(0.4)
        await pilot.pause()
        assert len(listing.children) == 1, "typing must narrow the list"
        assert SEEN[-1] == "missing", "the search term must reach the loader"

        listing.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert chosen == ["2026-CR-0002"], "Enter must return the filtered case's number"


@pytest.mark.anyio
async def test_enter_in_the_search_box_accepts_the_top_match(session_manager) -> None:
    """The common path: type the case number, press Enter, never touch the arrow keys."""
    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    app = TraceApp(session_manager)
    chosen: list[str | None] = []
    async with app.run_test() as pilot:
        app.push_screen(CasePicker(_load_cases), chosen.append)
        await pilot.pause()
        box = app.screen.query_one("#case-pick-filter")
        box.focus()
        await pilot.press(*"2026-CR-0002")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert chosen == ["2026-CR-0002"], "Enter in the search box must accept the match"


@pytest.mark.anyio
async def test_an_empty_filter_says_so_rather_than_looking_broken(session_manager) -> None:
    from textual.widgets import Static

    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app.push_screen(CasePicker(lambda _term: []))
        await pilot.pause()

        assert "no case matches" in str(app.screen.query_one("#case-pick-empty", Static).content)


@pytest.mark.anyio
async def test_the_devices_tab_files_a_device_under_the_chosen_case(session_manager, device_file_env) -> None:
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_node_links
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.devices import DevicesView

    CaseService(session_manager).create_case(
        CaseCreateDto(title="Contract Tampering", description="d", lead_examiner="Dana")
    )

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        view = app.query_one(DevicesView)
        node = view._selected_node()
        assert node is not None, "the fixture must yield a device"

        view._linked(node, "2026-CR-0001")
        await pilot.pause()

        assert [link.case_number for link in do_node_links(session_manager, node)] == ["2026-CR-0001"]


@pytest.mark.anyio
async def test_the_devices_tab_unlinks_and_reports(session_manager, device_file_env) -> None:
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_link, do_node_links
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.devices import DevicesView

    case = CaseService(session_manager).create_case(
        CaseCreateDto(title="Contract Tampering", description="d", lead_examiner="Dana")
    )
    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        view = app.query_one(DevicesView)
        node = view._selected_node()
        assert node is not None, "the fixture must yield a device"
        do_link(session_manager, node, case.number)
        view._cases_cache.clear()
        view.render_detail()
        await pilot.pause()

        view._unlinked(node, case.number, True)
        await pilot.pause()

        assert do_node_links(session_manager, node) == []


def test_the_devices_tab_advertises_link_and_unlink() -> None:
    from textual.binding import Binding

    from trace_core.tui.screens.devices import DevicesView

    keys = {b.key for b in DevicesView.BINDINGS if isinstance(b, Binding)}
    assert {"l", "u"} <= keys, "the tab must offer both link and unlink"


def test_the_palette_offers_both_link_commands() -> None:
    from trace_core.tui.palette import COMMANDS

    names = {entry[0] for entry in COMMANDS}
    assert {"device-link", "device-unlink"} <= names


def test_the_footer_hint_names_the_link_key() -> None:
    from trace_core.tui.app import TAB_HINTS

    assert "l Link" in TAB_HINTS["devices"]


@pytest.mark.anyio
async def test_the_picker_searches_through_the_service_not_its_own_matching(session_manager) -> None:
    """Reuse: `CaseFilterDto.search` matches number, title, lead examiner, description and
    notes, and is not capped at one page. The modal matching only number+title itself would
    have been a second, weaker implementation of search that already exists."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.devices import DevicesView

    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="Nothing Alike", description="d", lead_examiner="Priya Raman"))
    svc.create_case(CaseCreateDto(title="Unrelated Matter", description="d", lead_examiner="Sam Ortiz"))

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        view = app.query_one(DevicesView)

        assert len(view._open_cases("")) == 2, "the fixture must hold more than one case"
        assert [n for n, _ in view._open_cases("raman")] == ["2026-CR-0001"], (
            "the examiner's name must narrow the list; a dropped search term returns both"
        )
        assert [n for n, _ in view._open_cases("ortiz")] == ["2026-CR-0002"]


@pytest.mark.anyio
async def test_a_failing_loader_leaves_the_picker_usable(session_manager) -> None:
    """A lookup that raises must not kill the modal: the operator still has to cancel."""
    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    def _boom(_term: str) -> list[tuple[str, str]]:
        raise RuntimeError("cases table is locked")

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        app.push_screen(CasePicker(_boom))
        await pilot.pause()
        await pilot.pause()
        assert len(app.screen.query_one("#case-pick-list").children) == 0


def test_the_dossier_heading_is_linked_device(session_manager, device_file_env, case) -> None:
    """The heading is what the examiner looks for; nothing else guards it.

    `_append_meta` is exercised directly rather than through the screen: the dossier only
    renders for a *selected* case, and driving selection adds UI plumbing that would test
    the selection, not the heading.
    """
    from trace_core.devices.helpers import do_link
    from trace_core.tui.screens.cases import CasesView

    do_link(session_manager, str(device_file_env / "disk-a.dd"), case.number)
    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}

    rendered: list[str] = []
    body = _Recorder(rendered)
    CasesView._append_meta(view, body, case, rule="")

    text = "".join(rendered)
    assert "LINKED DEVICE" in text
    assert "\nDEVICES\n" not in text, "the old DEVICES heading must not come back"


class _Recorder:
    """Minimal stand-in for the Rich Text builder the dossier appends to."""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def append(self, text: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        self._sink.append(text)


def test_every_when_label_is_now_timestamp() -> None:
    """Three panes carried a `When` label; all three are now `Timestamp`.

    Asserted on source because these panes build a Rich Text blob, so the label is not
    reachable through the widget API without rendering a full event first.
    """
    import inspect

    from trace_core.audit import renderers as audit_renderers
    from trace_core.tui.screens import audit as audit_screen
    from trace_core.tui.screens import devices as devices_screen

    for module in (audit_renderers, audit_screen, devices_screen):
        source = inspect.getsource(module)
        assert '"When"' not in source, f"{module.__name__} still renders a When label"

    assert '("Timestamp"' in inspect.getsource(audit_renderers._detail_fields)
    assert '"Timestamp' in inspect.getsource(audit_screen)
    assert '"Timestamp' in inspect.getsource(devices_screen)


def test_the_label_columns_stay_aligned_after_the_rename() -> None:
    """`Timestamp` is wider than `When`; a hand-padded column that is not re-padded
    knocks every sibling label out of alignment."""
    import re

    from trace_core.tui.screens import audit as audit_screen
    from trace_core.tui.screens import devices as devices_screen

    for module in (audit_screen, devices_screen):
        labels = re.findall(r'body\.append\("([A-Za-z ]+)", style="dim"\)', inspect_source(module))
        widths = {len(x) for x in labels}
        assert len(widths) == 1, f"{module.__name__} label column is ragged: {labels}"


def inspect_source(module) -> str:  # noqa: ANN001
    import inspect

    return inspect.getsource(module)


@pytest.mark.anyio
async def test_the_arrow_keys_traverse_the_case_list(session_manager) -> None:
    """Down hands focus to the list; further Downs must move its cursor.

    The modal used to stop every "down", so the list could be focused but never
    traversed - the first press moved focus and each later one was swallowed before
    ListView saw it.
    """
    from textual.widgets import ListView

    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    rows = [(f"2026-CR-{i:04d}", f"Case {i}") for i in range(1, 26)]

    app = TraceApp(session_manager)
    async with app.run_test(size=(100, 40)) as pilot:
        app.push_screen(CasePicker(lambda _t: rows))
        await pilot.pause()
        listing = app.screen.query_one("#case-pick-list", ListView)
        assert app.focused is not None
        assert app.focused.id == "case-pick-filter"

        await pilot.press("down")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "case-pick-list"

        for expected in (1, 2, 3):
            await pilot.press("down")
            await pilot.pause()
            assert listing.index == expected, "the list must follow the arrow keys"

        await pilot.press("up")
        await pilot.pause()
        assert listing.index == 2


@pytest.mark.anyio
async def test_the_list_is_a_fixed_scrolling_window(session_manager) -> None:
    """A list taller than the window scrolls inside it instead of growing the modal."""
    from textual.widgets import ListView

    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    rows = [(f"2026-CR-{i:04d}", f"Case {i}") for i in range(1, 26)]

    app = TraceApp(session_manager)
    async with app.run_test(size=(100, 40)) as pilot:
        app.push_screen(CasePicker(lambda _t: rows))
        await pilot.pause()
        listing = app.screen.query_one("#case-pick-list", ListView)

        assert len(listing.children) == 25, "every row is still loaded"
        assert listing.size.height == 14, "a full list fills the fixed window"
        assert listing.show_vertical_scrollbar, "an overflowing list must show a scrollbar"
        assert listing.max_scroll_y > 0, "and must actually be scrollable"

    # A short list is what separates a FIXED height from `height: auto; max-height: 14`:
    # capped-auto would shrink to three rows, a fixed window stays at fourteen.
    app2 = TraceApp(session_manager)
    async with app2.run_test(size=(100, 40)) as pilot2:
        app2.push_screen(CasePicker(lambda _t: rows[:3]))
        await pilot2.pause()
        short = app2.screen.query_one("#case-pick-list", ListView)
        assert len(short.children) == 3
        assert short.size.height == 14, "a short list must still occupy the fixed window"


def test_the_picker_declares_a_scrollbar_and_filter_padding() -> None:
    """Asserted on the stylesheet: both are presentation-only, and neither shows up in a
    widget attribute - `show_vertical_scrollbar` reflects content overflow, not the CSS."""
    import inspect

    from trace_core.tui.forms import CasePicker

    css = inspect.getsource(CasePicker)
    assert "#case-pick-filter { margin-bottom: 1; }" in css
    assert "scrollbar-size-vertical: 1;" in css


@pytest.mark.anyio
async def test_picker_filter_is_debounced(session_manager) -> None:
    """Typing a filter term must not query per keystroke - one pause, one lookup."""
    import asyncio

    from trace_core.tui.app import TraceApp
    from trace_core.tui.forms import CasePicker

    calls: list[str] = []

    def load(term: str) -> list[tuple[str, str]]:
        calls.append(term)
        return []

    app = TraceApp(session_manager)
    async with app.run_test(size=(100, 40)) as pilot:
        app.push_screen(CasePicker(load))
        await pilot.pause()
        calls.clear()
        for key in ("a", "b", "c"):
            await pilot.press(key)
        await asyncio.sleep(0.5)
        assert calls == ["abc"], f"filter queried per keystroke: {calls}"
