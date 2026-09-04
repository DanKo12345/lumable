"""What has changed since the last time anybody was told anything.

A status on its own cannot say whether it is worth mentioning. The same one is
produced every hour by a check that found nothing new, and writing it down each
time turns a log into a metronome: an expired confirmation, or a clock somebody
has not got round to fixing, would fill the file with one identical line until
there was nothing else in it. Then the entry that mattered is buried under two
hundred copies of the entry that did not.

So the memory of the last state lives here, next to the decision that uses it,
rather than as a stray attribute on a window. It also keeps the window from
having to remember anything, which is the sort of thing windows forget when
somebody adds a second place that updates them.
"""

from __future__ import annotations

from app.license_status import CHECKING, Facts, Status, status


class LicenseStatusPresenter:
    def __init__(self) -> None:
        self._last_state: str | None = None

    def update(self, facts: Facts) -> tuple[Status, bool]:
        """The status to show, and whether this is news.

        News means the state is different from the one before it. Coming back to
        a state after leaving it counts: something changed and then changed
        back, and both are worth a line.
        """
        answer = status(facts)
        worth_saying = bool(answer.message) and answer.state != self._last_state

        if answer.state == CHECKING:
            # A moment rather than an event, and one that happens on every press
            # of the button. Recording it would also lose the state underneath
            # it, so that returning to the same problem afterwards would look
            # like news when nothing had moved.
            return answer, False

        self._last_state = answer.state
        return answer, worth_saying
