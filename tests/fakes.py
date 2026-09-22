"""Hand-written test doubles.

There is not a single ``unittest.mock`` in this suite, and that is a direct
consequence of the architecture.  Mocks are what you reach for when a dependency
is unreachable -- buried in a module-level import, constructed inside the
function under test, or hidden behind a global.  When every collaborator arrives
through a constructor, a fake is a small honest class instead.

The difference shows up when you refactor.  ``mock.patch("module.date")`` breaks
the moment the import moves.  ``FixedClock`` keeps working, because it satisfies a
contract rather than impersonating an implementation.

The repository fakes are not here: the real in-memory adapters in
``lending.infrastructure.driven.memory`` already serve that role, and they are
covered by the same contract suite as the SQLite ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from lending.domain.model import Book, Loan, Member

__all__ = ["FixedClock", "RecordingNotifier", "SpyNotification"]


class FixedClock:
    """Satisfies ``Clock``. The date is whatever you say it is."""

    def __init__(self, today: date) -> None:
        self._today = today

    def today(self) -> date:
        return self._today

    def set(self, today: date) -> None:
        self._today = today

    def advance(self, days: int) -> date:
        """Move time forward, which is how the overdue tests reach their state
        without sleeping or patching anything."""
        self._today += timedelta(days=days)
        return self._today


@dataclass(frozen=True, slots=True)
class SpyNotification:
    kind: str
    member_id: str
    isbn: str
    loan_id: str
    late_fee: Decimal | None = None


@dataclass
class RecordingNotifier:
    """Satisfies ``NotificationPort`` by remembering what it was asked to send.

    Lets a test assert that borrowing notified the member exactly once, which is
    behaviour worth pinning down and is invisible from the HTTP response.
    """

    sent: list[SpyNotification] = field(default_factory=list)

    def loan_confirmed(self, *, member: Member, book: Book, loan: Loan) -> None:
        self.sent.append(
            SpyNotification(
                kind="loan_confirmed",
                member_id=str(member.member_id),
                isbn=str(book.isbn),
                loan_id=str(loan.loan_id),
            )
        )

    def loan_returned(
        self, *, member: Member, book: Book, loan: Loan, late_fee: Decimal
    ) -> None:
        self.sent.append(
            SpyNotification(
                kind="loan_returned",
                member_id=str(member.member_id),
                isbn=str(book.isbn),
                loan_id=str(loan.loan_id),
                late_fee=late_fee,
            )
        )

    def kinds(self) -> list[str]:
        return [notification.kind for notification in self.sent]
