import pytest

from trace_core.updates.domain import UpdateChannel
from trace_core.updates.gate import ForensicOperationGate, GateDecision
from trace_core.updates.policy import _parse_version, is_installable, is_update_available, security_label


def test_version_ordering():
    assert _parse_version("1.10.0") > _parse_version("1.9.0")
    assert _parse_version("1.4.0a1") < _parse_version("1.4.0")
    assert _parse_version("1.5.0-beta.1") < _parse_version("1.5.0")
    with pytest.raises(ValueError):
        _parse_version("not-a-version")


def test_availability(signed_release):
    manifest, _, _, _ = signed_release(version="1.5.0")
    assert is_update_available("0.1.0", manifest) is True
    assert is_update_available("1.5.0", manifest) is False
    assert is_update_available("9.9.9", manifest) is False


def test_beta_blocked_on_stable(signed_release):
    manifest, _, _, _ = signed_release(channel="beta")
    ok, reason = is_installable("0.1.0", manifest, "stable")
    assert ok is False
    assert reason


def test_minimum_supported_version(signed_release):
    manifest, _, _, _ = signed_release(minimum_supported_version="1.4.0")
    ok, _ = is_installable("0.1.0", manifest, "stable")
    assert ok is False
    ok, _ = is_installable("1.4.0", manifest, "stable")
    assert ok is True


def test_forensic_active_defers(signed_release):
    manifest, _, _, _ = signed_release()
    ok, reason = is_installable("0.1.0", manifest, "stable", forensic_active=True)
    assert ok is False
    assert reason is not None
    assert "forensic" in reason


def test_gate_unknown_fails_closed():
    class UnknownGate(ForensicOperationGate):
        def can_install_update(self):
            return GateDecision.UNKNOWN

    assert UnknownGate().can_install_update() == GateDecision.UNKNOWN


def test_security_label_deterministic(signed_release):
    manifest, _, _, _ = signed_release(security_update=True, minimum_supported_version="1.4.0")
    label = security_label(manifest)
    assert label == "Security update — minimum supported version: 1.4.0"
    plain, _, _, _ = signed_release()
    assert security_label(plain) is None


def test_channels_are_enum():
    assert UpdateChannel.STABLE == "stable"
    assert UpdateChannel.BETA == "beta"
    assert "nightly" not in [c.value for c in UpdateChannel]
