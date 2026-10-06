"""Device renderers. One dispatch per shape, reused by the CLI, shell and TUI.

Verdict colours are derived from the existing theme tokens rather than a private palette,
so a theme change reaches the device panels without a second edit.
"""

from typing import Any

from rich.markup import escape

from trace_core.core.ui.renderers import (
    console,
    render_minimalist_table,
    render_output,
)
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.devices.domain import WpVerdict
from trace_core.devices.dto import DeviceInfoDto, FingerprintDto, InspectionDto, WpCheckDto
from trace_core.devices.service import short_id

VERDICT_STYLES: dict[str, tuple[str, str]] = {
    WpVerdict.READ_ONLY.value: ("READ ONLY", THEME_TOKENS["status_closed"]),
    WpVerdict.WRITABLE.value: ("WRITABLE", THEME_TOKENS["status_archived"]),
    WpVerdict.UNKNOWN.value: ("UNKNOWN", THEME_TOKENS["status_review"]),
}


def format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def verdict_style(verdict: str) -> tuple[str, str]:
    """Label and style for a write-protection verdict. An unmapped value is never guessed."""
    return VERDICT_STYLES.get(
        verdict,
        (verdict.replace("_", " ").upper(), THEME_TOKENS["value"]),
    )


def render_devices(devices: list[DeviceInfoDto], output: str = "table") -> None:
    render_output(output, [d.model_dump(mode="json") for d in devices], lambda: _devices_table(devices))


def _devices_table(devices: list[DeviceInfoDto]) -> None:
    columns = [
        ("ID", {"style": THEME_TOKENS["label"]}),
        ("NODE", {"style": THEME_TOKENS["label"]}),
        ("KIND", {"style": THEME_TOKENS["label"]}),
        ("SIZE", {"style": THEME_TOKENS["label"], "justify": "right"}),
        ("MODEL", {"style": THEME_TOKENS["label"]}),
        ("REAL HW", {"style": THEME_TOKENS["label"]}),
    ]
    rows: list[list[Any]] = [
        [
            short_id(device.node),
            escape(device.node),
            device.kind.value,
            format_bytes(device.size_bytes),
            escape(device.model_hint or "-"),
            "yes" if device.requires_real_hardware_opt_in else "no",
        ]
        for device in devices
    ]
    render_minimalist_table(
        title="Devices",
        columns=columns,
        rows=rows,
        empty_message="No block devices visible to this adapter.",
    )


def render_inspection(inspection: InspectionDto, output: str = "table") -> None:
    render_output(output, inspection.model_dump(mode="json"), lambda: _inspection_card(inspection))


def _fingerprint_rows(fingerprint: FingerprintDto) -> list[list[Any]]:
    return [
        ["Serial", escape(fingerprint.serial)],
        ["Model", escape(fingerprint.model)],
        ["Capacity", format_bytes(fingerprint.capacity_bytes)],
        ["Firmware", escape(fingerprint.firmware or "-")],
        ["Interface", fingerprint.interface.value],
        ["WWN", escape(fingerprint.wwn or "-")],
        ["Source", fingerprint.source],
    ]


def _inspection_card(inspection: InspectionDto) -> None:
    console.print("")
    console.print(f"  [bold]Device[/bold] [cyan]{escape(inspection.device.node)}[/cyan]")
    console.print("")
    console.print(
        f"  [dim]{escape(inspection.fingerprint.source)} observation at {inspection.inspected_at.isoformat()}[/dim]"
    )
    console.print("")
    columns = [("FIELD", {"style": THEME_TOKENS["label"]}), ("VALUE", {"style": THEME_TOKENS["value"]})]
    render_minimalist_table(
        title="Fingerprint",
        columns=columns,
        rows=_fingerprint_rows(inspection.fingerprint),
        tight=True,
    )
    console.print("")


def render_gate(check: WpCheckDto, output: str = "table") -> None:
    render_output(output, check.model_dump(mode="json"), lambda: _gate_card(check))


def _gate_card(check: WpCheckDto) -> None:
    label, style = verdict_style(check.verdict.value)
    colour = THEME_HEX["red"] if check.verdict is WpVerdict.WRITABLE else THEME_HEX["amber"]
    console.print("")
    console.print(f"  [{style}]Write protection:[/] [{colour}]{label}[/{colour}]")
    if check.unknown_cause:
        console.print(f"  [{THEME_TOKENS['muted']}]Cause:[/] {escape(check.unknown_cause)}")
    console.print("")
    columns = [
        ("CHECK", {"style": THEME_TOKENS["label"]}),
        ("RESULT", {"style": THEME_TOKENS["label"]}),
        ("DETAIL", {"style": THEME_TOKENS["label"]}),
    ]
    rows = [[escape(c.name), escape(c.result), escape(c.detail or "-")] for c in check.checks]
    render_minimalist_table(
        title=f"Evidence ({check.platform} / {escape(check.adapter_version)})",
        columns=columns,
        rows=rows,
        tight=True,
    )
    console.print("")
