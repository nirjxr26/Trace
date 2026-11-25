"""Fast console-script entrypoint."""


def main() -> None:
    import sys

    if sys.argv[1:] == ["tui"]:
        from trace_core.tui.app import run_tui

        run_tui()
        return

    from trace_core.cli.main import app

    app()
