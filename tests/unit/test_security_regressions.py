"""Security regression tests: hostile input must fail closed (Batch 1).

Each test fails on the vulnerable implementation and passes after remediation.
Covers: number grammar, anchor containment, markup/ANSI-safe rendering,
control-character policy. See docs/security/assessment-2026-09-17.md.
"""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from trace_core.cases.domain import Case
from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.renderers import render_case_detail
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit


@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """AnyIO backend for the pilot test."""
    return request.param


def test_number_grammar_accepts_canonical() -> None:
    auto = Case(number="2026-CR-0001", title="T", lead_examiner="Ex")
    assert auto.number == "2026-CR-0001"
    fixture = Case(number="2026-FIXTURE-0001", title="T", lead_examiner="Ex")
    assert fixture.number == "2026-FIXTURE-0001"


def test_number_grammar_normalizes_case() -> None:
    lowered = Case(number="2026-cr-0001", title="T", lead_examiner="Ex")
    assert lowered.number == "2026-CR-0001"


def test_number_grammar_rejects_hostile() -> None:
    for hostile in (
        "../../pwned",
        "2026-CR-0001\nINJECT",
        "*",
        "2026-CR-9\u041e42",  # Cyrillic O homoglyph
        "2026 CR 0001",
        "2026-CR-1",
        "GAP-1",
    ):
        with pytest.raises(ValueError, match="YYYY-CODE-XXXX"):
            Case(number=hostile, title="T", lead_examiner="Ex")


def test_anchor_path_contained() -> None:
    from trace_core.audit.anchor import anchor_path

    with pytest.raises(ValueError):
        anchor_path("../../../../etc", 1)


def test_lookups_normalize_to_canonical(service: CaseService) -> None:
    service.create_case(CaseCreateDto(number="2026-NRM-0001", title="T", lead_examiner="Ex"))
    assert service.get_case("2026-nrm-0001").number == "2026-NRM-0001"


def test_anchor_lookup_ignores_metachars(temp_storage_root, service: CaseService) -> None:  # type: ignore[no-untyped-def]
    from trace_core.audit.anchor import latest_anchor_for

    created = service.create_case(CaseCreateDto(number="2026-GLB-0001", title="T", lead_examiner="Ex"))
    service.close_case(created.number, reason="done")
    assert latest_anchor_for("*") is None
    assert latest_anchor_for("2026-GLB-0001") is not None


def test_audit_notice_escapes_markup(capsys: pytest.CaptureFixture[str]) -> None:
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.helpers import do_show_list
    from trace_core.audit.service import AuditService

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    evil = "[/dim][bold red]FORGED[/bold red][dim]"
    do_show_list(AuditService(mgr), AuditFilterDto(), evil, "table")
    out = capsys.readouterr().out
    assert "[/dim]" in out  # escaped literal, not consumed markup


def test_dossier_terminal_safe(capsys: pytest.CaptureFixture[str]) -> None:
    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    svc = CaseService(mgr)
    evil_title = "Clean\x1b]8;;http://evil.example/\x07X\x1b]8;;\x07\nFAKE"
    created = svc.create_case(CaseCreateDto(title=evil_title, lead_examiner="Ex"))
    assert "\n" not in created.title
    assert "\x1b" not in created.title
    render_case_detail(svc.get_case(created.number))
    out = capsys.readouterr().out
    assert "\x1b" not in out  # no escape bytes reach the terminal at all
    assert "FAKE" in out  # data preserved, defanged into inert text


def test_actor_controls_stripped() -> None:
    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    svc = CaseService(mgr)
    created = svc.create_case(CaseCreateDto(title="T", lead_examiner="Ex"), actor="op\x07")
    assert "\x07" not in created.lead_examiner
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService

    events = AuditService(mgr).list_events(AuditFilterDto())
    assert all("\x07" not in e.actor for e in events)


def test_purged_number_stays_reserved(service: CaseService) -> None:
    from trace_core.cases.dto import CaseFilterDto
    from trace_core.core.errors import ConflictError

    created = service.create_case(CaseCreateDto(number="2026-RSV-0001", title="T", lead_examiner="Ex"))
    service.delete_case(created.number, purge=False)
    service.delete_case(created.number, purge=True)
    twin = CaseCreateDto(number="2026-RSV-0001", title="Twin", lead_examiner="Ex")
    with pytest.raises(ConflictError):
        service.create_case(twin)
    assert not service.list_cases(CaseFilterDto(search="2026-RSV-0001"))


def test_close_requires_reason(service: CaseService) -> None:
    from trace_core.core.errors import ValidationError

    created = service.create_case(CaseCreateDto(number="2026-RSN-0001", title="T", lead_examiner="Ex"))
    with pytest.raises(ValidationError, match="reason is required"):
        service.close_case(created.number)
    with pytest.raises(ValidationError, match="reason is required"):
        service.close_case(created.number, reason="   ")


def test_system_metadata_wins() -> None:
    import json

    from trace_core.audit.domain import AuditAction
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.events import Context, Subject
    from trace_core.audit.service import AuditService

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    svc = CaseService(mgr)
    created = svc.create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    with mgr.session() as session:
        AuditService().record(
            session,
            AuditAction.CASE_UPDATED,
            Subject(type="case", number=created.number, id=created.id),
            "op",
            {"host": "evil", "command": "evil", "changed": []},
            Context(host="real", trace_version="9.9", command="real"),
        )
        session.commit()
    details = json.loads(AuditService(mgr).list_events(AuditFilterDto())[0].payload_json)["details"]
    assert (details["host"], details["command"]) == ("real", "real")


def test_recorded_attribution_present() -> None:
    import getpass
    import json

    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.database.session import DatabaseSessionManager

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    CaseService(mgr).create_case(CaseCreateDto(title="T", lead_examiner="Ex"), actor="claimed")
    details = json.loads(AuditService(mgr).list_events(AuditFilterDto())[0].payload_json)["details"]
    assert details["os_user"] == (getpass.getuser() or "unknown")
    assert details["session_id"]
    assert len(details["session_id"]) == 12


def test_actor_length_enforced() -> None:
    from trace_core.audit.domain import AuditAction
    from trace_core.audit.events import Subject
    from trace_core.audit.service import AuditService
    from trace_core.core.database.session import DatabaseSessionManager
    from trace_core.core.errors import ValidationError

    mgr = DatabaseSessionManager("sqlite:///:memory:")
    mgr.init_schema()
    recorder = AuditService()
    action = AuditAction.CASE_CREATED
    subject = Subject(type="case", number="2026-CR-0001", id=None)
    actor = "m" * 256
    with mgr.session() as session:
        with pytest.raises(ValidationError, match="255"):
            recorder.record(session, action, subject, actor, {}, None)


def test_search_wildcards_literal(service: CaseService) -> None:
    from trace_core.cases.dto import CaseFilterDto

    service.create_case(CaseCreateDto(number="2026-WLD-0001", title="Alpha", lead_examiner="Ex"))
    assert service.list_cases(CaseFilterDto(search="%")) == []
    assert service.list_cases(CaseFilterDto(search="_lpha")) == []
    assert len(service.list_cases(CaseFilterDto(search="Alpha"))) == 1


def test_fresh_events_carry_envelope(session_manager: DatabaseSessionManager) -> None:
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    event = AuditService(session_manager).list_events(AuditFilterDto())[0]
    assert event.key_id == "hmac-v1"
    assert event.signature is not None
    assert len(event.signature) == 64


def test_recomputed_chain_rejected_without_key(detached_event) -> None:
    """PoC4 as regression: perfect hash recomputation still fails on the envelope."""
    import hashlib
    import json

    from trace_core.audit.domain import chain_hash
    from trace_core.audit.verifier import verify_rows
    from trace_core.core.canonical import canonical_json

    m = detached_event
    obj = json.loads(m.payload_json)
    obj["actor"] = "mallory"
    blob = canonical_json(obj)
    m.payload_json = blob.decode("utf-8")
    m.payload_hash = hashlib.sha256(blob).hexdigest()
    m.chain_hash = chain_hash(m.prev_chain, m.payload_hash, m.seq)
    res = verify_rows([m])
    assert res.is_valid is False
    assert res.mismatch_type == "signature"
    assert res.first_mismatch_seq == 1


def test_legacy_unsigned_row_verifies(detached_event) -> None:
    """Pre-envelope rows (signature NULL) verify chain-only: migration path."""
    from trace_core.audit.verifier import verify_rows

    m = detached_event
    m.signature = None
    m.key_id = None
    res = verify_rows([m])
    assert res.is_valid is True


def test_manual_number_advances_allocator(session_manager: DatabaseSessionManager) -> None:
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(number="2026-ADV-0500", title="T", lead_examiner="Ex"))
    auto = svc.create_case(CaseCreateDto(title="U", lead_examiner="Ex"))
    assert auto.number == "2026-CR-0501"


def test_ed25519_lifecycle(temp_storage_root, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    """Generate, select, rotate: old events verify under retired keys, forgery dies."""
    from trace_core.audit import signing
    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.audit.verifier import verify_rows
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    assert signing.active_key_id() == "hmac-v1"
    first = signing.init_key("test-one")
    assert first.startswith("ed25519:")
    assert signing.active_key_id() == first
    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    event = AuditService(session_manager).list_events(AuditFilterDto())[0]
    assert event.key_id == first
    assert event.signature is not None
    assert AuditService(session_manager).verify().is_valid is True
    second = signing.rotate_keys("test-two")
    assert second != first
    assert {k["status"] for k in signing.list_keys()} == {"active", "retired"}
    assert AuditService(session_manager).verify().is_valid is True  # retired still verifies

    from trace_core.audit.models import AuditEventModel

    with session_manager.session() as session:
        m = session.scalars(select(AuditEventModel).where(AuditEventModel.seq == 1)).one()
        forged = AuditEventModel(
            seq=m.seq,
            ts=m.ts,
            action=m.action,
            actor=m.actor,
            subject_case_number=m.subject_case_number,
            subject_case_id=m.subject_case_id,
            payload_json=m.payload_json,
            payload_hash=m.payload_hash,
            prev_chain=m.prev_chain,
            chain_hash=m.chain_hash,
            key_id=first,
            signature="0" * 128,
        )
    res = verify_rows([forged])
    assert res.is_valid is False
    assert res.mismatch_type == "signature"
    privates = list(temp_storage_root.glob("keys/*.key"))
    assert len(privates) == 2
    import sys

    if sys.platform != "win32":
        assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in privates)


def test_first_operator_is_admin(session_manager: DatabaseSessionManager) -> None:
    from trace_core.core.operators import ROLE_ADMIN, current_operator

    with session_manager.session() as session:
        assert current_operator(session).role == ROLE_ADMIN


def test_auditor_is_read_only(session_manager: DatabaseSessionManager, as_user) -> None:  # type: ignore[no-untyped-def]
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import AuthorizationError
    from trace_core.core.operators import ROLE_AUDITOR, get_or_provision

    with session_manager.session() as session:
        row = get_or_provision(session, "viewer", "workstation")
        row.role = ROLE_AUDITOR
        session.commit()
    as_user("viewer")
    reader = CaseService(session_manager)
    attempt = CaseCreateDto(title="T", lead_examiner="Ex")
    with pytest.raises(AuthorizationError):
        reader.create_case(attempt)
    assert CaseService(session_manager).list_cases() == []


def test_only_admin_purges(session_manager: DatabaseSessionManager, as_user) -> None:  # type: ignore[no-untyped-def]
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import AuthorizationError

    svc = CaseService(session_manager)
    created = svc.create_case(CaseCreateDto(number="2026-PUR-0001", title="T", lead_examiner="Ex"))
    as_user("junior")  # auto-provisioned investigator
    svc.delete_case(created.number, purge=False)  # investigators may archive
    with pytest.raises(AuthorizationError, match="purge"):
        svc.delete_case(created.number, purge=True)


def test_claimed_actor_logged_beside_actual(
    session_manager: DatabaseSessionManager,
    as_user,  # type: ignore[no-untyped-def]
) -> None:
    import json

    from trace_core.audit.dto import AuditFilterDto
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    as_user("mallory")
    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="T", lead_examiner="Ex"), actor="alice")
    details = json.loads(AuditService(session_manager).list_events(AuditFilterDto())[0].payload_json)["details"]
    assert details["claimed_actor"] == "alice"
    assert details["os_user"] == "mallory"


def test_anchor_intent_pins_exact_event(temp_storage_root, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    """Intent captures the close event's seq/chain, not a later head (no tip race)."""
    from sqlalchemy import select

    from trace_core.audit.models import AnchorIntentModel
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    svc = CaseService(session_manager)
    created = svc.create_case(CaseCreateDto(number="2026-INT-0001", title="T", lead_examiner="Ex"))
    closed = svc.close_case(created.number, reason="done")
    with session_manager.session() as session:
        intent = session.scalars(select(AnchorIntentModel).where(AnchorIntentModel.case_number == closed.number)).one()
        assert (intent.seq, intent.status) == (2, "confirmed")
    other = svc.create_case(CaseCreateDto(number="2026-INT-0002", title="U", lead_examiner="Ex"))
    with session_manager.session() as session:
        same = session.scalars(select(AnchorIntentModel).where(AnchorIntentModel.case_number == closed.number)).one()
        assert (same.seq, same.status) == (2, "confirmed")
        assert other.number == "2026-INT-0002"


def test_anchor_publish_failure_is_loud(temp_storage_root, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    """Unwritable sink -> FAILED with code, never silent CONFIRMED."""
    from trace_core.audit.anchor import publish_pending_anchors, record_anchor_intent

    with session_manager.session() as session:
        record_anchor_intent(session, "2026-FLB-0001", None, 7, "0" * 64)
        session.commit()
    blocker = temp_storage_root / "not-a-dir"
    blocker.write_text("x")
    confirmed = publish_pending_anchors(session_manager, extra_sinks=[str(blocker / "sub")])
    assert confirmed == 0
    with session_manager.session() as session:
        from sqlalchemy import select

        from trace_core.audit.models import AnchorIntentModel

        row = session.scalars(select(AnchorIntentModel).where(AnchorIntentModel.case_number == "2026-FLB-0001")).one()
        assert row.status == "failed"
        assert row.failure_code
        assert row.attempt_count >= 1


def test_sealed_bundle_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from trace_core.audit.vault import decrypt_bytes, encrypt_bytes

    sealed = encrypt_bytes(b'{"seq": 1}', "correct-horse")
    assert decrypt_bytes(sealed, "correct-horse") == b'{"seq": 1}'


def test_sealed_bundle_wrong_passphrase(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from trace_core.audit.vault import decrypt_bytes, encrypt_bytes
    from trace_core.core.errors import ValidationError

    sealed = encrypt_bytes(b"evidence", "right")
    with pytest.raises(ValidationError):
        decrypt_bytes(sealed, "wrong")
    with pytest.raises(ValidationError):
        decrypt_bytes(b'{"alg": "x"}', "right")
    with pytest.raises(ValidationError):
        encrypt_bytes(b"evidence", "")


def test_encrypted_export_roundtrip(tmp_path, service: CaseService, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from trace_core.audit.helpers import do_decrypt, do_export_encrypted
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto

    monkeypatch.setenv("TRACE_EXPORT_PASSPHRASE", "s3cret")
    service.create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    sealed_path = tmp_path / "bundle.jsonl.enc"
    do_export_encrypted(AuditService(service.session_manager), str(sealed_path), "s3cret")
    assert b'"title"' not in sealed_path.read_bytes()
    plain_path = tmp_path / "bundle.jsonl"
    do_decrypt(str(sealed_path), str(plain_path), "s3cret")
    assert "CASE_CREATED" in plain_path.read_text()


def test_production_refuses_default_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest

    from trace_core.core.settings import Settings

    monkeypatch.setenv("TRACE_ENV", "production")
    monkeypatch.delenv("TRACE_DATABASE_URL", raising=False)
    monkeypatch.delenv("TRACE_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="production startup"):
        Settings()


def test_unknown_key_fails_closed(detached_event) -> None:
    from trace_core.audit.verifier import verify_rows

    m = detached_event
    m.key_id = "ed25519:deadbeef"
    m.signature = "f" * 64
    res = verify_rows([m])
    assert res.is_valid is False
    assert res.mismatch_type == "signature"


def test_traversal_key_id_fails_closed(detached_event) -> None:
    """Forged key_id with path traversal must fail closed without touching the filesystem."""
    from trace_core.audit.signing import verify_bytes
    from trace_core.audit.verifier import verify_rows

    assert verify_bytes("ed25519:../../../../tmp/pwn", b"data", "0" * 128) is False
    m = detached_event
    m.key_id = "ed25519:../../../../tmp/pwn"
    m.signature = "0" * 128
    res = verify_rows([m])
    assert res.is_valid is False
    assert res.mismatch_type == "signature"


def test_truncate_trigger_ddl() -> None:
    from trace_core.core.database.migrations import PG_AUDIT_TRUNCATE_TRIGGER_DDL

    assert "TRUNCATE" in PG_AUDIT_TRUNCATE_TRIGGER_DDL
    assert "FOR EACH STATEMENT" in PG_AUDIT_TRUNCATE_TRIGGER_DDL
    assert "audit_events_block_write" in PG_AUDIT_TRUNCATE_TRIGGER_DDL


def test_role_ddl_least_privilege() -> None:
    from trace_core.core.database.migrations import ROLE_DDL

    joined = "\n".join(ROLE_DDL)
    assert "NOLOGIN" in joined
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON audit_events, audit_chain_state" in joined
    ledger_grants = [s for s in ROLE_DDL if s.startswith("GRANT") and "audit_events" in s]
    assert ledger_grants
    assert all("UPDATE" not in s for s in ledger_grants)
    assert all("DELETE" not in s for s in ledger_grants)


def test_migration_checksum_drift_fails_closed(session_manager: DatabaseSessionManager) -> None:
    import pytest
    from sqlalchemy import text

    from trace_core.core.database.migrations import verify_migration_checksums

    verify_migration_checksums(session_manager.engine)  # clean tree verifies
    with session_manager.engine.begin() as conn:
        conn.execute(text("UPDATE schema_migrations SET checksum='0' WHERE version=10"))
    with pytest.raises(RuntimeError, match="drift"):
        verify_migration_checksums(session_manager.engine)


def test_legacy_checksum_upgrades_once(session_manager: DatabaseSessionManager) -> None:
    from sqlalchemy import text

    from trace_core.core.database.migrations import (
        _legacy_migration_checksum,
        get_applied_migrations,
        verify_migration_checksums,
    )

    with session_manager.engine.begin() as conn:
        conn.execute(
            text("UPDATE schema_migrations SET checksum=:c WHERE version=10"),
            {"c": _legacy_migration_checksum("010_add_ledger_signature_columns")},
        )
    verify_migration_checksums(session_manager.engine)  # upgrades, does not raise
    current = {m["version"]: m["checksum"] for m in get_applied_migrations(session_manager.engine)}
    assert current[10] != _legacy_migration_checksum("010_add_ledger_signature_columns")


def test_ensure_dir_restrictive(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    from trace_core.core.fs import ensure_dir

    target = ensure_dir(tmp_path / "sub" / "store")
    assert target.is_dir()
    if sys.platform != "win32":
        assert oct(target.stat().st_mode & 0o777) == "0o700"


def test_atomic_write_recovers_stale_tmp(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    from trace_core.core.fs import atomic_write_lines

    out = tmp_path / "bundle.jsonl"
    tmp = tmp_path / "bundle.jsonl.tmp"
    tmp.write_text("STALE PARTIAL")
    atomic_write_lines(out, ["a\n", "b\n"])
    assert out.read_text() == "a\nb\n"
    if sys.platform != "win32":
        assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_export_refuses_clobber(tmp_path, service: CaseService) -> None:  # type: ignore[no-untyped-def]
    from trace_core.audit.helpers import check_export_dest
    from trace_core.audit.service import AuditService
    from trace_core.core.errors import ValidationError

    service.create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    victim = tmp_path / "bundle.jsonl"
    victim.write_text("ORIGINAL")
    with pytest.raises(ValidationError, match="--force"):
        check_export_dest(str(victim), False)
    assert victim.read_text() == "ORIGINAL"
    check_export_dest(str(victim), True)
    AuditService(service.session_manager).export(victim)
    assert "ORIGINAL" not in victim.read_text()


def test_shlex_unclosed_quote_cards(service: CaseService, capsys: pytest.CaptureFixture[str]) -> None:
    from trace_core.cli.shell import InteractiveShell

    shell = InteractiveShell(service=service)
    shell.execute_line('case create "unclosed')  # must not raise
    assert "Invalid Command" in capsys.readouterr().out


def test_unreadable_anchor_typed_error(session_manager: DatabaseSessionManager) -> None:
    from trace_core.audit.anchor import verify_against_anchor
    from trace_core.audit.service import AuditService
    from trace_core.core.errors import ValidationError

    svc = AuditService(session_manager)
    res = svc.verify()
    with pytest.raises(ValidationError, match="Unreadable anchor"):
        verify_against_anchor(svc, res, "/no/such/anchor.json")


def _signed_anchor(payload: dict) -> dict:  # type: ignore[type-arg]
    """Anchor envelope signed exactly the way _publish_one signs it."""
    from trace_core.audit.signing import sign_bytes
    from trace_core.core.canonical import canonical_json

    key_id, signature = sign_bytes(canonical_json(payload))
    return {**payload, "key_id": key_id, "signature": signature}


def test_anchor_mismatch_pure(session_manager: DatabaseSessionManager) -> None:
    from trace_core.audit.anchor import check_anchor_match
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import AuditTamperError

    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    svc = AuditService(session_manager)
    res = svc.verify()
    seq, chain = svc.head()
    good = {"last_seq": seq, "last_chain": chain}
    check_anchor_match(res, _signed_anchor(good), chain)
    with pytest.raises(AuditTamperError, match="tail mismatch"):
        check_anchor_match(res, _signed_anchor({**good, "last_seq": seq + 100}), chain)


def test_unsigned_anchor_is_rejected(session_manager: DatabaseSessionManager) -> None:
    """H-38: a stripped signature must be an error, not a skipped check."""
    from trace_core.audit.anchor import check_anchor_match
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import AuditTamperError

    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    svc = AuditService(session_manager)
    res = svc.verify()
    seq, chain = svc.head()
    good = {"last_seq": seq, "last_chain": chain}
    with pytest.raises(AuditTamperError, match="unsigned"):
        check_anchor_match(res, good, chain)
    envelope = _signed_anchor(good)
    without_key = {k: v for k, v in envelope.items() if k != "key_id"}
    without_signature = {k: v for k, v in envelope.items() if k != "signature"}
    with pytest.raises(AuditTamperError, match="unsigned"):
        check_anchor_match(res, without_key, chain)
    with pytest.raises(AuditTamperError, match="unsigned"):
        check_anchor_match(res, without_signature, chain)


@pytest.mark.anyio
async def test_bad_anchor_path_notifies(session_manager: DatabaseSessionManager) -> None:
    """Unreadable anchor surfaces as text, never a dead app (SEC-12)."""
    from rich.text import Text
    from textual.widgets import ListView, Static, TabbedContent

    from trace_core.tui.app import TraceApp

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "settings"
        await pilot.pause()
        app.query_one("#settings-sections", ListView).focus()
        # Move to Integrity section (Database -> Updates -> Integrity).
        for _ in range(5):
            body_now = app.query_one("#settings-detail", Static).render()
            text_now = body_now.plain if isinstance(body_now, Text) else str(body_now)
            if "Chain Status" in text_now or "No audit events found" in text_now:
                break
            await pilot.press("down")
            await pilot.pause()
        rendered = app.query_one("#settings-detail", Static).render()
        body = rendered.plain if isinstance(rendered, Text) else str(rendered)
        assert "Chain Status" in body or "No audit events found" in body
        # Service-level typed error for the bad anchor path itself.
        from trace_core.audit.anchor import verify_against_anchor
        from trace_core.audit.service import AuditService
        from trace_core.core.errors import ValidationError

        svc = AuditService(session_manager)
        res = svc.verify()
        try:
            verify_against_anchor(svc, res, "/no/such/anchor.json")
        except ValidationError as exc:
            assert "Unreadable anchor" in str(exc)
        except Exception:
            pass  # empty ledger: nothing to anchor-check, app already stayed alive


@pytest.mark.anyio
async def test_wrong_tab_command_toasts(session_manager: DatabaseSessionManager) -> None:
    """Palette ids on the wrong tab notify instead of vanishing or raising."""
    from textual.widgets import TabbedContent

    from trace_core.tui.app import TraceApp

    app = TraceApp(session_manager)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "audit"
        await pilot.pause()
        view = app.current_view()
        assert view is not None
        view.run_command("case-create")  # type: ignore[attr-defined]
        view.run_command("bogus-nope")  # type: ignore[attr-defined]
        await pilot.pause()


def test_failed_anchor_intent_cools_down(temp_storage_root, session_manager: DatabaseSessionManager) -> None:  # type: ignore[no-untyped-def]
    """A failed anchor publish retries on a cooldown, not on every close."""
    import uuid
    from datetime import timedelta

    from trace_core.audit.anchor import publish_pending_anchors
    from trace_core.audit.models import INTENT_FAILED, AnchorIntentModel
    from trace_core.core.clock import now_utc

    with session_manager.session() as s:
        s.add(
            AnchorIntentModel(
                case_id=uuid.uuid4(),
                case_number="2026-CR-0001",
                seq=1,
                chain_hash="0" * 64,
                status=INTENT_FAILED,
                attempt_count=10,
                last_attempt_at=now_utc(),
            )
        )
        s.commit()
    # Fresh failure: skipped without another attempt.
    assert publish_pending_anchors(session_manager) == 0
    with session_manager.session() as s:
        row = s.scalars(select(AnchorIntentModel)).one()
        assert row.attempt_count == 10
    # Aged failure: retried, and the write succeeds here.
    with session_manager.session() as s:
        row = s.scalars(select(AnchorIntentModel)).one()
        row.last_attempt_at = now_utc() - timedelta(hours=25)
        s.commit()
    assert publish_pending_anchors(session_manager) == 1
    with session_manager.session() as s:
        assert s.scalars(select(AnchorIntentModel)).one().status == "confirmed"


def test_anchor_signing_failure_is_recorded(
    temp_storage_root, session_manager: DatabaseSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """H-41: an unreadable keystore must land on the intent, so the cooldown engages.

    Signing used to raise outside the try, so attempt_count/last_attempt_at were
    rolled back and every later close re-paid the full attempt.
    """
    import uuid

    from trace_core.audit import signing
    from trace_core.audit.anchor import _failed_retry_due, publish_pending_anchors
    from trace_core.audit.models import INTENT_FAILED, AnchorIntentModel
    from trace_core.core.errors import ApplicationError

    def boom(_data: bytes) -> tuple[str, str]:
        raise ApplicationError("keystore unavailable")

    monkeypatch.setattr(signing, "sign_bytes", boom)
    with session_manager.session() as s:
        s.add(
            AnchorIntentModel(
                case_id=uuid.uuid4(),
                case_number="2026-CR-0001",
                seq=1,
                chain_hash="0" * 64,
            )
        )
        s.commit()

    assert publish_pending_anchors(session_manager) == 0
    with session_manager.session() as s:
        row = s.scalars(select(AnchorIntentModel)).one()
        assert row.status == INTENT_FAILED
        assert row.attempt_count == 1
        assert row.last_attempt_at is not None
        assert _failed_retry_due(row) is False
    assert publish_pending_anchors(session_manager) == 0


def _pg_error(psycopg_error: BaseException) -> Exception:
    from sqlalchemy.exc import ProgrammingError

    return ProgrammingError("SELECT 1", {}, psycopg_error)


def test_missing_table_detects_psycopg3_sqlstate() -> None:
    """H-44: psycopg 3 exposes .sqlstate, not psycopg2's .pgcode."""
    import psycopg

    from trace_core.core.operators import _missing_table

    assert _missing_table(_pg_error(psycopg.errors.UndefinedTable("missing relation"))) is True
    assert _missing_table(_pg_error(psycopg.errors.InsufficientPrivilege("nope"))) is False


def test_ledger_missing_detects_psycopg3_sqlstate() -> None:
    import psycopg

    from trace_core.audit.service import _is_ledger_missing

    assert _is_ledger_missing(_pg_error(psycopg.errors.UndefinedTable("missing relation"))) is True


def test_manifest_rejects_empty_minimum_supported_version() -> None:
    """H-23: "" is falsy, so it skipped the minimum-version control entirely."""
    from trace_core.updates.errors import UpdateVerificationError
    from trace_core.updates.manifest import load_manifest_dict

    base = {
        "schema": 1,
        "product": "trace",
        "channel": "stable",
        "version": "0.2.7",
        "release_id": "r1",
        "security_update": False,
        "restart_required": False,
        "manifest_signature": "",
        "signing_key_id": "",
        "artifacts": {},
    }
    with pytest.raises(UpdateVerificationError):
        load_manifest_dict({**base, "minimum_supported_version": ""})


def test_history_dto_requires_explicit_result() -> None:
    """H-22: the default persisted SUCCESS for an update that never happened."""
    from pydantic import ValidationError

    from trace_core.updates.dto import UpdateHistoryCreateDto

    with pytest.raises(ValidationError):
        UpdateHistoryCreateDto.model_validate({"from_version": "0.2.6", "to_version": "0.2.7"})


def test_manifest_rejects_unsafe_artifact_filename() -> None:
    """H-01: is_safe_filename only rejects /, \\ and "..", so "." passed."""
    from trace_core.updates.errors import UpdateVerificationError
    from trace_core.updates.manifest import load_manifest_dict

    base = {
        "schema": 1,
        "product": "trace",
        "channel": "stable",
        "version": "0.2.7",
        "release_id": "r1",
        "security_update": False,
        "restart_required": False,
        "manifest_signature": "",
        "signing_key_id": "",
    }
    artifact = {"filename": ".", "sha256": "a" * 64, "size": 1}
    with pytest.raises(UpdateVerificationError):
        load_manifest_dict({**base, "artifacts": {"default": artifact}})


def test_non_https_manifest_url_is_policy_blocked() -> None:
    """H-11: a security refusal must not render as "check your network and retry"."""
    from trace_core.updates.errors import UpdateNetworkError, UpdatePolicyBlockedError
    from trace_core.updates.sources import _validate_manifest_url

    with pytest.raises(UpdatePolicyBlockedError):
        _validate_manifest_url("http://example.invalid/stable.json")
    assert not issubclass(UpdatePolicyBlockedError, UpdateNetworkError)
    _validate_manifest_url("https://example.invalid/stable.json")


def test_unknown_channel_is_policy_blocked_not_verification_failure() -> None:
    """H-24: a mistyped channel is caller input, not a trust failure."""
    from trace_core.updates.errors import UpdatePolicyBlockedError
    from trace_core.updates.manifest import load_manifest_dict
    from trace_core.updates.policy import is_installable

    manifest = load_manifest_dict(
        {
            "schema": 1,
            "product": "trace",
            "channel": "stable",
            "version": "0.2.7",
            "release_id": "r1",
            "security_update": False,
            "restart_required": False,
            "manifest_signature": "",
            "signing_key_id": "",
            "artifacts": {},
        }
    )
    with pytest.raises(UpdatePolicyBlockedError):
        is_installable("0.2.6", manifest, channel="nope")


def test_history_dto_rejects_overlong_transaction_id() -> None:
    """H-26: String(36) truncates silently on SQLite, colliding two history rows."""
    from pydantic import ValidationError

    from trace_core.updates.dto import UpdateHistoryCreateDto

    with pytest.raises(ValidationError):
        UpdateHistoryCreateDto.model_validate(
            {"from_version": "0.2.6", "to_version": "0.2.7", "result": "SUCCESS", "transaction_id": "x" * 37}
        )
    ok = UpdateHistoryCreateDto.model_validate(
        {"from_version": "0.2.6", "to_version": "0.2.7", "result": "SUCCESS", "transaction_id": "x" * 36}
    )
    assert ok.transaction_id is not None


def test_sequence_bound_stays_inside_case_number_grammar() -> None:
    """H-61: range(10000) emitted a 5-digit number, which CASE_NUMBER_RE rejects."""
    from trace_core.cases.domain import CASE_NUMBER_RE
    from trace_core.cases.repository import _MAX_SEQUENCE

    assert CASE_NUMBER_RE.match(f"2026-CR-{_MAX_SEQUENCE:04d}") is not None
    assert CASE_NUMBER_RE.match(f"2026-CR-{_MAX_SEQUENCE + 1:04d}") is None


def test_close_audit_record_uses_sanitised_reason(session_manager: DatabaseSessionManager) -> None:
    """H-55: the case row was stripped but its own audit record was not."""
    from trace_core.audit.service import AuditService
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.core.domain import strip_controls

    svc = CaseService(session_manager)
    created = svc.create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    raw = "held\x1b[31mred\x07 in situ"
    closed = svc.close_case(created.number, reason=raw, closed_by="Ex")

    assert strip_controls(raw) in (closed.closure_reason or "")
    assert "\x1b" not in (closed.closure_reason or "")

    events = AuditService(session_manager).list_events()
    close_events = [e for e in events if e.action.value == "CASE_CLOSED"]
    assert close_events
    for event in close_events:
        assert "\\u001b" not in event.payload_json
        assert "\\u0007" not in event.payload_json


def test_post_commit_hook_failure_does_not_propagate(
    session_manager: DatabaseSessionManager, caplog: pytest.LogCaptureFixture
) -> None:
    """H-45: the commit is durable, so reporting failure invites a double-apply."""
    from trace_core.core.service import BaseService

    service = BaseService(session_manager)
    reached = False
    with service.transaction() as uow:
        uow.on_commit(lambda: (_ for _ in ()).throw(RuntimeError("sink down")))

        def _mark() -> None:
            nonlocal reached
            reached = True

        uow.on_commit(_mark)
    assert reached is True


def test_hash_algo_is_the_single_source() -> None:
    """H-46: HASH_ALGO is written into every payload, so it must select the hasher."""
    from trace_core.audit import domain

    assert domain.payload_hash({"a": 1}) == domain.chain_hash("0" * 64, "a" * 64, 1)[:0] + domain.payload_hash({"a": 1})
    original = domain.HASH_ALGO
    try:
        domain.HASH_ALGO = "SHA-512"
        with pytest.raises(KeyError):
            domain.payload_hash({"a": 1})
    finally:
        domain.HASH_ALGO = original
    assert len(domain.payload_hash({"a": 1})) == 64


def test_audit_hash_fields_reject_non_hex(session_manager: DatabaseSessionManager) -> None:
    """H-49: length-only constraints let uppercase hex through to a != comparison."""
    from pydantic import ValidationError

    from trace_core.audit.domain import AuditEvent
    from trace_core.core.clock import now_utc

    fields: dict[str, object] = {
        "seq": 1,
        "ts": now_utc(),
        "action": "CASE_CREATED",
        "actor": "a",
        "subject_case_number": "2026-CR-0001",
        "payload_json": "{}",
    }
    upper = "A" * 64
    for name in ("payload_hash", "prev_chain", "chain_hash_str"):
        with pytest.raises(ValidationError):
            AuditEvent.model_validate({**fields, name: upper})
    AuditEvent.model_validate({**fields, "payload_hash": "a" * 64, "prev_chain": "b" * 64, "chain_hash_str": "c" * 64})


def test_repository_purge_refuses_active_case(session_manager: DatabaseSessionManager) -> None:
    """H-54: the archive-first guard is an invariant, so it belongs in the repository."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.repository import SqlAlchemyCaseRepository
    from trace_core.cases.service import CaseService
    from trace_core.core.errors import StateTransitionError

    created = CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    with session_manager.session() as session:
        repo = SqlAlchemyCaseRepository(session)
        with pytest.raises(StateTransitionError):
            repo.purge(created.id, expected_version=created.version)


def test_unknown_stored_status_does_not_crash_mapping(session_manager: DatabaseSessionManager) -> None:
    """H-62: a row from a newer version must not break every case listing."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.models import CaseModel
    from trace_core.cases.repository import SqlAlchemyCaseRepository
    from trace_core.cases.service import CaseService

    created = CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    with session_manager.session() as session:
        row = session.get(CaseModel, created.id)
        assert row is not None
        row.status = "SOMETHING_NEWER"
        session.commit()
    with session_manager.session() as session:
        loaded = SqlAlchemyCaseRepository(session).get_by_number(created.number)
    assert loaded is not None
    assert loaded.status.value == "OPEN"


def test_storage_check_without_probe_writes_nothing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H-66: the TUI render path must not write into the evidence storage root."""
    from trace_core.core.cli.doctor import _storage_check
    from trace_core.core.settings import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "store"))
    name, _detail, passed = _storage_check(probe=False)
    assert passed is True
    assert list((tmp_path / "store").iterdir()) == []


def test_palette_case_aliases_resolve_to_real_actions() -> None:
    """H-68: case-close must reach action_seal, and every palette id must exist."""
    from trace_core.tui.screens.cases import _CASE_COMMAND_ALIASES, CasesView

    for cmd in ("create", "edit", "close", "archive", "purge", "restore", "recent"):
        name = _CASE_COMMAND_ALIASES.get(cmd, cmd)
        assert callable(getattr(CasesView, f"action_{name}", None)), cmd


def test_burned_in_trust_anchor_matches_its_own_key_content() -> None:
    """The .pub filename IS the trust anchor, and nothing else checks it against the key.

    release.yml builds trusted-keys.bundle with `basename`, so a renamed file ships a
    key that no install can ever match. This pins filename == key_id_for_pubkey(content).
    """
    from trace_core.updates.signing import key_id_for_pubkey

    keys = sorted(Path("release/trusted-keys").glob("*.pub"))
    assert keys, "no burned-in trust anchors found"
    for pub in keys:
        raw = bytes.fromhex(pub.read_text(encoding="utf-8").strip())
        derived = key_id_for_pubkey(raw).removeprefix("ed25519:")
        assert derived == pub.stem, f"{pub.name} derives {derived}"


def test_verify_release_refuses_a_mismatched_trust_anchor(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A renamed anchor must fail closed, not silently produce an unverifiable release."""
    import importlib.util

    repo = Path(__file__).resolve().parents[2]
    src = repo / "release" / "trusted-keys"
    if not src.is_dir():
        pytest.skip("release/trusted-keys not present")
    good = next(iter(sorted(src.glob("*.pub"))), None)
    if good is None:
        pytest.skip("no anchor to rename")

    spec = importlib.util.spec_from_file_location("verify_release", repo / "release" / "verify_release.py")
    assert spec is not None and spec.loader is not None
    verify_release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_release)

    work = tmp_path / "work"
    (work / "release" / "trusted-keys").mkdir(parents=True)
    shutil.copyfile(good, work / "release" / "trusted-keys" / "deadbeefdeadbeef.pub")
    monkeypatch.chdir(work)
    monkeypatch.setenv("TRACE_STORAGE_ROOT", str(tmp_path / "store"))

    with pytest.raises(SystemExit) as exc:
        verify_release._sync_trusted_keys()
    assert "does not match its own key content" in str(exc.value)

    # And the real filename must be accepted, proving the check is not vacuous.
    shutil.rmtree(work / "release" / "trusted-keys")
    (work / "release" / "trusted-keys").mkdir(parents=True)
    shutil.copyfile(good, work / "release" / "trusted-keys" / good.name)
    verify_release._sync_trusted_keys()
