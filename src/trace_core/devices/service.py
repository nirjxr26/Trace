"""Device application service: enumerate, inspect, gate.

Mirrors `CaseService`: owns the transaction, resolves RBAC, and hands adapters
to the domain through the three ports. Adapters arrive by constructor injection
exactly as `CaseService` receives its `session_manager`, so the service imports
no adapter module [D31].
"""

import os
import re
import sys
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from trace_core.audit.domain import AuditAction
from trace_core.audit.events import Context, Subject
from trace_core.core.database.session import DatabaseSessionManager
from trace_core.core.errors import AuthorizationError, ValidationError
from trace_core.core.operators import current_identity, require_mutator
from trace_core.core.service import BaseService, UnitOfWork
from trace_core.devices.domain import (
    DeviceInfo,
    DeviceInspection,
    DeviceKind,
    DeviceNotFoundError,
    FingerprintMismatchError,
    GateCheck,
    WpVerdict,
    WriteProtectionError,
)
from trace_core.devices.models import bound_actor
from trace_core.devices.ports import DeviceAdapter, DeviceEnumerator, DeviceInspector, WriteBlockerProbe
from trace_core.devices.repository import SqlAlchemyDeviceRepository

KIND_ALL = "all"
ENV_ADAPTER = "TRACE_DEVICE_ADAPTER"
ENV_DEVICE_ROOT = "TRACE_DEVICE_ROOT"
_OVERRIDE_REASON = "accepted unverified source"


class DeviceService(BaseService):
    def __init__(
        self,
        session_manager: DatabaseSessionManager | None = None,
        enumerator: DeviceEnumerator | None = None,
        inspector: DeviceInspector | None = None,
        probe: WriteBlockerProbe | None = None,
    ) -> None:
        super().__init__(session_manager)
        self.enumerator, self.inspector, self.probe = _fill_ports(enumerator, inspector, probe)

    def list_devices(self, kind: str = KIND_ALL) -> list[DeviceInfo]:
        """Zero persistence, zero audit events, zero evidentiary reads [D10], [D23]."""
        devices = self.enumerator.list_block_devices()
        if str(kind).strip().lower() == KIND_ALL:
            return devices
        wanted = _kind_or_error(kind)
        return [d for d in devices if d.kind is wanted]

    def change_token(self) -> tuple[str, ...]:
        return self.enumerator.change_token()

    def inspect_device(self, node: str, *, allow_real_hardware: bool = False) -> DeviceInspection:
        device = self._resolve(node, allow_real_hardware)
        with self.transaction() as authz:
            self._actor(authz)
        inspection = self.inspector.inspect(device)
        from trace_core.audit.builder import for_device_inspected

        with self.transaction() as uow:
            actor = self._actor(uow)
            SqlAlchemyDeviceRepository(uow.session).save_observation(inspection, actor)
            uow.before_commit(self._ledger_hook(lambda: for_device_inspected(**_identity_details(inspection)), actor))
        return inspection

    def check_device(
        self,
        node: str,
        *,
        inspection: DeviceInspection | None = None,
        allow_real_hardware: bool = False,
        acknowledge_unverified_source: bool = False,
        override_reason: str = "",
    ) -> GateCheck:
        device = self._resolve(node, allow_real_hardware)
        with self.transaction() as authz:
            self._actor(authz)
        captured = inspection if inspection is not None else self.inspector.inspect(device)
        if _node_name(captured.device.node) != _node_name(device.node):
            raise FingerprintMismatchError(f"inspection is for {captured.device.node}, not the requested {device.node}")
        if captured.device.size_bytes != device.size_bytes:
            raise FingerprintMismatchError(
                f"inspection reports {captured.device.size_bytes} bytes, the enumerated device reports {device.size_bytes}"
            )
        gate = self.probe.verify(captured.device)
        refusal = _refusal_for(gate, acknowledge_unverified_source)
        from trace_core.audit.builder import for_device_gate_checked, for_device_override

        if refusal is not None:
            self._record_refusal(captured, gate)
            raise refusal
        with self.transaction() as uow:
            actor = self._actor(uow)
            SqlAlchemyDeviceRepository(uow.session).save_observation(captured, actor, gate)
            uow.before_commit(
                self._ledger_hook(lambda: for_device_gate_checked(**_gate_details(captured, gate)), actor)
            )
            if gate.verdict is WpVerdict.UNKNOWN:
                uow.before_commit(
                    self._ledger_hook(
                        lambda: for_device_override(
                            node=captured.device.node,
                            original_verdict=gate.verdict.value,
                            original_unknown_cause=_cause_value(gate),
                            authorized_by=actor,
                            reason=override_reason.strip() or _OVERRIDE_REASON,
                        ),
                        actor,
                    )
                )
        return gate

    def _resolve(self, node: str, allow_real_hardware: bool) -> DeviceInfo:
        """A node must be in the freshly enumerated set; stale names and traversal die here."""
        cleaned = str(node).strip()
        if not cleaned:
            raise ValidationError("device node must not be empty")
        devices = self.enumerator.list_block_devices()
        exact = [d for d in devices if d.node == cleaned]
        if len(exact) == 1:
            return self._permit(exact[0], node, allow_real_hardware)
        base = _node_name(cleaned)
        named = [d for d in devices if _node_name(d.node) == base]
        if len(named) == 1:
            return self._permit(named[0], node, allow_real_hardware)
        if len(named) > 1:
            raise DeviceNotFoundError(f"device {node} is ambiguous; use the full node from `device list`")
        key = _pd_key(base)
        if key is not None:
            aliased = [d for d in devices if _pd_key(_node_name(d.node)) == key]
            if len(aliased) == 1:
                return self._permit(aliased[0], node, allow_real_hardware)
            if len(aliased) > 1:
                raise DeviceNotFoundError(f"device {node} is ambiguous; use the full node from `device list`")
        raise DeviceNotFoundError(f"device {node} is not in the current enumeration")

    def _permit(self, device: DeviceInfo, node: str, allow_real_hardware: bool) -> DeviceInfo:
        if device.requires_real_hardware_opt_in and not allow_real_hardware:
            raise AuthorizationError(f"{node} is real hardware; pass --allow-real-hardware to proceed")
        return device

    def _actor(self, uow: UnitOfWork) -> str:
        """RBAC then identity, read-only [D18]. Returns the operator name for the row.

        Bounded here because the value reaches both the fingerprint row and the ledger's
        actor column, and `AuditService` rejects an over-long actor outright.
        """
        require_mutator(uow.session, action="device operation")
        user, host = current_identity()
        return bound_actor(f"{user}@{host}")

    def _record_refusal(self, inspection: DeviceInspection, gate: GateCheck) -> None:
        """Ledger a refused check. The attempt itself is the evidence.

        Nothing is persisted to the fingerprint table: no observation was accepted. The
        ledger row records the refusal with its evidence, so a later audit can show that
        the source was found writable or unverifiable and the operation was stopped.
        """
        from trace_core.audit.builder import for_device_gate_checked

        with self.transaction() as uow:
            actor = self._actor(uow)
            uow.before_commit(
                self._ledger_hook(lambda: for_device_gate_checked(**_gate_details(inspection, gate)), actor)
            )

    def _ledger_hook(
        self,
        build: Callable[[], tuple[AuditAction, Subject, dict[str, Any], Context]],
        actor: str,
    ) -> Callable[[Session], None]:
        """A `before_commit` hook writing one ledger row inside the capture transaction [§14.5].

        A failed audit therefore rolls the observation back: an unledgered fingerprint never
        exists, which is the whole point of capturing one. Registering through the hook is
        what §14.5 requires, and it is the same mechanism `CaseService` uses.
        """
        from trace_core.audit.service import AuditService

        def _hook(session: Session) -> None:
            action, subject, details, ctx = build()
            AuditService().record(session, action, subject, actor, details, ctx)

        return _hook


def _refusal_for(gate: GateCheck, acknowledge_unverified_source: bool) -> WriteProtectionError | None:
    """The error this gate must raise, or None when it may proceed.

    Returned rather than raised so the caller can ledger the refusal before propagating
    it: an unrecorded attempt to image a writable source is exactly the gap [D2] exists
    to close.
    """
    if gate.verdict is WpVerdict.WRITABLE:
        return WriteProtectionError("source is writable", gate.verdict, gate.evidence)
    if gate.verdict is WpVerdict.UNKNOWN and not acknowledge_unverified_source:
        return WriteProtectionError(
            f"write protection could not be established ({gate.evidence.unknown_cause})",
            gate.verdict,
            gate.evidence,
        )
    return None


_PD_ALIAS = re.compile(r"(?:physicaldrive|pd)(\d+)$")


def _node_name(node: str) -> str:
    cleaned = str(node).strip()
    if not cleaned:
        raise ValidationError("device node must not be empty")
    return cleaned.replace("\\", "/").rsplit("/", 1)[-1]


def _pd_key(base: str) -> tuple[str, str] | None:
    """Canonical short identity for `PhysicalDriveN`-style names, case-insensitive.

    The prefix is required. The pattern used to make it optional, so any node whose name
    is bare digits matched: `12`, `pd12` and `PhysicalDrive12` all resolved to the same
    key, and where only one of them was enumerated `device check pd12` silently selected
    the wrong device. Leading zeros collapsed too (`007` -> `pd7`).
    """
    match = _PD_ALIAS.fullmatch(base.strip().lower())
    if match is None:
        return None
    return ("pd", str(int(match.group(1))))


def short_id(node: str) -> str:
    """The name a human types: `pd0` for a physical drive, the basename otherwise."""
    cleaned = str(node).strip()
    if not cleaned:
        return ""
    base = _node_name(cleaned)
    key = _pd_key(base)
    return f"pd{key[1]}" if key is not None else base


def _identity_details(inspection: DeviceInspection) -> dict[str, Any]:
    fingerprint = inspection.fingerprint
    return {
        "node": inspection.device.node,
        "serial": fingerprint.serial.value,
        "model": fingerprint.model,
        "capacity_bytes": fingerprint.capacity_bytes,
        "interface": str(fingerprint.interface),
        "source": fingerprint.source,
    }


def _cause_value(gate: GateCheck) -> str:
    """`GateCheck` already guarantees an UNKNOWN verdict carries a cause."""
    cause = gate.evidence.unknown_cause
    return str(cause) if cause is not None else ""


def _gate_details(inspection: DeviceInspection, gate: GateCheck) -> dict[str, Any]:
    cause = gate.evidence.unknown_cause
    return {
        "node": inspection.device.node,
        "verdict": gate.verdict.value,
        "unknown_cause": None if cause is None else cause.value,
        "evidence": gate.evidence.model_dump(mode="json"),
        "serial": inspection.fingerprint.serial.value,
    }


def _kind_or_error(kind: str) -> DeviceKind:
    try:
        return DeviceKind(str(kind).strip().upper())
    except ValueError as exc:
        expected = [k.value for k in DeviceKind]
        raise ValidationError(f"unknown device kind {kind!r}; expected {KIND_ALL!r} or {expected}") from exc


def default_adapter() -> DeviceAdapter:
    """The platform's real adapter, or the file adapter on an explicitly named root.

    A file adapter is never rooted at the current directory: `Path.cwd()` would make an
    ordinary working directory enumerate as if it were a set of block devices, and a
    directory can hold anything. With no OS adapter and no root, this refuses rather
    than guessing [D27].
    """
    adapter = os_adapter()
    if adapter is not None:
        return adapter
    root = os.environ.get(ENV_DEVICE_ROOT, "").strip()
    if not root:
        raise ValidationError(
            "No device adapter for this platform. Set "
            f"{ENV_DEVICE_ROOT} to the directory holding synthetic disks, or install Trace on Linux or Windows."
        )
    from trace_core.devices.file_device import FileDevice

    return FileDevice(root)


def os_adapter() -> DeviceAdapter | None:
    """The real-hardware adapter for this platform, or None when there is none.

    [D27] `TRACE_DEVICE_ADAPTER` selects the adapter but never bypasses the
    `--allow-real-hardware` opt-in, so selection is not a privilege decision.
    """
    from trace_core.devices.linux import LinuxDevice
    from trace_core.devices.win32 import Win32Device

    chosen = os.environ.get(ENV_ADAPTER, "").strip().lower() or "auto"
    if chosen == "linux":
        return LinuxDevice()
    if chosen == "win32":
        return Win32Device()
    if chosen != "auto":
        return None
    if sys.platform.startswith("linux"):
        return LinuxDevice()
    return Win32Device() if sys.platform == "win32" else None


def _fill_ports(
    enumerator: DeviceEnumerator | None,
    inspector: DeviceInspector | None,
    probe: WriteBlockerProbe | None,
) -> tuple[DeviceEnumerator, DeviceInspector, WriteBlockerProbe]:
    """One shared default for every port left unfilled, so a partial injection cannot leave None."""
    if enumerator is not None and inspector is not None and probe is not None:
        return enumerator, inspector, probe
    adapter = default_adapter()
    return (
        enumerator if enumerator is not None else adapter,
        inspector if inspector is not None else adapter,
        probe if probe is not None else adapter,
    )
