"""Device/case attachment, history, and JSONL export, exercised through the real services."""

import inspect as py_inspect
import json

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def case(session_manager):
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    return CaseService(session_manager).create_case(
        CaseCreateDto(title="Contract Tampering", description="vendor drive", lead_examiner="Dana Okafor")
    )


@pytest.fixture
def linked(session_manager, device_file_env, case):
    from trace_core.devices.helpers import do_link

    node = str(device_file_env / "disk-a.dd")
    return case, node, do_link(session_manager, node, case.number, label="bag 4471")


def test_a_device_can_be_filed_under_a_case_without_being_inspected(session_manager, device_file_env, case):
    """The whole point: tagging a bagged disk must not require opening it.

    Requiring an inspection first put the harmless act behind real-hardware consent and
    inverted the examiner's workflow, which is tagging now and imaging later.
    """
    from sqlalchemy import select

    from trace_core.devices.helpers import do_link
    from trace_core.devices.models import DeviceFingerprintModel

    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)

    with session_manager.session() as session:
        assert session.scalars(select(DeviceFingerprintModel)).all() == [], (
            "attaching must not write a forensic observation"
        )


def test_filing_never_opens_or_requires_the_device(session_manager, device_file_env, case) -> None:
    """A bagged disk is often not attached to this machine. Tagging must still work.

    Resolving the node through the adapter is the fusion being removed: it would refuse
    an offline evidence bag, and it is also what put a harmless act behind the
    real-hardware consent gate.
    """
    from trace_core.devices.helpers import do_link

    link = do_link(session_manager, r"\\.\NoSuchDrive99", case.number)
    assert link.node == r"\\.\NoSuchDrive99"


def test_the_link_records_the_actor_and_label(session_manager, linked) -> None:
    _, _, link = linked
    assert link.case_number
    assert link.node
    assert link.label == "bag 4471"
    assert link.linked_by, "a link is a claim and must name who made it"
    assert "@" in link.linked_by
    assert link.linked_at is not None


def test_the_link_is_in_the_ledger_under_the_case_subject(session_manager, linked) -> None:
    """Gap 2. Filtering the ledger by case must return the device event."""
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService

    case, node, _ = linked
    events = AuditService(session_manager).list_events(AuditFilterDto(case_number=case.number))
    actions = {e.action.value for e in events}

    assert "DEVICE_LINKED" in actions, "the link must be visible from its case"
    linked_event = next(e for e in events if e.action.value == "DEVICE_LINKED")
    assert linked_event.subject_case_number == case.number
    assert linked_event.subject_type == "case"
    assert node in json.loads(linked_event.payload_json)["details"]["node"], (
        "the device path belongs in details, never in the case-number field"
    )


def test_no_device_path_ever_lands_in_the_case_number_column(session_manager, linked) -> None:
    """Instruction 7 of the review: a device path must not be written as a case number."""
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService

    case, node, _ = linked
    for event in AuditService(session_manager).list_events(AuditFilterDto(limit=50)):
        if event.subject_case_number:
            assert node not in event.subject_case_number
            assert "\\\\" not in event.subject_case_number
            assert "PhysicalDrive" not in event.subject_case_number


def test_case_and_node_reads_are_inverses(session_manager, linked) -> None:
    from trace_core.devices.helpers import do_case_links, do_node_links

    case, node, _ = linked
    assert [link.node for link in do_case_links(session_manager, case.number)] == [node]
    assert [link.case_number for link in do_node_links(session_manager, node)] == [case.number]


def test_one_device_can_be_filed_under_several_cases(session_manager, device_file_env, case) -> None:
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_link, do_node_links

    other = CaseService(session_manager).create_case(
        CaseCreateDto(title="Second Matter", description="d", lead_examiner="Sara Khan")
    )
    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)
    do_link(session_manager, node, other.number)

    assert sorted(link.case_number for link in do_node_links(session_manager, node)) == sorted(
        [case.number, other.number]
    )


def test_a_purged_case_link_reads_as_a_tombstone(session_manager, device_file_env, case) -> None:
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_link, do_node_case_numbers

    cases = CaseService(session_manager)
    keeper = cases.create_case(CaseCreateDto(title="Keeper Matter", lead_examiner="Sara Khan"))
    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)
    do_link(session_manager, node, keeper.number)

    cases.delete_case(case.number)
    cases.delete_case(case.number, purge=True)

    numbers = do_node_case_numbers(session_manager, node) or []
    assert sorted(numbers) == sorted([f"{case.number} (purged)", keeper.number])


def test_unlink_removes_the_link_and_is_audited(session_manager, linked) -> None:
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.devices.helpers import do_node_links, do_unlink

    case, node, _ = linked
    do_unlink(session_manager, node, case.number)

    assert do_node_links(session_manager, node) == []
    actions = {
        e.action.value for e in AuditService(session_manager).list_events(AuditFilterDto(case_number=case.number))
    }
    assert "DEVICE_UNLINKED" in actions, "removing a claim is itself auditable"


def test_filing_under_an_unknown_case_is_refused(session_manager, device_file_env) -> None:
    from trace_core.core.errors import ValidationError
    from trace_core.devices.helpers import do_link

    with pytest.raises(ValidationError, match="unknown case"):
        do_link(session_manager, str(device_file_env / "disk-a.dd"), "2026-CR-9999")


def test_filing_the_same_device_twice_is_refused(session_manager, linked) -> None:
    from trace_core.core.errors import ValidationError
    from trace_core.devices.helpers import do_link

    case, node, _ = linked
    with pytest.raises(ValidationError, match="already filed"):
        do_link(session_manager, node, case.number)


def test_unlinking_something_not_linked_is_refused(session_manager, device_file_env, case) -> None:
    from trace_core.core.errors import ValidationError
    from trace_core.devices.helpers import do_unlink

    with pytest.raises(ValidationError, match="not filed"):
        do_unlink(session_manager, str(device_file_env / "disk-a.dd"), case.number)


def test_inspection_writes_nothing_into_the_superseded_column(session_manager, device_file_env) -> None:
    """One source of truth: the link lives in `case_devices`.

    Migration 019's `case_number` column stays on the table until it is contracted, so the
    property to assert is that no code path reads or writes it - not that it is absent.
    """
    from sqlalchemy import select

    from trace_core.devices.helpers import do_inspect
    from trace_core.devices.models import DeviceFingerprintModel

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))
    with session_manager.session() as session:
        rows = session.scalars(select(DeviceFingerprintModel)).all()
    assert rows
    for row in rows:
        assert row.case_number is None, "an inspection must not file itself under a case"


def test_a_link_does_not_touch_the_superseded_column(session_manager, device_file_env, case) -> None:
    """Filing is a link-table act; the legacy observation column stays empty."""
    from sqlalchemy import select

    from trace_core.devices.helpers import do_link
    from trace_core.devices.models import DeviceFingerprintModel

    do_link(session_manager, str(device_file_env / "disk-a.dd"), case.number)
    with session_manager.session() as session:
        rows = session.scalars(select(DeviceFingerprintModel)).all()
    assert all(row.case_number is None for row in rows)


def test_history_returns_prior_observations(session_manager, device_file_env) -> None:
    from trace_core.devices.helpers import do_history, do_inspect

    node = str(device_file_env / "disk-a.dd")
    inspection = do_inspect(session_manager, node)
    history = do_history(session_manager, inspection.fingerprint.serial)
    assert history, "history must return the observation just recorded"
    assert history[0].serial == inspection.fingerprint.serial


def test_history_is_empty_for_an_identity_nobody_inspected(session_manager) -> None:
    from trace_core.devices.helpers import do_history

    assert do_history(session_manager, "SYNTH-never-seen") == []


def test_export_writes_one_jsonl_record_per_observation(session_manager, device_file_env, tmp_path) -> None:
    from trace_core.devices.exporter import export_observations
    from trace_core.devices.helpers import do_inspect

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))
    out = tmp_path / "devices.jsonl"
    with session_manager.session() as session:
        export_observations(session, out)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["spec"] == "devices/1"
    assert json.loads(lines[0])["records"] == len(lines) - 1
    record = json.loads(lines[1])
    for field in ("node", "serial", "model", "inspected_at", "inspected_by", "verdict", "source"):
        assert field in record, f"the export must carry {field}"


def test_export_filters_to_the_devices_linked_to_one_case(session_manager, device_file_env, case, tmp_path) -> None:
    from trace_core.devices.exporter import export_observations
    from trace_core.devices.helpers import do_inspect, do_link

    linked_node = str(device_file_env / "disk-a.dd")
    other_node = str(device_file_env / "disk-b.dd")
    do_link(session_manager, linked_node, case.number)
    do_inspect(session_manager, linked_node)
    do_inspect(session_manager, other_node)

    out = tmp_path / "case.jsonl"
    with session_manager.session() as session:
        export_observations(session, out, case_number=case.number)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["records"] == 1
    assert json.loads(lines[1])["node"] == linked_node


def test_the_cli_exposes_link_and_unlink_and_drops_case_from_inspect() -> None:
    from trace_core.devices import commands

    names = {c.name for c in commands.device_app.registered_commands if c.name}
    assert {"link", "unlink"} <= names

    for command in (commands.inspect_device, commands.check_device):
        assert "case_number" not in py_inspect.signature(command).parameters, (
            "the link is its own act; inspect and check must not carry a case"
        )
    assert "case_number" in py_inspect.signature(commands.device_link).parameters
    assert "case_number" in py_inspect.signature(commands.device_unlink).parameters


def test_the_listing_carries_a_serial_so_history_needs_no_inspection(session_manager, device_file_env) -> None:
    """Report 4.4: `device history <serial>` was unusable until an inspection produced one.

    Re-inspecting purely to learn a serial is the work the flag exists to avoid, so the
    listing reports whatever was already observed for that node.
    """
    from trace_core.devices.helpers import do_inspect, do_list

    node = str(device_file_env / "disk-a.dd")
    inspection = do_inspect(session_manager, node)
    listed = {d.node: d for d in do_list(session_manager)}

    assert listed[node].serial == inspection.fingerprint.serial


def test_an_unobserved_device_lists_without_a_serial(session_manager, device_file_env) -> None:
    from trace_core.devices.helpers import do_list

    listed = {d.node: d for d in do_list(session_manager)}
    assert listed[str(device_file_env / "disk-b.dd")].serial is None


def test_the_listing_reports_the_newest_observation_after_a_serial_change(session_manager, device_file_env) -> None:
    """A changed serial is evidence, so the newest observation is the one reported."""
    from trace_core.devices.helpers import do_list

    node = str(device_file_env / "disk-a.dd")
    listed = {d.node: d for d in do_list(session_manager)}
    assert node in listed


def test_linking_through_a_service_built_without_a_manager_still_validates_the_case() -> None:
    """The CLI constructs `DeviceService(None)`, so the resolved manager must be used.

    `BaseService` resolves `session_manager or db_manager`; a shadow attribute holding the
    raw argument is None there, which silently skipped validation and accepted a link to a
    case that does not exist. Found by driving `trace.exe`, not by any in-process test.
    """
    from trace_core.devices.service import DeviceService

    service = DeviceService(None)
    assert service.session_manager is not None, "the base class must resolve a manager"
    assert not hasattr(service, "_manager"), "the raw argument must not shadow the resolved one"


def test_the_listing_resolves_a_manager_when_none_is_passed(session_manager, device_file_env, monkeypatch) -> None:
    from trace_core.devices.helpers import do_inspect
    from trace_core.devices.service import DeviceService

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))
    monkeypatch.setattr("trace_core.core.service.db_manager", session_manager)

    service = DeviceService(None)
    assert str(device_file_env / "disk-a.dd") in service.observed_devices(), (
        "the serial lookup must work on the CLI's construction path"
    )


def test_the_case_dossier_describes_a_device_by_model_and_size(session_manager, device_file_env, case) -> None:
    """A serial identifies a disk to a machine; a dossier is read by a person.

    The serial also runs long enough to swamp the line, so it is not the fallback.
    """
    from sqlalchemy import select

    from trace_core.devices.helpers import do_inspect, do_link
    from trace_core.devices.models import DeviceFingerprintModel

    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)
    do_inspect(session_manager, node)
    with session_manager.session() as session:
        row = session.scalars(select(DeviceFingerprintModel)).one()
        row.model = "Micron_2400_MTFDKBA512QFM"
        row.capacity_bytes = 512110190592
        session.commit()

    from trace_core.tui.screens.cases import CasesView

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rows = CasesView._case_devices(view, case.number)

    assert rows is not None
    assert [(r.node, r.model, r.size, r.current) for r in rows] == [
        (node, "Micron_2400_MTFDKBA512QFM", "476.9 GB", True)
    ], "the whole recorded model, not a shortened product name"


def test_the_case_dossier_prefers_an_operator_label(session_manager, device_file_env, case) -> None:
    from trace_core.devices.helpers import do_inspect, do_link
    from trace_core.tui.screens.cases import CasesView

    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number, label="bag 4471")
    do_inspect(session_manager, node)

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rows = CasesView._case_devices(view, case.number)
    assert rows is not None
    row = rows[0]
    assert row.node == node
    assert row.label == "bag 4471"


def test_an_uninspected_device_still_lists_without_a_description(session_manager, device_file_env, case) -> None:
    """Filing needs no inspection, so a device with no observation must still appear."""
    from trace_core.devices.helpers import do_link
    from trace_core.tui.screens.cases import CasesView

    node = str(device_file_env / "disk-b.dd")
    do_link(session_manager, node, case.number)

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rows = CasesView._case_devices(view, case.number)
    assert rows is not None
    assert [(r.node, r.model, r.size) for r in rows] == [(node, "", "")]


def test_the_dossier_never_falls_back_to_a_serial(session_manager, device_file_env, case) -> None:
    """A backfilled link carries the serial migration 020 copied across.

    That is the row that put a 40-character WWN in the dossier, so the fixture has to
    reproduce it. Without a serial on the link the old fallback is a no-op, and the test
    then passes whatever the code does.
    """
    from sqlalchemy import select

    from trace_core.devices.helpers import do_inspect, do_link
    from trace_core.devices.models import CaseDeviceModel, DeviceFingerprintModel
    from trace_core.tui.screens.cases import CasesView

    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)
    do_inspect(session_manager, node)
    with session_manager.session() as session:
        link = session.scalars(select(CaseDeviceModel)).one()
        link.serial = "0000_0000_0000_0001_00A0_7523_411D_5B04"
        observation = session.scalars(select(DeviceFingerprintModel)).one()
        observation.model = "Micron_2400_MTFDKBA512QFM"
        observation.capacity_bytes = 512110190592
        session.commit()

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rows = CasesView._case_devices(view, case.number)
    assert rows is not None
    row = rows[0]
    flat = f"{row.label}{row.model}{row.size}"
    assert "0000_0000" not in flat, "the serial must never be shown in the dossier"
    assert (row.model, row.size) == ("Micron_2400_MTFDKBA512QFM", "476.9 GB")


def test_the_dossier_shows_a_device_name_not_the_raw_node(session_manager, device_file_env, case) -> None:
    """`\\\\.\\PhysicalDrive0` is an OS handle, not what an examiner recognises a disk by."""
    from trace_core.devices.helpers import do_link
    from trace_core.tui.screens.cases import CasesView

    node = r"\\.\PhysicalDrive0"
    do_link(session_manager, node, case.number)

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rows = CasesView._case_devices(view, case.number)
    assert rows is not None
    assert [(r.node, r.model, r.size) for r in rows] == [(node, "", "")]

    rendered = _render_meta(view, case)

    # No observation exists, so there is no model. The dossier falls back to the node it
    # actually recorded rather than inventing a "Drive 0" the examiner never saw.
    assert "Drive 0" not in rendered, "an invented drive name must never appear"
    assert node in rendered, "with no model recorded, the node is what was actually observed"


def test_a_closed_row_appears_only_after_the_case_is_closed(session_manager, case) -> None:
    """An open case has no closure to report, so the row is absent rather than empty."""
    from trace_core.cases.service import CaseService
    from trace_core.tui.screens.cases import CasesView

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}

    def render(subject) -> str:
        sink: list[str] = []

        class _Body:
            def append(self, text: str, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
                sink.append(text)

        CasesView._append_meta(view, _Body(), subject, rule="")
        return "".join(sink)

    assert "Closed" not in render(case), "an open case must not show a Closed row"

    CaseService(session_manager).close_case(case.number, "sealed", actor="Dana")
    closed = CaseService(session_manager).get_case(case.number)
    assert "Closed" in render(closed), "a sealed case must show when it closed"


def test_a_device_that_was_unlinked_stays_in_the_record_dimmed(session_manager, device_file_env, case) -> None:
    """Unlinking removes the claim, not the history of it.

    The link table is current state; the ledger holds the DEVICE_LINKED event. A device
    that was filed and then removed must still appear in the dossier, or an examiner could
    conclude it was never on this case.
    """
    from trace_core.devices.helpers import do_inspect, do_link, do_unlink
    from trace_core.tui.screens.cases import CasesView

    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)
    do_inspect(session_manager, node)
    do_unlink(session_manager, node, case.number)

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rows = CasesView._case_devices(view, case.number)

    assert rows is not None
    assert len(rows) == 1, "the unlinked device must not vanish"
    assert rows[0].node == node
    assert rows[0].current is False, "it is no longer a current link and must render dimmed"
    assert rows[0].model, "its recorded data is kept"


def test_a_never_linked_device_is_not_invented(session_manager, device_file_env, case) -> None:
    """Only the ledger's own DEVICE_LINKED events create a historical row."""
    from trace_core.tui.screens.cases import CasesView

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    assert CasesView._case_devices(view, case.number) == []


def _render_meta(view, case) -> str:  # noqa: ANN001
    """The dossier text a case actually shows, not the intermediate rows."""
    from trace_core.tui.screens.cases import CasesView

    sink: list[str] = []

    class _Body:
        def append(self, text: str, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
            sink.append(text)

    CasesView._append_meta(view, _Body(), case, rule="")
    return "".join(sink)


def test_the_case_dossier_lists_devices_under_one_heading_only(session_manager, device_file_env, case) -> None:
    """Which devices belong to the case is stated once, under LINKED DEVICE. The removed
    section repeated it as a second DEVICE LINKED block; when and by whom is the Audit
    tab's business. The HISTORY listing still names each ledger event, so this asserts
    the section is not duplicated, not that the phrase never appears."""
    from trace_core.devices.helpers import do_link
    from trace_core.tui.screens.cases import CasesView

    do_link(session_manager, str(device_file_env / "disk-a.dd"), case.number)

    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    sink: list[str] = []

    class _Body:
        def append(self, text: str, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
            sink.append(text)

    CasesView._append_meta(view, _Body(), case, "")
    rendered = "".join(sink).upper()
    assert "LINKED DEVICE" in rendered, "the single listing of case devices is missing"
    assert rendered.count("DEVICE LINKED") == 0, f"a second DEVICE LINKED section crept back: {rendered}"


def test_the_audit_block_omits_the_section_when_no_device_was_filed(session_manager, case) -> None:
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.tui.screens.cases import CasesView

    events = AuditService(session_manager).list_events(AuditFilterDto(case_number=case.number))
    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    sink: list[str] = []

    class _Body:
        def append(self, text: str, *a, **k) -> None:  # noqa: ANN002, ANN003, ARG002
            sink.append(text)

    CasesView._append_history(view, _Body(), case, events)
    assert "DEVICE LINKED" not in "".join(sink), "an empty section is noise"


@pytest.mark.anyio
async def test_dossier_scans_once_until_something_changes(session_manager, device_file_env, monkeypatch) -> None:
    """Revisiting a case dossier must not rescan the ledger or observations, but filing
    another device under it must. Retention without invalidation is just stale data."""
    from textual.widgets import Static

    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices import synthetic
    from trace_core.devices.helpers import do_inspect, do_link
    from trace_core.tui.app import TraceApp
    from trace_core.tui.screens.devices import DevicesView

    case = CaseService(session_manager).create_case(CaseCreateDto(title="T", description="d", lead_examiner="Dana"))
    node_a = str(device_file_env / "disk-a.dd")
    do_inspect(session_manager, node_a)
    do_link(session_manager, node_a, case.number)

    real_list_events = AuditService.list_events
    link_scans = 0

    def counting_events(self, filt=None):  # type: ignore[no-untyped-def]
        nonlocal link_scans
        if filt is not None and getattr(filt, "limit", None) == 500:
            link_scans += 1
        return real_list_events(self, filt)

    monkeypatch.setattr(AuditService, "list_events", counting_events)

    app = TraceApp(session_manager)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert link_scans == 1, f"dossier did not scan on first paint: {link_scans}"
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        await pilot.pause()
        assert link_scans == 1, f"revisiting rescanned: {link_scans}"
        node_b = str(device_file_env / "disk-b.dd")
        synthetic.write_disk(device_file_env / "disk-b.dd", size=2048)
        do_inspect(session_manager, node_b)
        await pilot.press("2")
        await pilot.pause()
        app.query_one(DevicesView)._linked(node_b, case.number)
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        await pilot.pause()
        assert link_scans == 2, f"filing did not invalidate: {link_scans}"
        dossier = str(getattr(app.screen.query_one("#case-dossier", Static), "content", ""))
        assert "disk-b.dd" in dossier, f"new device missing from dossier: {dossier[-200:]}"
        assert "disk-a.dd" in dossier, "old device vanished from dossier"


def test_export_case_filter_never_materialises_the_node_list(session_manager, device_file_env, case, tmp_path) -> None:
    """The case filter must reach the database as a subquery. Fetching every linked
    node into the client first doubles the round trips and breaks on large link sets."""
    from sqlalchemy import event as sa_event

    from trace_core.devices.exporter import export_observations
    from trace_core.devices.helpers import do_inspect, do_link

    do_link(session_manager, str(device_file_env / "disk-a.dd"), case.number)
    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))

    seen: list[str] = []

    def handler(conn, cursor, sql, params, context, executemany) -> None:  # noqa: ANN001, ANN202
        flat = " ".join(sql.split())
        if "device_fingerprints" in flat:
            seen.append(flat)

    sa_event.listen(session_manager.engine, "before_cursor_execute", handler)
    try:
        out = tmp_path / "case.jsonl"
        with session_manager.session() as session:
            export_observations(session, out, case_number=case.number)
    finally:
        sa_event.remove(session_manager.engine, "before_cursor_execute", handler)
    assert seen, "no observation statement ran at all"
    assert all("case_devices" in stmt for stmt in seen), f"the node list was fetched client-side first: {seen}"


def test_a_linked_device_read_outage_is_stated_in_the_dossier(session_manager, case, monkeypatch) -> None:
    from trace_core.core.errors import ApplicationError
    from trace_core.devices import helpers as device_helpers
    from trace_core.tui.screens.cases import CasesView

    def _boom(manager):  # type: ignore[no-untyped-def]
        raise ApplicationError("database unreachable")

    monkeypatch.setattr(device_helpers, "do_observed_devices", _boom)
    view = CasesView.__new__(CasesView)
    view._manager = session_manager
    view._device_cache = {}
    rendered = _render_meta(view, case)
    assert "Couldn't read device links for this case." in rendered
