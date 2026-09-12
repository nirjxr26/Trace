"""Global pytest test configuration and shared fixtures for Trace."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trace_core.cases.dto import CaseCreateDto, CaseResponseDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment() -> None:
    """Set standard environment variables for isolated testing."""
    os.environ["TRACE_DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["TRACE_STORAGE_ROOT"] = "./.test_storage"


@pytest.fixture
def temp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated temporary evidence storage directory."""
    storage_dir = tmp_path / "evidence_store"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRACE_STORAGE_ROOT", str(storage_dir))
    return storage_dir


@pytest.fixture
def session_manager() -> DatabaseSessionManager:
    """Provide a fresh in-memory SQLite database session manager with schema initialized."""
    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    return mgr


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


@pytest.fixture
def cli_runner(monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager) -> CliRunner:
    """Provide a Typer CliRunner pre-isolated with an in-memory database."""
    monkeypatch.setattr("trace_core.cases.commands.db_manager", session_manager)
    return CliRunner()
