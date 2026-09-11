"""Backward-compatible re-export of UI renderers."""

from trace_core.cli.ui.renderers import (
    console,
    format_status_badge,
    render_case_detail,
    render_case_table,
    render_entity_panel,
    render_json,
    render_table,
)

__all__ = [
    "console",
    "format_status_badge",
    "render_case_detail",
    "render_case_table",
    "render_entity_panel",
    "render_json",
    "render_table",
]
