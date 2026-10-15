"""Messages that claim more than the code checked.

Every test here asserts the rendered text, not an enum, because the defect was always in
the wording: the code returned a correct value and the screen said something the value did
not support.
"""

import pytest


@pytest.fixture
def out(capsys):
    """Rendered card as plain text. Rich wraps rows, so this collapses whitespace —
    otherwise a phrase split across two lines never matches."""
    from trace_core.audit.renderers import render_verify_result

    class _Out:
        def __call__(self, res, anchor=None) -> str:
            render_verify_result(res, anchor)
            return " ".join(capsys.readouterr().out.split())

    return _Out()


def test_an_empty_ledger_is_not_reported_as_valid(out) -> None:
    """`verify_rows` returns is_valid=True for zero rows, so an emptied ledger rendered
    "✓ VALID / No tampering. Ledger intact." An empty ledger is what a fully truncated one
    looks like, and that is not a clean bill of health."""
    from trace_core.audit.dto import VerifyResultDto

    text = out(VerifyResultDto(is_valid=True, events_verified=0))
    assert "EMPTY" in text, text
    assert "VALID" not in text, text
    assert "Ledger intact" not in text, text
    assert "does not prove the ledger is intact" in text, text
    assert "trace doctor" in text, text


def test_a_populated_ledger_does_not_imply_nothing_is_missing(out) -> None:
    """`verify_event` cannot detect deletion, and neither can a full verify without an
    anchor. Saying only "No tampering" reads as proof of completeness."""
    from trace_core.audit.dto import VerifyResultDto

    text = out(VerifyResultDto(is_valid=True, events_verified=3, first_seq=1, last_seq=3))
    assert "VALID" in text, text
    assert "Every record checked matched" in text, text
    assert "does not prove no records are missing" in text, text
    assert "Ledger intact" not in text, text


def test_gaps_are_not_labelled_rolled_back(out) -> None:
    """A sequence gap is equally consistent with a rolled-back append and with a deleted
    row. Nothing in the schema records which, so asserting the benign cause is a claim
    with no evidence behind it."""
    from trace_core.audit.dto import VerifyResultDto

    text = out(VerifyResultDto(is_valid=True, events_verified=3, first_seq=1, last_seq=4, sequence_gaps=[2]))
    assert "rolled-back" not in text, text
    assert "not tampering" not in text, text
    assert "2" in text, text


def test_an_empty_ledger_supplied_an_anchor_names_the_mismatch(out) -> None:
    from trace_core.audit.dto import VerifyResultDto

    text = out(VerifyResultDto(is_valid=True, events_verified=0), anchor="anchor.json")
    assert "EMPTY" in text, text
    assert "does not have" in text, text


def test_a_valid_card_shows_no_hash_internals(out) -> None:
    from trace_core.audit.dto import VerifyResultDto

    text = out(VerifyResultDto(is_valid=True, events_verified=3, first_seq=1, last_seq=3))
    assert "VALID" in text, text
    assert "SHA-256" not in text, text
    assert "recomputed" not in text, text
    assert "trace-canonical-json-v1" not in text, text


def test_a_tamper_card_names_the_seq_without_hash_dumps(out) -> None:
    from trace_core.audit.dto import VerifyResultDto

    text = out(
        VerifyResultDto(
            is_valid=False,
            events_verified=3,
            first_mismatch_seq=4,
            mismatch_type="chain_hash",
            expected_chain_hash="a" * 64,
            actual_chain_hash="b" * 64,
        )
    )
    assert "TAMPER" in text, text
    assert "Seq 4" in text, text
    assert "a" * 64 not in text, text
    assert "b" * 64 not in text, text


def test_an_event_card_shows_the_seal_without_hash_rows(session_manager, capsys) -> None:  # type: ignore[no-untyped-def]
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.renderers import render_audit_detail
    from trace_core.audit.repository import SqlAlchemyAuditRepository

    with session_manager.session() as session:
        dto = SqlAlchemyAuditRepository(session).append(
            AuditAction.CASE_CREATED, "Ex", "2026-CR-0001", None, {}, subject_type="case"
        )
        session.commit()
    render_audit_detail(dto)
    text = " ".join(capsys.readouterr().out.split())
    assert "VERIFIED" in text, text
    assert "Payload Hash" not in text, text
    assert "Previous Chain" not in text, text
    assert "Chain Hash" not in text, text
