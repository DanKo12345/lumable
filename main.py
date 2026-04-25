from __future__ import annotations

import sys

from app.crash_logging import install_crash_logging, write_current_exception


def main() -> int:
    install_crash_logging()
    try:
        from app.main_window import run

        run()
    except Exception:
        path = write_current_exception(context="startup")
        print(f"Crash log saved to: {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
