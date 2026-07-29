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

        # 0.3.6 automations. Kept alongside --scheduled-action, not instead of it:
        # the tasks the old schedule created still call that argument, and a user
        # who rolls back to 0.3.5 would otherwise be left with Windows tasks
        # invoking a switch that build has never heard of.
        #
        # Both switches do the same thing, because a task invocation only means
        # "something is due" — the process decides *which* rule may run, so that
        # several tasks coming due together cannot each apply their own. --run-rule
        # carries the waking task's id for the journal and nothing more.
        if "--run-automations" in sys.argv or "--run-rule" in sys.argv:
            woken_by = ""
            if "--run-rule" in sys.argv:
                index = sys.argv.index("--run-rule")
                woken_by = sys.argv[index + 1] if index + 1 < len(sys.argv) else ""
            from app.automation.headless import run_automations

            return run_automations(woken_by=woken_by)

        from app.main_window import run

        run()
    except Exception:
        path = write_current_exception(context="startup")
        print(f"Crash log saved to: {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
