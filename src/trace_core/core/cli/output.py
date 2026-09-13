"""Shared CLI output-format parsing for table/json commands."""

from trace_core.core.cli.args import extract_flag_value

OUTPUT_CHOICES = [("table", "Table view"), ("json", "JSON view")]


def parse_output_format(args: list[str] | None = None, default: str = "table") -> str:
    """Parse --output/-o flag into normalized table|json value."""
    if not args:
        return default
    return (extract_flag_value(args, "--output", "-o") or default).lower()
