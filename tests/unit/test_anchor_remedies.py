"""An anchor problem and a ledger problem need different remedies.

All four anchor conditions used to raise AuditTamperError, whose only remedy was "find
where the records changed / restore from backup". Restoring cannot repair an unsigned or
forged anchor file, and following that advice discards newer valid records.
"""

import pytest

from trace_core.core.errors import AnchorVerificationError, AuditTamperError


def _card(exc: Exception) -> tuple[str, str, str]:
    from trace_core.core.cli.error_handler import _resolve_error_details

    title, message, remedy, _code = _resolve_error_details(exc, None, None)
    return title, message, remedy or ""


def test_a_forged_anchor_does_not_prescribe_restoring_the_ledger() -> None:
    title, _message, remedy = _card(AnchorVerificationError("Anchor signature invalid - the file was altered"))
    assert title == "Anchor Not Trusted", title
    assert "restore from backup" not in remedy.lower(), remedy
    assert "anchor" in remedy.lower(), remedy


def test_an_unsigned_anchor_does_not_prescribe_restoring_the_ledger() -> None:
    _title, _message, remedy = _card(AnchorVerificationError("Anchor is unsigned"))
    assert "restore from backup" not in remedy.lower(), remedy


def test_genuine_ledger_tampering_still_prescribes_a_restore() -> None:
    """The split must not weaken real detection. A broken chain at the anchored position
    is still a ledger edit and keeps the restore advice."""
    title, _message, remedy = _card(AuditTamperError("record 4 no longer matches the point this anchor saved"))
    assert title == "Audit Verification Failed", title
    assert "TRACE_SECRET_KEY" in remedy, remedy


def test_an_anchor_error_is_still_caught_as_a_tamper_error() -> None:
    """Existing callers catch AuditTamperError. The subclass keeps them working."""
    assert issubclass(AnchorVerificationError, AuditTamperError)
    with pytest.raises(AuditTamperError):
        raise AnchorVerificationError("anchor is unsigned")
