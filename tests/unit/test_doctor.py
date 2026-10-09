"""Unit tests for trace doctor preflight diagnostics."""

import pytest
from typer.testing import CliRunner

from trace_core.cli.main import app
from trace_core.core.cli.exit_codes import EXIT_ERROR
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit


def test_doctor_healthy(monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager) -> None:
    """Verify doctor exits 0 with all PASS rows on a migrated database."""
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", session_manager)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "Trace Doctor" in res.output
    assert "PASS" in res.output
    assert "FAIL" not in res.output


def test_doctor_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify doctor exits 1 with FAIL rows and remediation when DB is down."""
    import sqlalchemy.exc

    bad_mgr = DatabaseSessionManager("sqlite:///:memory:")

    def _boom() -> None:
        raise sqlalchemy.exc.OperationalError("connect", None, Exception("connection refused"))

    monkeypatch.setattr(bad_mgr, "ensure_ready", _boom)
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", bad_mgr)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == EXIT_ERROR
    assert "FAIL" in res.output
    assert "trace doctor" in res.output


def test_doctor_fails_when_the_signing_key_is_the_default(
    monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager
) -> None:
    """The gate that certifies an install must not pass when records cannot be checked.

    This ran the wrong key (a `.env` that resolves only from the repo directory) and
    printed four PASS rows with exit 0 while `audit verify` reported the host could not
    verify its own ledger.
    """
    from trace_core.core.settings import DEV_SECRET_SENTINEL, settings

    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", session_manager)
    monkeypatch.setattr(settings, "secret_key", type(settings.secret_key)(DEV_SECRET_SENTINEL))
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == EXIT_ERROR, res.output
    assert "Signing key" in res.output
    assert "FAIL" in res.output


def test_doctor_reports_the_record_count_it_checked(
    monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager
) -> None:
    """A bare PASS is indistinguishable from an empty ledger; the count proves it ran."""
    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService

    CaseService(session_manager).create_case(CaseCreateDto(title="T", lead_examiner="Ex"))
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", session_manager)
    res = CliRunner().invoke(app, ["doctor"])
    assert "1 records" in res.output
    assert "Records protected" in res.output


def test_doctor_pending_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify doctor self-heals a fresh schema (no manual migrate needed)."""
    fresh_mgr = DatabaseSessionManager("sqlite:///:memory:")
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", fresh_mgr)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "up to date" in res.output.lower()
    assert "FAIL" not in res.output


def test_the_database_url_shown_to_users_never_contains_a_password() -> None:
    """`doctor` and the settings panel print this. Three paths used to return the raw URL:
    no username (so query masking was never reached), no hostname, and any parse error."""
    from trace_core.core.database.session import sanitized_db_url

    secrets = ("pw123", "hunter2", "s3cr3t", "leakme")
    cases = [
        "postgresql+psycopg://alice:pw123@host:5432/trace",
        "postgresql://host:5432/trace?password=hunter2",
        "postgresql://host:5432/trace?sslpassword=s3cr3t",
        "sqlite:///C:/x/trace.db?password=leakme",
        "not a url at all :::",
    ]
    for url in cases:
        shown = sanitized_db_url(url)
        for secret in secrets:
            assert secret not in shown, f"{secret} leaked from {url} as {shown}"


def test_masking_keeps_the_url_usable_for_diagnostics() -> None:
    """A masked URL still has to identify which database it is, or doctor is useless."""
    from trace_core.core.database.session import sanitized_db_url

    shown = sanitized_db_url("postgresql+psycopg://alice:pw123@host:5432/trace")
    assert "host:5432" in shown
    assert "trace" in shown
    assert "alice" in shown
    assert "pw123" not in shown


def test_doctor_output_masks_a_password_in_the_configured_url(
    monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager
) -> None:
    """End to end: the secret must not reach the rendered table."""
    monkeypatch.setattr("trace_core.core.cli.doctor.db_manager", session_manager)
    monkeypatch.setattr(
        "trace_core.core.settings.settings.database_url",
        "postgresql://someone:hunter2@db.internal:5432/trace",
    )
    res = CliRunner().invoke(app, ["doctor"])
    assert "hunter2" not in res.output, res.output


def test_an_unparseable_url_is_replaced_not_echoed() -> None:
    """The `except` path returned the raw string, so a malformed URL with a password in
    it printed verbatim. Every case below makes the parser raise."""
    from trace_core.core.database.session import sanitized_db_url

    for url in (
        "postgres://user:hunter2@[bad",
        "postgres://user:hunter2@h:notaport/db",
        "postgres://user:hunter2@h:99999/db",
    ):
        shown = sanitized_db_url(url)
        assert "hunter2" not in shown, f"leaked from {url} as {shown}"


def test_integrity_line_separates_verified_empty_and_unreadable() -> None:
    """The green tick used to appear for all three, because an unreadable ledger and an
    empty event list both left the flag True."""
    from trace_core.tui.theme import integrity_line

    unreadable = integrity_line(None, 0)
    empty = integrity_line(True, 0)
    checked = integrity_line(True, 8)
    assert "Couldn't verify" in str(unreadable)
    assert "No records" in str(empty)
    assert "8 newest records checked" in str(checked)
    assert "Verified" not in str(unreadable)


def test_integrity_line_names_its_window_when_only_a_sample_was_checked() -> None:
    """A bare "Verified" implied the case's whole history was covered. The dossier checks the
    newest handful, so the line has to say so."""
    from trace_core.tui.theme import integrity_line

    sampled = str(integrity_line(True, 6, sampled=140))
    assert "6 newest records of 140 checked" in sampled, sampled
    assert "Verified" not in sampled, "must not read as a whole-history verdict"


def test_repl_status_does_not_claim_connected_without_connecting(
    monkeypatch: pytest.MonkeyPatch, session_manager: DatabaseSessionManager
) -> None:
    """`status` printed Connected after constructing an object. Nothing was queried."""
    import sqlalchemy.exc

    from trace_core.cases.service import CaseService
    from trace_core.cli.shell import InteractiveShell
    from trace_core.core.cli.registry import ShellContext

    shell = InteractiveShell(service=CaseService(session_manager))
    shell.context = ShellContext()
    monkeypatch.setattr("trace_core.cli.shell.settings.storage_root", str(session_manager.engine.url))

    def _boom(*_args, **_kwargs):
        raise sqlalchemy.exc.OperationalError("connect", None, Exception("connection refused"))

    monkeypatch.setattr("trace_core.core.database.health.fetch_db_snapshot", _boom)
    from trace_core.core.ui.renderers import console

    with console.capture() as cap:
        shell.show_status()
    out = cap.get()
    assert "Can't reach it" in out, out
    assert "Connected ·" not in out, out
    assert "ISO 17025" not in out, out


def test_two_backups_in_a_row_both_succeed(tmp_path) -> None:
    """The real defect, end to end. A fixed filename made the second backup fail with
    output file already exists, which surfaced as "an unexpected operational error".
    Testing the helper alone would not catch a caller that stopped using it."""
    from trace_core.core.database.session import DatabaseSessionManager
    from trace_core.updates.migration import backup_database

    dest = tmp_path / "backups"
    db = tmp_path / "trace.db"
    mgr = DatabaseSessionManager(f"sqlite:///{db.as_posix()}")
    mgr.init_schema()
    first = backup_database(mgr, dest)
    second = backup_database(mgr, dest)
    assert first.name != second.name
    assert first.exists() and second.exists()


def test_masking_does_not_rewrite_a_sqlite_url() -> None:
    """`urlunsplit` collapsed the empty authority: sqlite:///trace.db became sqlite:/trace.db.
    A hostless URL must keep its slashes or it no longer identifies the file."""
    from trace_core.core.database.session import sanitized_db_url

    assert sanitized_db_url("sqlite:///trace.db") == "sqlite:///trace.db"
    assert sanitized_db_url("sqlite:///C:/cases/trace.db") == "sqlite:///C:/cases/trace.db"
    masked = sanitized_db_url("sqlite:///trace.db?password=hunter2")
    assert masked.startswith("sqlite:///trace.db")
    assert "hunter2" not in masked
