"""Device ports: the three contracts every adapter implements [D8]."""

from typing import Protocol

from trace_core.devices.domain import DeviceInfo, DeviceInspection, GateCheck


class DeviceEnumerator(Protocol):
    """Lists the block devices an adapter can see."""

    def list_block_devices(self) -> list[DeviceInfo]: ...

    def change_token(self) -> tuple[str, ...]:
        """Cheap change signal for polling. Equal tokens mean enumeration would agree."""
        ...


class DeviceInspector(Protocol):
    """Captures device identity; produces no protection fields."""

    def inspect(self, device: DeviceInfo) -> DeviceInspection: ...


class WriteBlockerProbe(Protocol):
    """Checks write protection; produces no fingerprint fields."""

    def verify(self, device: DeviceInfo) -> GateCheck: ...


class DeviceAdapter(DeviceEnumerator, DeviceInspector, WriteBlockerProbe, Protocol):
    """One object satisfying all three ports. Every adapter in the suite provides all three."""
