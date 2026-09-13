"""Quick check for 5W1H enrichment."""

import pytest

from trace_core.audit.service import AuditService
from trace_core.cases.dto import CaseCreateDto, CaseUpdateDto
from trace_core.cases.service import CaseService
from trace_core.core.database.session import DatabaseSessionManager

pytestmark = pytest.mark.unit


def test_5w1h_enrichment(session_manager: DatabaseSessionManager) -> None:
    svc = CaseService(session_manager)
    c = svc.create_case(CaseCreateDto(title="W1", lead_examiner="Alice"))
    svc.update_case(c.number, CaseUpdateDto(title="W2"))
    audit = AuditService(session_manager)
    events = audit.list_events()
    assert len(events) == 2
    # check host/version/command present via payload_json
    import json

    for e in events:
        payload = json.loads(e.payload_json)
        details = payload["details"]
        assert "host" in details
        assert "trace_version" in details
        assert "command" in details
    # UPDATED should have before/after (newest first: events[0] is UPDATED)
    upd = next(e for e in events if json.loads(e.payload_json)["action"] == "CASE_UPDATED")
    payload = json.loads(upd.payload_json)
    assert payload["details"]["changed"] == ["title"]
    assert payload["details"]["before"]["title"] == "W1"
    assert payload["details"]["after"]["title"] == "W2"


def test_audit_show_seq_detail(session_manager: DatabaseSessionManager) -> None:
    from typer.testing import CliRunner

    from trace_core.cases.dto import CaseCreateDto
    from trace_core.cases.service import CaseService
    from trace_core.cli.main import app

    runner = CliRunner()
    # isolate db

    svc = CaseService(session_manager)
    svc.create_case(CaseCreateDto(title="SeqTest", lead_examiner="Bob"))

    # monkeypatch db_manager for CLI
    import trace_core.audit.commands as ac
    import trace_core.cases.commands as cc

    orig_ac = ac.db_manager
    orig_cc = cc.db_manager
    ac.db_manager = session_manager  # type: ignore[assignment]
    cc.db_manager = session_manager  # type: ignore[assignment]
    try:
        res = runner.invoke(app, ["audit", "show", "--seq", "1"])
        assert res.exit_code == 0
        assert "AUDIT #1" in res.stdout
        assert "Who" in res.stdout
        res2 = runner.invoke(app, ["audit", "show", "--seq", "999"])
        assert res2.exit_code != 0
    finally:
        ac.db_manager = orig_ac
        cc.db_manager = orig_cc
