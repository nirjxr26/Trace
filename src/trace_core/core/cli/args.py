"""Reusable argument and flag parsing utilities for interactive shell feature handlers."""


def extract_flag_value(args: list[str], *flags: str) -> str | None:
    """Extract the value following any of the specified flags (e.g. --output json)."""
    for i, arg in enumerate(args):
        if arg in flags and i + 1 < len(args):
            return args[i + 1]
    return None


def has_flag(args: list[str], *flags: str) -> bool:
    """Check if any of the specified flags are present."""
    return any(arg in flags for arg in args)


def strip_flags(args: list[str], flags_with_values: tuple[str, ...] = ()) -> list[str]:
    """Filter out flags and their associated values, returning positional arguments."""
    pos_args: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in flags_with_values:
            skip_next = True
            continue
        if not arg.startswith("-"):
            pos_args.append(arg)
    return pos_args
