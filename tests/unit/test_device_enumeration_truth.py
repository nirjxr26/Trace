"""A device list that could not be fetched must not look like an empty device list.

"0 device(s)" under a green marker tells an operator no drive is attached. When the
enumeration tool is missing or its output is unparseable, that is a false all-clear on a
forensic tool.
"""

import pytest


def _boom():
    from trace_core.devices._subprocess import HelperFailure
    from trace_core.devices.domain import UnknownCause

    raise HelperFailure(UnknownCause.TOOL_MISSING, "lsblk could not be executed")


def test_a_failed_enumeration_raises_instead_of_returning_no_devices(session_manager) -> None:
    from trace_core.devices.service import DeviceService

    service = DeviceService(session_manager)

    class _Broken:
        adapter_version = "test"

        def list_block_devices(self):  # type: ignore[no-untyped-def]
            _boom()

        def change_token(self):  # type: ignore[no-untyped-def]
            return ()

    service.enumerator = _Broken()  # type: ignore[assignment]
    with pytest.raises(Exception) as caught:
        service.list_devices()
    assert "Could not list devices" in str(caught.value), caught.value
    assert "not the same as finding none" in str(caught.value), caught.value


def test_the_error_card_names_the_failure_not_an_empty_list(session_manager) -> None:
    from trace_core.core.cli.error_handler import _resolve_error_details
    from trace_core.devices.domain import DeviceEnumerationError

    title, message, remedy, code = _resolve_error_details(
        DeviceEnumerationError("Could not list devices: lsblk could not be executed."), None, None
    )
    assert title == "Couldn't List Devices", title
    assert remedy is not None and "Nothing was changed" in remedy, remedy
    assert code != 0, "a failed enumeration must not exit success"


def test_the_empty_message_says_empty_not_broken(session_manager, capsys) -> None:
    """The genuinely-empty case must still render, and must not be reworded into a failure."""
    from trace_core.core.ui.renderers import console
    from trace_core.devices.renderers import render_devices

    with console.capture() as cap:
        render_devices([])
    out = cap.get()
    assert "No block devices visible" in out, out
