import os
from pathlib import Path

from trace_core.core.settings import settings


def test_the_session_storage_root_is_rebound_on_the_live_settings_object() -> None:
    session_root = os.environ.get("TRACE_STORAGE_ROOT")
    assert session_root, "the session fixture did not export TRACE_STORAGE_ROOT"
    assert settings.storage_root == Path(session_root)
