"""Global pytest test configuration and shared fixtures for Trace."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from trace_core.cases.dto import CaseCreateDto, CaseResponseDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Set standard environment variables for isolated testing.

    H-78: the storage default was the relative './.test_storage'. install_root() and
    trust_root() derive from storage_root, so every derived root landed in the checkout —
    CI wrote anchors, signing keys, the update lock and the check cache into the repository
    on each run. An absolute per-session tmp directory keeps all of that out of the tree.

    The global `db_manager` is rebound as well, not just the environment variable.
    `core/database/session.py` builds it at import time, so it captured whatever
    TRACE_DATABASE_URL the repo `.env` held — the operator's real database. Any test reaching
    a service with no explicit manager (the device CLI tests do, via `helpers.do_*`) then
    wrote observations and ledger rows into it. Setting the variable afterwards cannot undo
    an object that was already constructed, so this rebinds it.
    """
    from trace_core.core import service as core_service

    os.environ["TRACE_DATABASE_URL"] = "sqlite:///:memory:"
    storage_root = tmp_path_factory.mktemp("trace-test-storage") / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    os.environ["TRACE_STORAGE_ROOT"] = str(storage_root)
    core_service.db_manager = DatabaseSessionManager("sqlite:///:memory:")


@pytest.fixture
def temp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated temporary evidence storage directory."""
    storage_dir = tmp_path / "evidence_store"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRACE_STORAGE_ROOT", str(storage_dir))
    return storage_dir


@pytest.fixture
def device_box(tmp_path: Path) -> Path:
    """Two seeded synthetic disks. Single source for every device-suite file adapter."""
    from trace_core.devices import synthetic

    synthetic.write_disk(tmp_path / "disk-a.dd", size=2048)
    synthetic.write_disk(tmp_path / "disk-b.dd", seed=b"other", size=1024)
    return tmp_path


@pytest.fixture
def device_file_env(device_box: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Select the file adapter rooted at `device_box`. Returns the root."""
    from trace_core.devices.service import ENV_ADAPTER, ENV_DEVICE_ROOT

    monkeypatch.setenv(ENV_ADAPTER, "file")
    monkeypatch.setenv(ENV_DEVICE_ROOT, str(device_box))
    return device_box


@pytest.fixture
def session_manager() -> DatabaseSessionManager:
    """Provide a fresh in-memory SQLite database session manager with schema initialized."""
    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    return mgr


@pytest.fixture(autouse=True)
def tests_never_touch_the_real_database() -> None:
    """Fail loudly if any test could reach the operator's actual database.

    `db_manager` is constructed at import time and would otherwise carry the repo `.env`
    URL, so a test reaching a service without an explicit manager writes to the real
    forensic ledger. That happened: 667 synthetic observations landed in `trace`. The
    rows cannot be removed — the ledger and the observation store are append-only — so the
    only available remedy is to stop the next run reaching it, and prove it stopped.
    """
    from trace_core.core import service as core_service

    url = str(core_service.db_manager.engine.url)
    assert "sqlite" in url or "memory" in url, f"tests are bound to a real database: {url}"


@pytest.fixture
def service(session_manager: DatabaseSessionManager) -> CaseService:
    """Provide an isolated CaseService instance wired to an in-memory database."""
    return CaseService(session_manager)


@pytest.fixture
def sample_case_dto() -> CaseCreateDto:
    """Provide a standard, valid CaseCreateDto fixture."""
    return CaseCreateDto(
        number="2026-FIXTURE-0001",
        title="Automated Test Investigation",
        lead_examiner="Forensic Lead Examiner",
        description="Standard test case fixture for integration and unit flows",
        tags=["test", "fixture", "forensics"],
    )


@pytest.fixture
def sample_case(service: CaseService, sample_case_dto: CaseCreateDto) -> CaseResponseDto:
    """Provide a pre-created active case in the isolated database."""
    return service.create_case(sample_case_dto)


@pytest.fixture
def sample_cases_batch(service: CaseService) -> list[CaseResponseDto]:
    """Provide a batch of pre-created cases for search, filter, and pagination tests."""
    dtos = [
        CaseCreateDto(
            number="2026-BATCH-0001",
            title="Active Network Intrusion",
            lead_examiner="Examiner Alpha",
            tags=["network", "intrusion"],
        ),
        CaseCreateDto(
            number="2026-BATCH-0002",
            title="Malware Reverse Engineering",
            lead_examiner="Examiner Beta",
            tags=["malware", "reverse-engineering"],
        ),
        CaseCreateDto(
            number="2026-BATCH-0003",
            title="Insider Threat Assessment",
            lead_examiner="Examiner Gamma",
            tags=["insider", "audit"],
        ),
    ]
    return [service.create_case(dto) for dto in dtos]


def make_case(service: CaseService, title: str = "Test Case", examiner: str = "Ex") -> CaseResponseDto:
    """Single source for case creation in tests. Reusable."""
    return service.create_case(CaseCreateDto(title=title, lead_examiner=examiner))


@pytest.fixture
def temp_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the global settings storage root at an isolated tmp dir. Restores after.

    H-78: this used to be `tmp_path` itself, so `install_root()` and `trust_root()` —
    which derive from `storage_root.parent` — resolved to pytest's shared per-session
    parent. Every test in the session wrote anchors, signing keys, the update lock and
    the check cache to the same place, and under the relative `./.test_storage` default
    that place was `./install` and `./trust/releases` *inside the checkout*. The nested
    "storage" dir keeps every derived root under this test's own tmp_path.
    """
    from trace_core.core.settings import settings

    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "storage_root", storage_root)
    return storage_root


@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """Single AnyIO backend fixture for every async test (was copy-pasted in 3 files)."""
    return request.param


@pytest.fixture
def as_user(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Run subsequent service calls as another OS user. Returns a setter."""

    def _as(name: str) -> None:
        monkeypatch.setattr("trace_core.core.operators.current_identity", lambda: (name, "workstation"))

    return _as


@pytest.fixture
def detached_event(session_manager: DatabaseSessionManager):  # type: ignore[no-untyped-def]
    """Transient copy of the seq-1 ledger row for envelope forgery tests (no DB writes)."""
    from sqlalchemy import select

    from trace_core.audit.models import AuditEventModel

    make_case(CaseService(session_manager))
    with session_manager.session() as session:
        m = session.scalars(select(AuditEventModel).where(AuditEventModel.seq == 1)).one()
        return AuditEventModel(
            seq=m.seq,
            ts=m.ts,
            action=m.action,
            actor=m.actor,
            subject_case_number=m.subject_case_number,
            subject_case_id=m.subject_case_id,
            payload_json=m.payload_json,
            payload_hash=m.payload_hash,
            prev_chain=m.prev_chain,
            chain_hash=m.chain_hash,
            key_id=m.key_id,
            signature=m.signature,
        )
