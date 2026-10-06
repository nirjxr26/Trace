"""Tribunal tests for the device ports [D8]."""

import inspect
import typing

import pytest

from trace_core.devices import ports
from trace_core.devices.domain import DeviceInfo, DeviceInspection, GateCheck

pytestmark = pytest.mark.unit


def _return_annotation(protocol: type, method: str) -> object:  # type: ignore[no-untyped-def]
    hints = typing.get_type_hints(getattr(protocol, method))
    return hints["return"]


def _param_names(protocol: type, method: str) -> list[str]:  # type: ignore[no-untyped-def]
    return list(inspect.signature(getattr(protocol, method)).parameters)


def test_ports_module_exports_the_three_contracts_and_their_union() -> None:
    contracts = {
        name
        for name, obj in vars(ports).items()
        if inspect.isclass(obj) and getattr(obj, "_is_protocol", False) and obj is not typing.Protocol
    }
    assert contracts == {"DeviceEnumerator", "DeviceInspector", "WriteBlockerProbe", "DeviceAdapter"}


def test_the_adapter_union_is_exactly_the_three_ports() -> None:
    assert set(inspect.getmro(ports.DeviceAdapter)) >= {
        ports.DeviceEnumerator,
        ports.DeviceInspector,
        ports.WriteBlockerProbe,
    }


def test_enumerator_lists_device_info() -> None:
    assert _param_names(ports.DeviceEnumerator, "list_block_devices") == ["self"]
    assert _return_annotation(ports.DeviceEnumerator, "list_block_devices") == list[DeviceInfo]


def test_inspector_returns_device_inspection() -> None:
    assert _param_names(ports.DeviceInspector, "inspect") == ["self", "device"]
    assert _return_annotation(ports.DeviceInspector, "inspect") is DeviceInspection


def test_probe_returns_gate_check_not_a_bare_enum() -> None:
    assert _param_names(ports.WriteBlockerProbe, "verify") == ["self", "device"]
    assert _return_annotation(ports.WriteBlockerProbe, "verify") is GateCheck


def test_a_single_adapter_can_satisfy_all_three_contracts() -> None:
    class _Adapter:
        def list_block_devices(self) -> list[DeviceInfo]:
            raise NotImplementedError

        def inspect(self, device: DeviceInfo) -> DeviceInspection:
            raise NotImplementedError

        def verify(self, device: DeviceInfo) -> GateCheck:
            raise NotImplementedError

    for protocol, method in (
        (ports.DeviceEnumerator, "list_block_devices"),
        (ports.DeviceInspector, "inspect"),
        (ports.WriteBlockerProbe, "verify"),
    ):
        assert inspect.signature(getattr(_Adapter, method)) == inspect.signature(getattr(protocol, method))
