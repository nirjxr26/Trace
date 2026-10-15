"""Device renderers. One dispatch per shape, reused by the CLI, shell and TUI.

Verdict colours are derived from the existing theme tokens rather than a private palette,
so a theme change reaches the device panels without a second edit.
"""

import re
from typing import Any

from rich.markup import escape

from trace_core.core.ui.renderers import (
    console,
    render_minimalist_table,
    render_output,
)
from trace_core.core.ui.theme import THEME_HEX, THEME_TOKENS
from trace_core.devices.domain import WpVerdict
from trace_core.devices.dto import DeviceInfoDto, FingerprintDto, InspectionDto, ObservationDto, WpCheckDto
from trace_core.devices.service import short_id

VERDICT_STYLES: dict[str, tuple[str, str]] = {
    WpVerdict.READ_ONLY.value: ("READ ONLY", THEME_TOKENS["status_closed"]),
    WpVerdict.WRITABLE.value: ("WRITABLE", THEME_TOKENS["status_archived"]),
    WpVerdict.UNKNOWN.value: ("UNKNOWN", THEME_TOKENS["status_review"]),
}


_PART_NUMBER = re.compile(r"(?<!-)[ _]+(?=[A-Z0-9]*\d)[A-Z0-9]{4,}(?:_[A-Z0-9]{2,})*$")
_CAPACITY_SUFFIX = re.compile(
    r"\s+\d+(?:\.\d+)?\s?(?:TB|GB|MB)\b|\s+USB\s?3\.0\b|\s+External\b",
    re.IGNORECASE,
)


_DRIVE_PREFIX = "physicaldrive"


def display_node(node: str) -> str:
    """A human name for a device node. `\\\\.\\PhysicalDrive0` reads as `Drive 0`.

    A node is an OS handle, not something an examiner recognises a disk by. Falls back to
    the trailing path component for file-backed adapters, where the name is meaningful.
    """
    name = node.replace("\\", "/").rsplit("/", 1)[-1] or node
    if name.lower().startswith(_DRIVE_PREFIX):
        index = name[len(_DRIVE_PREFIX) :]
        return f"Drive {index}" if index else "Drive"
    return name


def readable_model(model: str) -> str:
    """Strip the part number and capacity a vendor appends, keeping the product name.

    `NVMe Micron_2400_MTFDKBA512QFM` reads as `NVMe Micron`, `Samsung SSD 990 PRO 2TB` as
    `Samsung SSD 990 PRO`. Only an underscore-joined tail is treated as a part number:
    a hyphen joins a real model to its revision (`WDC WD10EZEX-08W`), so it is kept.
    Display only - the raw string stays on `Model` and in every stored observation.
    """
    text = _PART_NUMBER.sub("", model).strip(" _-")
    text = _CAPACITY_SUFFIX.sub("", text).strip(" _-,")
    return text or model


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
        ("SERIAL", {"style": THEME_TOKENS["label"]}),
        ("REAL HW", {"style": THEME_TOKENS["label"]}),
    ]
    rows: list[list[Any]] = [
        [
            short_id(device.node),
            escape(device.node),
            device.kind.value,
            format_bytes(device.size_bytes),
            escape(device.model_hint or "-"),
            escape(device.serial or "-"),
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


def render_inspection(inspection: InspectionDto, output: str = "table", case_numbers: list[str] | None = None) -> None:
    render_output(output, inspection.model_dump(mode="json"), lambda: _inspection_card(inspection, case_numbers))


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


def _inspection_card(inspection: InspectionDto, case_numbers: list[str] | None = None) -> None:
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
    if case_numbers:
        from trace_core.core.ui.renderers import render_section_title

        console.print("")
        render_section_title("CASES")
        console.print("")
        for number in case_numbers:
            console.print(f"    {escape(number)}")
    console.print("")


def render_history(observations: list[ObservationDto], output: str = "table") -> None:
    render_output(output, [o.model_dump(mode="json") for o in observations], lambda: _history_table(observations))


def _history_table(observations: list[ObservationDto]) -> None:
    columns = [
        ("OBSERVED", {"style": THEME_TOKENS["label"]}),
        ("SERIAL", {"style": THEME_TOKENS["label"]}),
        ("MODEL", {"style": THEME_TOKENS["label"]}),
        ("VERDICT", {"style": THEME_TOKENS["label"]}),
    ]
    rows: list[list[Any]] = [
        [
            observation.inspected_at.isoformat(),
            escape(observation.serial),
            escape(observation.model),
            escape(observation.verdict.value if observation.verdict else "-"),
        ]
        for observation in observations
    ]
    render_minimalist_table(
        title="Device History",
        columns=columns,
        rows=rows,
        empty_message="No observations recorded for this device.",
    )


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


def device_heading(node: str, model: str | None, capacity_bytes: int | None) -> str:
    """How a device is named wherever it appears: the recorded model and its capacity.

    Falls back to the node rather than an invented name - a device filed but never
    inspected has no model, and "Drive 0" is a name nobody saw. The model is shown exactly
    as recorded: `readable_model` shortens a vendor part number into a product name, which
    is right for a narrow list column and wrong in a record, because the part number is what
    identifies the drive.
    """
    parts = [part for part in (model, format_bytes(capacity_bytes) if capacity_bytes else "") if part]
    return "  \u00b7  ".join(parts) or node
