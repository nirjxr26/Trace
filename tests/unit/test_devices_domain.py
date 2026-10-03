"""Device domain contract tests: frozen representation, bounds, UTC, D19, D27."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from trace_core.devices.domain import (
    DeviceFingerprint,
    DeviceInfo,
    DeviceInspection,
    DeviceInterface,
    DeviceKind,
    DevicePreflight,
    GateCheck,
    ObservedSerial,
    ProtectionCheck,
    ProtectionEvidence,
    UnknownCause,
    WpVerdict,
)

pytestmark = pytest.mark.unit

STAMP = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _serial(value: str = "SERIAL-1") -> ObservedSerial:
    return ObservedSerial(value=value)


def test_observed_serial_is_not_a_bare_string() -> None:
    assert ObservedSerial(value="SERIAL-1").value == "SERIAL-1"
    with pytest.raises(ValidationError):
        ObservedSerial(value=cast(str, 1))


def _fingerprint(
    serial: ObservedSerial | None = None,
    model: str = "Samsung SSD",
    capacity_bytes: int = 500_000_000_000,
    firmware: str | None = "SVT02B6Q",
    interface: DeviceInterface = DeviceInterface.NVME,
    wwn: str | None = None,
    source: Literal["os", "smartctl", "synthetic"] = "os",
) -> DeviceFingerprint:
    return DeviceFingerprint(
        serial=_serial() if serial is None else serial,
        model=model,
        capacity_bytes=capacity_bytes,
        firmware=firmware,
        interface=interface,
        wwn=wwn,
        source=source,
    )


def _info(
    node: str = "/dev/nvme0n1",
    kind: DeviceKind = DeviceKind.OS,
    requires_real_hardware_opt_in: bool = True,
    size_bytes: int | None = 500_000_000_000,
    model_hint: str | None = "Samsung SSD 980",
) -> DeviceInfo:
    return DeviceInfo(
        node=node,
        kind=kind,
        requires_real_hardware_opt_in=requires_real_hardware_opt_in,
        size_bytes=size_bytes,
        model_hint=model_hint,
    )


def _evidence(
    platform: Literal["linux", "windows", "fake"] = "linux",
    checks: tuple[ProtectionCheck, ...] | None = None,
    adapter_version: str = "0.2.8",
    checked_at: datetime = STAMP,
    unknown_cause: UnknownCause | None = None,
) -> ProtectionEvidence:
    return ProtectionEvidence(
        platform=platform,
        checks=(ProtectionCheck(name="blkroget", result="1"),) if checks is None else checks,
        adapter_version=adapter_version,
        checked_at=checked_at,
        unknown_cause=unknown_cause,
    )


def _gate(
    verdict: WpVerdict = WpVerdict.READ_ONLY,
    evidence: ProtectionEvidence | None = None,
    checked_at: datetime = STAMP,
) -> GateCheck:
    return GateCheck(
        verdict=verdict,
        evidence=_evidence() if evidence is None else evidence,
        checked_at=checked_at,
    )


def test_device_contracts_are_frozen() -> None:
    inspection = DeviceInspection(device=_info(), fingerprint=_fingerprint(), inspected_at=STAMP)
    with pytest.raises(ValidationError):
        inspection.inspected_at = STAMP  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _serial().value = "tampered"  # type: ignore[misc]


def test_unknown_verdict_requires_a_cause() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _gate(WpVerdict.UNKNOWN)
    assert "unknown_cause" in str(excinfo.value)


@pytest.mark.parametrize("cause", list(UnknownCause))
def test_every_unknown_cause_satisfies_the_gate(cause: UnknownCause) -> None:
    gate = _gate(WpVerdict.UNKNOWN, evidence=_evidence(unknown_cause=cause))
    assert gate.evidence.unknown_cause is cause


def test_device_kind_is_separate_from_the_opt_in_property() -> None:
    loopback = _info(kind=DeviceKind.OS, requires_real_hardware_opt_in=False)
    assert loopback.kind is DeviceKind.OS
    assert loopback.requires_real_hardware_opt_in is False
    assert _info(kind=DeviceKind.FILE, requires_real_hardware_opt_in=True).kind is DeviceKind.FILE


def test_naive_timestamps_are_rejected() -> None:
    naive = datetime(2026, 10, 3, 12, 0)
    with pytest.raises(ValidationError):
        DeviceInspection(device=_info(), fingerprint=_fingerprint(), inspected_at=naive)
    with pytest.raises(ValidationError):
        _gate(checked_at=naive)


def test_aware_timestamps_are_coerced_to_utc() -> None:
    shifted = datetime(2026, 10, 3, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    inspection = DeviceInspection(device=_info(), fingerprint=_fingerprint(), inspected_at=shifted)
    offset = inspection.inspected_at.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
    assert inspection.inspected_at.hour == 12


def test_hostile_device_strings_are_truncated_not_accepted() -> None:
    oversized = "A" * 5000
    fingerprint = _fingerprint(model=oversized, firmware=oversized)
    assert len(fingerprint.model) == 512
    assert fingerprint.firmware is not None
    assert len(fingerprint.firmware) == 512
    assert len(_info(node="/" + "B" * 5000).node) == 4096


def test_control_characters_are_stripped() -> None:
    fingerprint = _fingerprint(model="Samsung\x00\x07 SSD")
    assert fingerprint.model == "Samsung SSD"


def test_negative_capacity_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _fingerprint(capacity_bytes=-1)
    with pytest.raises(ValidationError):
        _info(size_bytes=-1)


def test_preflight_pairs_inspection_with_gate() -> None:
    preflight = DevicePreflight(
        inspection=DeviceInspection(device=_info(), fingerprint=_fingerprint(), inspected_at=STAMP),
        gate=_gate(),
    )
    assert preflight.inspection.fingerprint.serial.value == "SERIAL-1"
    assert preflight.gate.verdict is WpVerdict.READ_ONLY


def test_unknown_cause_is_allowed_on_a_non_unknown_verdict() -> None:
    """A probe may record a warning-grade cause alongside a decided verdict.

    [D19] mandates a cause when the verdict is UNKNOWN; it does not forbid one
    otherwise. A READ_ONLY device whose probe hit EACCES on a secondary check is
    still READ_ONLY, and discarding that evidence would lose the reason.
    """
    gate = _gate(WpVerdict.READ_ONLY, evidence=_evidence(unknown_cause=UnknownCause.EACCES))
    assert gate.evidence.unknown_cause is UnknownCause.EACCES


def test_device_adapter_defaults_to_file_and_cannot_bypass_the_opt_in() -> None:
    """[D27] The env var selects the adapter only; the flag remains required."""
    from trace_core.core.settings import Settings

    # Fields are alias-driven, so the constructor takes the env alias.
    assert Settings().device_adapter == "file"
    assert Settings(TRACE_DEVICE_ADAPTER="linux").device_adapter == "linux"
    with pytest.raises(ValidationError):
        Settings.model_validate({"TRACE_DEVICE_ADAPTER": "root_privileges"})

    linux = _info(kind=DeviceKind.OS, requires_real_hardware_opt_in=True)
    assert linux.requires_real_hardware_opt_in is True
