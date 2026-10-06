"""Tribunal tests for the shared subprocess helpers both OS adapters use."""

import pytest

from trace_core.devices import _subprocess
from trace_core.devices._subprocess import HelperFailure
from trace_core.devices.domain import DeviceInterface, UnknownCause

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (b"smartctl 7.4 2023-08-01 r5530\n", None),
        (b"smartctl 5.16 2020-01-01 r5122\n", None),
        (b"smartctl 5.15 2019-01-01 r4882\n", UnknownCause.TOOL_TOO_OLD),
        (b"smartctl 5.16.1 2020-01-01 r5123\n", None),
        (b"", UnknownCause.TOOL_MISSING),
        (b"unparseable\n", UnknownCause.TOOL_MISSING),
    ],
)
def test_smartctl_readiness_names_absence_and_staleness_apart(
    monkeypatch: pytest.MonkeyPatch, version: bytes, expected: UnknownCause | None
) -> None:
    """[D22] absent is TOOL_MISSING, present-but-old is TOOL_TOO_OLD. Never the reverse."""
    monkeypatch.setattr(_subprocess, "run_capped", lambda argv, **k: version)
    assert _subprocess.smartctl_readiness() is expected


def test_smartctl_readiness_survives_an_unstartable_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    def _absent(argv, **k):
        raise HelperFailure(UnknownCause.TOOL_MISSING, "no smartctl")

    monkeypatch.setattr(_subprocess, "run_capped", _absent)
    assert _subprocess.smartctl_readiness() is UnknownCause.TOOL_MISSING


def test_smartctl_readiness_survives_a_hung_version_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _hung(argv, **k):
        raise HelperFailure(UnknownCause.SMARTCTL_TIMEOUT, "hung")

    monkeypatch.setattr(_subprocess, "run_capped", _hung)
    assert _subprocess.smartctl_readiness() is UnknownCause.TOOL_MISSING


def test_the_device_type_map_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """[D20] the `-d` chain is a closed mapping, identical for both adapters."""
    assert _subprocess.SMARTCTL_TYPES == {
        DeviceInterface.USB: "usb",
        DeviceInterface.SATA: "sat",
        DeviceInterface.NVME: "nvme",
        DeviceInterface.SCSI: "scsi",
    }
    assert DeviceInterface.UNKNOWN not in _subprocess.SMARTCTL_TYPES
    assert DeviceInterface.VIRTUAL not in _subprocess.SMARTCTL_TYPES


def test_neither_adapter_keeps_its_own_device_type_map() -> None:
    from trace_core.devices import _subprocess, linux, win32

    assert linux.SMARTCTL_TYPES is _subprocess.SMARTCTL_TYPES
    assert win32.SMARTCTL_TYPES is _subprocess.SMARTCTL_TYPES


@pytest.mark.parametrize(
    ("document", "key", "expected"),
    [
        ({"wwn": "0xabc"}, "wwn", "0xabc"),
        ({"outer": {"wwn": " 0xabc "}}, "wwn", "0xabc"),
        ({"items": [{"nope": 1}, {"wwn": "0x2"}]}, "wwn", "0x2"),
        ({"wwn": "   "}, "wwn", None),
        ({"wwn": 42}, "wwn", None),
        ({"other": 1}, "wwn", None),
        ([{"wwn": "0x9"}], "wwn", "0x9"),
        ("not-a-document", "wwn", None),
        (None, "wwn", None),
    ],
)
def test_deep_text_finds_the_first_usable_string(document: object, key: str, expected: str | None) -> None:
    assert _subprocess.deep_text(document, key) == expected


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"smartctl": {"exit_status": 0}}, True),
        ({}, True),
        ({"smartctl": {}}, True),
        ({"smartctl": {"exit_status": 1}}, False),
        ({"smartctl": {"exit_status": 4}}, False),
        ({"smartctl": None}, True),
    ],
)
def test_smartctl_succeeded_reads_only_the_exit_status(document: dict, expected: bool) -> None:
    assert _subprocess.smartctl_succeeded(document) is expected
