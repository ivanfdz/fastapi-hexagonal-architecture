"""Use case: take a borrowed copy back and settle any late fee.

Worth contrasting with ``borrow_book``: this one delegates its central rule to
the entity instead of the policy.  "A loan can only be closed once" concerns a
single loan and needs no other data, so ``Loan.close`` owns it and raises
``LoanAlreadyReturnedError`` itself.  Deciding what lateness *costs* does depend
on configuration, so that stays in ``LoanPolicy``.

The heuristic: rules that a single entity can verify from its own fields belong
on the entity; rules that need several entities, aggregates or configured
thresholds belong in a policy.
"""

from __future__ import annotations

from lending.application.dto import LoanView, ReturnBookCommand, loan_view
from lending.application.ports.driven import (
    BookRepository,
    Clock,
    LoanRepository,
    MemberRepository,
    NotificationPort,
)
from lending.domain.errors import BookNotFoundError, LoanNotFoundError, MemberNotFoundError
from lending.domain.model import LoanId
from lending.domain.policy import LoanPolicy

__all__ = ["ReturnBook"]


class ReturnBook:
    """Implements ``ReturnBookUseCase``."""

    def __init__(
        self,
        *,
        books: BookRepository,
        members: MemberRepository,
        loans: LoanRepository,
        notifications: NotificationPort,
        clock: Clock,
        policy: LoanPolicy,
    ) -> None:
        self._books = books
        self._members = members
        self._loans = loans
        self._notifications = notifications
        self._clock = clock
        self._policy = policy

    def execute(self, command: ReturnBookCommand) -> LoanView:
        loan_id = LoanId(command.loan_id)

        loan = self._loans.get(loan_id)
        if loan is None:
            raise LoanNotFoundError("No such loan.", loan_id=command.loan_id)

        member = self._members.get(loan.member_id)
        if member is None:
            # Referential damage, not a user mistake: a stored loan points at a
            # member who is gone. Surfaced as a domain error rather than an
            # AttributeError three frames later.
            raise MemberNotFoundError(
                "The loan references a member that no longer exists.",
                member_id=str(loan.member_id),
            )

        book = self._books.get(loan.isbn)
        if book is None:
            raise BookNotFoundError(
                "The loan references a title that is no longer catalogued.",
                isbn=str(loan.isbn),
            )

        today = self._clock.today()

        # The entity performs the transition and reports the lateness; the policy
        # prices it. Two different kinds of knowledge, two different owners.
        days_overdue = loan.close(today)
        late_fee = self._policy.late_fee_for(days_overdue)

        self._loans.update(loan)
        self._notifications.loan_returned(
            member=member, book=book, loan=loan, late_fee=late_fee
        )

        return loan_view(loan=loan, book=book, as_of=today, policy=self._policy)
