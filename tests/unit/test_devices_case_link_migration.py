"""Tribunal tests for migrations 019 and 020: the device/case link."""

import pytest
from sqlalchemy import inspect, text

from trace_core.core.database.migrations import (
    CASE_DEVICES_INDEX,
    CASE_DEVICES_TABLE,
    DEVICE_CASE_COLUMN,
    DEVICE_CASE_INDEX,
    MIGRATION_OPERATIONS,
    MIGRATION_VERIFIERS,
    REQUIRED_CASE_DEVICE_COLUMNS,
    apply_migrations,
)

pytestmark = pytest.mark.unit

# Recorded by a deployed database on 2026-10-10, before 020 superseded it. Migration 19 is
# already applied in the field, so its identity is fixed: AGENTS.md 7 forbids editing an
# applied migration, and the runner enforces that by refusing to start on drift. This
# constant is what a rename or a reworded operation would change, so asserting it here is
# what stops that mistake from being made twice.
DEPLOYED_019_CHECKSUM = "795c730fa725b553f09ebf5ddcc33ea87bf589a1fa0d98bb68fce33d2431333d"

VERIFIER_019 = MIGRATION_VERIFIERS[19]
VERIFIER_020 = MIGRATION_VERIFIERS[20]


@pytest.fixture
def fresh_engine(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    apply_migrations(engine)
    yield engine
    engine.dispose()


def test_migration_19_keeps_the_identity_deployed_installs_already_recorded() -> None:
    """A deployed database stored this name and checksum; drift makes the app refuse to start.

    The name is read from the registry rather than written out here, so renaming the
    migration changes the payload and fails this test. Hardcoding it made the guard pass
    no matter what the code said.
    """
    import hashlib

    from trace_core.core.canonical import canonical_json
    from trace_core.core.database.migrations import CHECKSUM_SCHEME, MIGRATIONS

    name = next(n for v, n, _ in MIGRATIONS if v == 19)
    payload = {
        "scheme": CHECKSUM_SCHEME,
        "version": 19,
        "name": name,
        "operations": list(MIGRATION_OPERATIONS[19]),
    }
    assert hashlib.sha256(canonical_json(payload)).hexdigest() == DEPLOYED_019_CHECKSUM


def test_migration_19_is_idempotent_on_a_fresh_database(fresh_engine) -> None:
    """`create_all` at 018 builds the column, so 019 must not add it a second time."""
    assert VERIFIER_019(fresh_engine.connect()) is True


def test_a_fresh_database_carries_the_link_table_and_its_index(fresh_engine) -> None:
    inspector = inspect(fresh_engine)
    assert CASE_DEVICES_TABLE in inspector.get_table_names()
    assert REQUIRED_CASE_DEVICE_COLUMNS.issubset({c["name"] for c in inspector.get_columns(CASE_DEVICES_TABLE)})
    assert CASE_DEVICES_INDEX in {i["name"] for i in inspector.get_indexes(CASE_DEVICES_TABLE)}


def test_the_link_has_no_foreign_key_so_a_purge_cannot_cascade(fresh_engine) -> None:
    """[D29] purging a case must never reach device records, so there is no FK to cascade."""
    assert inspect(fresh_engine).get_foreign_keys(CASE_DEVICES_TABLE) == []


def test_a_link_survives_its_case_being_purged(session_manager, device_file_env):
    """The link is a claim about the past; losing it on purge would erase the association."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.devices.helpers import do_link

    svc = CaseService(session_manager)
    case = svc.create_case(CaseCreateDto(title="T", description="d", lead_examiner="Dana"))
    node = str(device_file_env / "disk-a.dd")
    do_link(session_manager, node, case.number)

    svc.close_case(case.number, "sealed", actor="Dana")
    svc.delete_case(case.number, purge=False, actor="Dana")
    svc.delete_case(case.number, purge=True, actor="Dana")

    with session_manager.session() as session:
        count = session.execute(text(f"SELECT count(*) FROM {CASE_DEVICES_TABLE}")).scalar()
    assert count == 1, "the link row must outlive the case it names"


def test_020_backfills_links_written_through_the_superseded_column(session_manager, device_file_env):
    """An observation filed under a case before 020 must still show its device afterwards."""
    from sqlalchemy import select

    from trace_core.devices.models import CaseDeviceModel, DeviceFingerprintModel

    node = str(device_file_env / "disk-a.dd")
    with session_manager.session() as session:
        session.add(
            DeviceFingerprintModel(
                node=node,
                serial="SER-1",
                model="m",
                capacity_bytes=1024,
                interface="NVME",
                source="SYNTHETIC",
                inspected_by="dana",
                case_number="2026-CR-0001",
            )
        )
        session.commit()

    from trace_core.core.database import migrations as m

    with session_manager.engine.begin() as conn:
        m._run_migration_020(conn)

    with session_manager.session() as session:
        links = session.scalars(select(CaseDeviceModel)).all()
    assert [(row.case_number, row.node, row.linked_by) for row in links] == [("2026-CR-0001", node, "dana")]


def test_the_verifier_rejects_a_missing_column(fresh_engine) -> None:
    assert VERIFIER_020(fresh_engine.connect()) is True
    with fresh_engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {CASE_DEVICES_INDEX}"))
        conn.execute(text(f"ALTER TABLE {CASE_DEVICES_TABLE} DROP COLUMN label"))
    with fresh_engine.connect() as conn:
        assert VERIFIER_020(conn) is False


def test_the_declared_operations_name_the_table_and_index() -> None:
    ops = " ".join(MIGRATION_OPERATIONS[20])
    assert CASE_DEVICES_TABLE in ops
    assert CASE_DEVICES_INDEX in ops
    assert "no foreign key" in ops
    assert "backfill" in ops


def test_the_superseded_column_is_never_written_by_an_inspection(session_manager, device_file_env) -> None:
    """020 moved the link, but the old column stays until it is contracted. Nothing reads
    or writes it, so it cannot become a second source of truth."""
    from sqlalchemy import select

    from trace_core.devices.helpers import do_inspect
    from trace_core.devices.models import DeviceFingerprintModel

    do_inspect(session_manager, str(device_file_env / "disk-a.dd"))
    with session_manager.session() as session:
        row = session.scalars(select(DeviceFingerprintModel)).one()
    assert getattr(row, DEVICE_CASE_COLUMN) is None, "inspection must not file anything under a case"
    assert DEVICE_CASE_INDEX is not None
