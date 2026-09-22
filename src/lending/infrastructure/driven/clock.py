"""Clock adapters.

Yes, "what day is it" is infrastructure.  It is a read from outside the process,
non-deterministic and not under the application's control, which is the same
description as a database read.  Treating it as a port is what allows
``tests/application`` to assert an exact late fee instead of approximating one.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

__all__ = ["SystemClock", "UTCClock", "FrozenClock"]


class SystemClock:
    """Satisfies ``Clock`` using the machine's local date."""

    def today(self) -> date:
        return date.today()


class UTCClock:
    """Satisfies ``Clock`` using UTC.

    The better default for a server: with a local clock, a loan created at
    23:30 in Madrid and one created at 00:30 fall on different days depending on
    where the container happens to run, and due dates stop being reproducible.
    """

    def today(self) -> date:
        return datetime.now(timezone.utc).date()


class FrozenClock:
    """Satisfies ``Clock`` with a date you control.

    It lives in ``src`` rather than in ``tests`` because it is genuinely useful
    outside the suite: seeding a demo dataset with overdue loans, or reproducing
    a bug that only happens at a month boundary.
    """

    def __init__(self, today: date) -> None:
        self._today = today

    def today(self) -> date:
        return self._today

    def set(self, today: date) -> None:
        self._today = today
