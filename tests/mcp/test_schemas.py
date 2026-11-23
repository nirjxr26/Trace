import pytest
from pydantic import ValidationError

from trace_core.mcp.schemas import AuditExportArgs, CaseListArgs, DeviceLinksArgs, UninstallArgs


def test_case_list_bounds() -> None:
    with pytest.raises(ValidationError):
        CaseListArgs(limit=0)
    with pytest.raises(ValidationError):
        CaseListArgs(limit=201)


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        CaseListArgs.model_validate({"actor": "admin"})


def test_device_links_requires_exactly_one_target() -> None:
    with pytest.raises(ValidationError):
        DeviceLinksArgs()
    with pytest.raises(ValidationError):
        DeviceLinksArgs(case_number="2026-CR-0001", node="/dev/sda")


def test_bundle_filename_rejects_traversal() -> None:
    with pytest.raises(ValidationError):
        AuditExportArgs(filename="../secret.jsonl")
    with pytest.raises(ValidationError):
        AuditExportArgs(filename="/tmp/bundle.jsonl")


def test_uninstall_confirmation() -> None:
    with pytest.raises(ValidationError):
        UninstallArgs(confirm="yes")
    assert UninstallArgs(confirm="UNINSTALL").confirm == "UNINSTALL"
