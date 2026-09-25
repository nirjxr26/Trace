"""Shared CLI output-format parsing for table/json commands."""

from trace_core.core.cli.args import extract_flag_value

OUTPUT_CHOICES = [("table", "Table view"), ("json", "JSON view")]
OUTPUT_HELP = "table|json"
SKIP_CONFIRM_HELP = "Skip confirmation prompt"


def parse_output_format(args: list[str] | None = None, default: str = "table") -> str:
    """Parse --output/-o flag into normalized table|json value. Unknown values fail loudly."""
    if not args:
        return default
    value = (extract_flag_value(args, "--output", "-o") or default).lower()
    if value not in ("table", "json"):
        from trace_core.core.errors import ValidationError

        raise ValidationError(f"Invalid output format '{value}'. Valid: table, json.")
    return value
