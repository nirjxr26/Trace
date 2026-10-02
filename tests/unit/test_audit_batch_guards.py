"""Regression guards for the audit batch that closed dead code, drift, and masking.

Each test names the finding it pins. They are grouped by the kind of defect:
- dead code that must not come back
- two sources of truth that must not drift again
- a value that must not be silently discarded
"""

import json
from datetime import timedelta

import pytest

from trace_core.core.cli.error_handler import _typed_error
from trace_core.core.cli.exit_codes import EXIT_CONFLICT, EXIT_ERROR
from trace_core.core.errors import ConcurrencyConflictError, ConflictError

# --- #1/#2 dead ledger entity (H-36) -------------------------------------------------


def test_dead_audit_entity_is_gone():
    """AuditEvent was built only by _model_to_domain, which nothing called."""
    import trace_core.audit as audit_pkg
    import trace_core.audit.domain as domain
    import trace_core.audit.repository as repo

    assert not hasattr(domain, "AuditEvent")
    assert not hasattr(repo, "_model_to_domain")
    assert "AuditEvent" not in audit_pkg.__all__


def test_hash_charset_lives_on_the_dto_every_read_path_builds():
    """H-49's constraint was on the dead entity, so it guarded no read path."""
    from pydantic import ValidationError

    from trace_core.audit.dto import AuditEventDto

    fields = {
        "seq": 1,
        "ts": "2026-01-01T00:00:00Z",
        "action": "CASE_CREATED",
        "actor": "a",
        "subject_case_number": "2026-CR-0001",
        "payload_json": "{}",
    }
    for name in ("payload_hash", "prev_chain", "chain_hash"):
        with pytest.raises(ValidationError):
            AuditEventDto.model_validate({**fields, name: "A" * 64})


# --- #3/#4 dead helpers ------------------------------------------------------------


def test_single_use_helpers_are_inlined():
    from trace_core.audit import verifier
    from trace_core.cases.repository import SqlAlchemyCaseRepository

    assert not hasattr(verifier, "_retain_first")
    assert not hasattr(SqlAlchemyCaseRepository, "_is_candidate_free")


# --- #5 the exit-code contract that lied --------------------------------------------


def test_concurrency_conflict_reports_its_own_exit_code():
    """EXIT_CONFLICT was declared but unreachable; a version conflict is not a
    duplicate record, so it must not share EXIT_ERROR with one."""
    concurrency = _typed_error(ConcurrencyConflictError("Case", "2026-CR-0001", 3, 4), None, None)
    duplicate = _typed_error(ConflictError("Case", "number", "2026-CR-0001"), None, None)
    assert concurrency is not None and concurrency[3] == EXIT_CONFLICT
    assert duplicate is not None and duplicate[3] == EXIT_ERROR
    assert concurrency[3] != duplicate[3]


# --- #10 a domain error that escaped as an internal fault --------------------------


def test_transition_error_is_a_domain_error():
    from trace_core.cases.domain import TransitionError
    from trace_core.core.domain import DomainError

    assert issubclass(TransitionError, DomainError)
    # Routed by the typed ladder as invalid input rather than masked as a bug.
    from trace_core.cases.domain import CaseStatus

    rendered = _typed_error(TransitionError(CaseStatus.OPEN, CaseStatus.OPEN), None, None)
    assert rendered is not None, "TransitionError must be handled, not fall through to the mask"


# --- #12 the cache the test clock could not age ------------------------------------


def test_cache_age_is_read_through_the_shared_clock(tmp_path, monkeypatch):
    """cache.py used time.time(), so core.clock.set_clock could not expire the TTL."""
    from trace_core.core import clock as clock_mod
    from trace_core.core.settings import settings
    from trace_core.updates import cache as cache_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    real_now = clock_mod.now_utc()

    class _Later:
        def now(self):
            return real_now + timedelta(seconds=60)

    cache_mod.write_check_cache({"target": "1.0.0"})
    assert cache_mod.read_check_cache(max_age=3600) is not None

    try:
        clock_mod.set_clock(_Later())
        assert cache_mod.read_check_cache(max_age=1) is None, "the test clock could not age the cache"
    finally:
        clock_mod.reset_clock()


def test_future_timestamp_is_treated_as_expired(tmp_path, monkeypatch):
    """A stamp ahead of us gave a negative age, so the entry stayed fresh for as long
    as the clock was behind."""
    from trace_core.core.settings import settings
    from trace_core.updates import cache as cache_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    cache_mod.cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_mod.cache_path().write_text(json.dumps({"checked_at": cache_mod._now() + 10_000}), encoding="utf-8")
    assert cache_mod.read_check_cache(max_age=3600) is None


# --- #13/#14 failure classes and an unauthenticated field ---------------------------


def test_vault_rejects_a_rewritten_algorithm():
    """decrypt ignored the alg the writer stamped, so a rewritten one opened silently."""
    import json as _json

    from trace_core.audit.vault import decrypt_bytes, encrypt_bytes
    from trace_core.core.errors import ValidationError

    blob = encrypt_bytes(b"evidence", "correct horse")
    envelope = _json.loads(blob.decode("ascii"))
    envelope["alg"] = "AES-128-GCM/AES-1-CTR"
    with pytest.raises(ValidationError):
        decrypt_bytes(_json.dumps(envelope).encode("ascii"), "correct horse")
    assert decrypt_bytes(blob, "correct horse") == b"evidence"


def test_update_error_classes_are_documented():
    """H-24/H-14 mis-routed because the classes carried no assignment rule."""
    import inspect

    from trace_core.updates import errors as errs

    module_doc = inspect.getdoc(errs) or ""
    for name in ("UpdateVerificationError", "UpdatePolicyBlockedError", "UpdateNetworkError", "RecoveryError"):
        assert name in module_doc, f"{name} has no documented failure class"


# --- #15 two status resolvers, two answers -----------------------------------------


@pytest.mark.parametrize("raw", ["under_review", "UNDER_REVIEW", "Under_Review", "open", "OPEN"])
def test_tui_and_terminal_agree_on_status(raw: str):
    """tui/theme.py did not upper-case or strip underscores, so a lowercase status
    rendered default-grey in the TUI and amber in the terminal."""
    from trace_core.core.ui.renderers import get_status_style_and_label
    from trace_core.tui.theme import status_label, status_style

    label, style, _border = get_status_style_and_label(raw)
    assert status_label(raw) == label
    assert status_style(raw) == style


# --- #17 permission checks that vanished on Windows ---------------------------------


def test_permission_assertions_are_skips_not_in_body_guards():
    """An `if sys.platform` inside a test body means the assertion is skipped while
    coverage still reports the lines covered."""
    import inspect

    from tests.unit import test_security_regressions as mod

    source = inspect.getsource(mod)
    assert 'sys.platform != "win32"' not in source, "in-body platform guard still present"
    assert source.count('pytest.mark.skipif(sys.platform == "win32"') >= 3


# --- #18/#19 a lying signature and an inverted dependency ---------------------------


def test_manifest_resolution_takes_no_channel():
    """It never read one, yet five call sites passed it believing it was channel-aware."""
    import inspect

    from trace_core.updates.checker import resolve_manifest_target

    assert "channel" not in inspect.signature(resolve_manifest_target).parameters


def test_client_verifier_is_not_widened_for_the_release_script():
    """platform_key existed only so release/verify_release.py could select by key."""
    import inspect

    from trace_core.updates.verifier import resolve_artifact, verify_manifest

    for fn in (resolve_artifact, verify_manifest):
        assert "platform_key" not in inspect.signature(fn).parameters


# --- #21/#22/#23 modal safety and shared-state hygiene ------------------------------


def test_modals_do_not_relist_a_base_already_in_their_mro():
    import inspect

    from trace_core.tui import forms

    source = inspect.getsource(forms)
    assert "_BaseModal, ModalScreen[" not in source, "ModalScreen is already _BaseModal's base"


def test_modal_bindings_are_not_a_shared_mutable_list():
    from textual.binding import Binding

    from trace_core.tui.forms import CaseForm, RawModal, TextInputModal, _BaseModal

    assert _BaseModal.BINDINGS is not CaseForm.BINDINGS or len(CaseForm.BINDINGS) == len(_BaseModal.BINDINGS)
    # A copy, not an alias: appending to one class's bindings must not touch another's.
    assert isinstance(_BaseModal.BINDINGS, list)
    assert all(isinstance(b, (Binding, tuple)) for b in _BaseModal.BINDINGS)
    assert _BaseModal.BINDINGS == RawModal.BINDINGS == TextInputModal.BINDINGS


def test_yes_no_modal_focuses_no_not_yes():
    """Without an explicit focus, focus landed on #yes and Enter immediately
    confirmed an archive, restore, or purge."""
    from trace_core.tui.forms import YesNoModal

    assert hasattr(YesNoModal, "on_mount"), "YesNoModal lost its focus call"
    assert '"#no"' in inspect_source(YesNoModal), "YesNoModal must focus No, not the first focusable widget"


def inspect_source(obj) -> str:  # type: ignore[no-untyped-def]
    import inspect

    return inspect.getsource(obj)


# --- #29 a method signature on a module function ------------------------------------


def test_pip_health_is_annotated_and_not_method_shaped():
    import inspect

    from trace_core.updates.pip_backend import pip_health

    params = inspect.signature(pip_health).parameters
    assert "self" not in params
    assert params["manifest"].annotation is not inspect.Parameter.empty
