"""Reusable argument and flag parsing utilities for interactive shell feature handlers."""


def extract_flag_value(args: list[str], *flags: str) -> str | None:
    """Extract the value following any of the specified flags (e.g. --output json)."""
    for i, arg in enumerate(args):
        if arg in flags and i + 1 < len(args):
            return args[i + 1]
    return None


def extract_positional(args: list[str], *value_flags: str) -> list[str]:
    """Positional tokens excluding flags and their values. Single source for identifier resolution."""
    found: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in value_flags:
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                skip_next = True
            continue
        if arg.startswith("-"):
            continue
        found.append(arg)
    return found


def has_flag(args: list[str], *flags: str) -> bool:
    """Check if any of the specified flags are present."""
    return any(arg in flags for arg in args)


def extract_int_flag(args: list[str], default: int, *flags: str) -> int:
    """Extract an integer flag value. Raises ValidationError on non-integers."""
    from trace_core.core.errors import ValidationError

    raw = extract_flag_value(args, *flags)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValidationError(f"Invalid integer value '{raw}' for {'/'.join(flags)}.") from None


def extract_str_flag(args: list[str], default: str, *flags: str) -> str:
    """Extract a string flag value with default. Single source for `or default` chains."""
    return extract_flag_value(args, *flags) or default
