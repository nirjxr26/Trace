"""An anchor is the only external witness that records were not deleted.

Two holes let a truncated ledger pass: an empty ledger skipped the tip comparison entirely
(last_seq is None, so `exp_seq > res.last_seq` was False), and a deleted anchored row left
anchored_chain None, which skipped the tail comparison.
"""

import json

import pytest


def _signed(envelope: dict) -> dict:
    from trace_core.audit.signing import sign_bytes
    from trace_core.core.canonical import canonical_json

    key_id, signature = sign_bytes(canonical_json(envelope))
    return {**envelope, "key_id": key_id, "signature": signature}


@pytest.fixture()
def svc(session_manager):
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    CaseService(session_manager).create_case(CaseCreateDto(title="Anchor subject", lead_examiner="Ex"))
    return AuditService(session_manager)


def _verify(svc, envelope: dict, anchor_path) -> None:
    from trace_core.audit.anchor import verify_against_anchor

    anchor_path.write_text(json.dumps(envelope), encoding="utf-8")
    verify_against_anchor(svc, svc.verify(), str(anchor_path))


def test_an_anchor_against_an_empty_ledger_is_a_mismatch_not_a_pass(svc, tmp_path) -> None:
    """`last_seq is None` made `exp_seq > res.last_seq` False, so an emptied ledger
    accepted an anchor naming records it no longer had."""
    from trace_core.core.errors import AnchorVerificationError

    empty = type(svc.verify())
    res = empty(is_valid=True, events_verified=0)
    with pytest.raises(AnchorVerificationError, match="another ledger"):
        from trace_core.audit.anchor import check_anchor_match

        check_anchor_match(res, _signed({"last_seq": 9, "last_chain": "a" * 64}), None)


def test_a_deleted_anchored_row_is_reported_not_skipped(svc, tmp_path) -> None:
    """`get_by_seq` returning None left anchored_chain None, and the tail comparison is
    guarded on it being truthy — so the record the anchor witnessed could vanish silently."""
    from trace_core.core.errors import AnchorVerificationError

    seq, chain = svc.head()
    envelope = _signed({"last_seq": seq, "last_chain": chain})
    res = svc.verify()

    class _Svc:
        def get_by_seq(self, _seq):  # type: ignore[no-untyped-def]
            return None

    from trace_core.audit.anchor import verify_against_anchor

    anchor_path = tmp_path / "anchor.json"
    anchor_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(AnchorVerificationError, match="no longer in the ledger"):
        verify_against_anchor(_Svc(), res, str(anchor_path))


def test_an_anchor_file_that_is_not_an_object_is_a_readable_error(svc, tmp_path) -> None:
    """Valid JSON that is not a dict reached `.get` and raised AttributeError, which
    `capture_cli_errors` reported as an unexpected operational error."""
    from trace_core.core.errors import ValidationError

    anchor_path = tmp_path / "anchor.json"
    anchor_path.write_text("[1, 2, 3]", encoding="utf-8")
    from trace_core.audit.anchor import verify_against_anchor

    with pytest.raises(ValidationError, match="not an anchor"):
        verify_against_anchor(svc, svc.verify(), str(anchor_path))


def test_an_intact_anchor_still_passes(svc, tmp_path) -> None:
    """The three holes above must not have broken the working case."""
    seq, chain = svc.head()
    _verify(svc, _signed({"last_seq": seq, "last_chain": chain}), tmp_path / "anchor.json")
