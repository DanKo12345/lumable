from __future__ import annotations

import sys

from app.crash_logging import install_crash_logging, write_current_exception


def main() -> int:
    install_crash_logging()
    try:
        if "--scheduled-action" in sys.argv:
            index = sys.argv.index("--scheduled-action")
            action = sys.argv[index + 1] if index + 1 < len(sys.argv) else ""
            from app.scheduled_action import run_scheduled_action

            return run_scheduled_action(action)

        from app.main_window import run

        run()
    except Exception:
        path = write_current_exception(context="startup")
        print(f"Crash log saved to: {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
