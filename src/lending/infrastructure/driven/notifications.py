"""Notification adapters.

Both are trivial, and that is the point worth noticing: the use cases do not
care.  ``BorrowBook`` calls ``loan_confirmed`` and moves on.  Replacing the
console with SES, a Slack webhook or an outbox table is a new class in this file
and one line in the composition root; the use case and its tests are untouched.

Observe that neither adapter formats business rules into its message.  They
render facts they were given (``late_fee`` was computed by the policy).  If a
notifier started deciding *whether* a fee applies, the rule would have escaped
the hexagon.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from lending.domain.model import Book, Loan, Member

__all__ = ["ConsoleNotifier", "NullNotifier", "LoggingNotifier"]

_logger = logging.getLogger("lending.notifications")


class ConsoleNotifier:
    """Satisfies ``NotificationPort`` by printing. Good enough for a demo run."""

    def loan_confirmed(self, *, member: Member, book: Book, loan: Loan) -> None:
        print(
            f"[notification] to {member.email}: you borrowed {book.title!r} "
            f"(loan {loan.loan_id}), due {loan.due_on.isoformat()}."
        )

    def loan_returned(
        self, *, member: Member, book: Book, loan: Loan, late_fee: Decimal
    ) -> None:
        settlement = "no fee owed" if late_fee == 0 else f"fee owed: {late_fee}"
        print(
            f"[notification] to {member.email}: thanks for returning {book.title!r} "
            f"(loan {loan.loan_id}); {settlement}."
        )


class LoggingNotifier:
    """Satisfies ``NotificationPort`` through the logging module.

    The sensible default for a server: structured, level-controlled, and it does
    not interleave with uvicorn's own output the way ``print`` does.
    """

    def loan_confirmed(self, *, member: Member, book: Book, loan: Loan) -> None:
        _logger.info(
            "loan confirmed",
            extra={
                "member_id": str(member.member_id),
                "isbn": str(book.isbn),
                "loan_id": str(loan.loan_id),
                "due_on": loan.due_on.isoformat(),
            },
        )

    def loan_returned(
        self, *, member: Member, book: Book, loan: Loan, late_fee: Decimal
    ) -> None:
        _logger.info(
            "loan returned",
            extra={
                "member_id": str(member.member_id),
                "isbn": str(book.isbn),
                "loan_id": str(loan.loan_id),
                "late_fee": str(late_fee),
            },
        )


class NullNotifier:
    """Satisfies ``NotificationPort`` by doing nothing.

    Used by the HTTP tests so the suite stays quiet. A null adapter is also the
    honest way to disable a side effect in an environment: the use case still
    calls the port, so the code path under test is the real one.
    """

    def loan_confirmed(self, *, member: Member, book: Book, loan: Loan) -> None:
        return None

    def loan_returned(
        self, *, member: Member, book: Book, loan: Loan, late_fee: Decimal
    ) -> None:
        return None
