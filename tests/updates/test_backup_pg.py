import subprocess

import pytest

from trace_core.core.database.session import DatabaseSessionManager
from trace_core.updates.errors import UpdateError
from trace_core.updates.migration import backup_database

pytestmark = pytest.mark.unit


def test_pg_backup_invocation(tmp_path, monkeypatch):
    seen = {}

    def _fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        kwargs["stdout"].write(b"-- fake dump")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    mgr = DatabaseSessionManager("postgresql+psycopg://u:p@127.0.0.1:1/trace")
    out = backup_database(mgr, tmp_path / "backups")
    assert out.name == "trace-backup.sql"
    assert seen["argv"][0] == "pg_dump"
    assert seen["argv"][1] == "postgresql://u:p@127.0.0.1:1/trace"
    assert seen["kwargs"]["timeout"] == 300
    assert seen["kwargs"]["check"] is True
    assert seen["kwargs"]["stderr"] == subprocess.DEVNULL


def test_pg_backup_missing_binary_fails_closed(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("pg_dump not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    mgr = DatabaseSessionManager("postgresql+psycopg://u:p@127.0.0.1:1/trace")
    with pytest.raises(UpdateError):
        backup_database(mgr, tmp_path / "backups")
