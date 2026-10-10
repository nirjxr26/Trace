"""Failure classes the user cannot tell apart from the exit code, or the message.

Three defects, one file, because they are the same class of problem — a script branches on
the number, and two unrelated outcomes share it:

  - exit 11 meant both "your ledger broke" and "the download isn't trusted"
  - an internal invariant breach exited 2 (usage) with "correct the highlighted field",
    so a script retrying on 2 loops forever on a broken chain-hash input
  - a path-traversal refusal exited 1 and echoed the attacker's filename back to the console
"""

import pytest


def _code(exc: Exception) -> int:
    from trace_core.core.cli.error_handler import _resolve_error_details

    return _resolve_error_details(exc, None, None)[3]


def test_ledger_tampering_and_a_bad_download_have_different_exit_codes() -> None:
    """Both exited 11. `audit verify` and `update install` failing for unrelated reasons is
    indistinguishable to anything not parsing stderr."""
    from trace_core.core.errors import AuditTamperError
    from trace_core.updates.errors import UpdateVerificationError

    ledger = _code(AuditTamperError("record 4 no longer matches"))
    download = _code(UpdateVerificationError("artifact hash mismatch"))
    assert ledger != download, f"both are {ledger}"


def test_an_artifact_refusal_is_still_a_trust_failure_code() -> None:
    from trace_core.core.cli.exit_codes import EXIT_VERIFY_FAILED
    from trace_core.updates.errors import UpdateVerificationError

    assert _code(UpdateVerificationError("bad signature")) == EXIT_VERIFY_FAILED


def test_a_traversal_refusal_does_not_echo_the_payload() -> None:
    """The filename came from an untrusted manifest. Reprinting it is what an operator then
    pastes into a bug report."""
    from trace_core.updates.verifier import safe_filename_or_exit

    payload = "../../../../etc/passwd"
    with pytest.raises(SystemExit) as caught:
        safe_filename_or_exit(payload)
    assert caught.value.code != 0
    assert payload not in str(caught.value), caught.value


def test_a_traversal_refusal_exits_with_the_verification_code() -> None:
    """SystemExit(str) exited 1, so a security refusal looked like any script failure."""
    from trace_core.core.cli.exit_codes import EXIT_VERIFY_FAILED
    from trace_core.updates.verifier import safe_filename_or_exit

    with pytest.raises(SystemExit) as caught:
        safe_filename_or_exit("../../etc/passwd")
    assert caught.value.code == EXIT_VERIFY_FAILED, caught.value.code


def test_a_safe_filename_still_passes_through() -> None:
    from trace_core.updates.verifier import safe_filename_or_exit

    assert safe_filename_or_exit("trace-1.5.0-py3-none-any.whl") == "trace-1.5.0-py3-none-any.whl"


def test_an_internal_invariant_breach_is_not_advice_about_a_form_field() -> None:
    """A broken chain-hash input is stored data, not something the operator typed. Exit 2
    plus "correct the highlighted field" sends a retrying script into a loop."""
    from trace_core.core.cli.exit_codes import EXIT_USAGE
    from trace_core.core.domain import InvariantViolationError

    exc = InvariantViolationError("chain hash inputs must both be 64-character SHA-256 hex digests")
    title, message, remedy, code = __import__(
        "trace_core.core.cli.error_handler", fromlist=["_resolve_error_details"]
    )._resolve_error_details(exc, None, None)
    assert "highlighted field" not in (remedy or ""), remedy
    assert code != EXIT_USAGE, "exit 2 tells a script to retry, which can never help here"


def test_a_real_input_violation_is_still_a_usage_error() -> None:
    """The split must not turn a typo into an internal error."""
    from trace_core.core.cli.exit_codes import EXIT_USAGE
    from trace_core.core.domain import DomainError

    assert _code(DomainError("tag exceeds maximum length of 50 characters.")) == EXIT_USAGE
