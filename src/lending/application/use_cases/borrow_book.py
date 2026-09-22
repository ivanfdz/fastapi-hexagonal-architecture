"""Use case: lend a copy of a title to a member.

This is the file to read if you only read one.  It is the richest operation in
the system and it is still only about twenty lines of logic, because a use case
does exactly four things and nothing else:

1. Translate primitives from the caller into domain types (``ISBN``).
2. Load what it needs through driven ports.
3. Ask the domain to decide (``LoanPolicy``, ``Loan.open``).
4. Persist, notify, and project the result into a view.

There is no SQL, no ``session.commit()``, no HTTP status code, no ``if
settings.env == "prod"``.  Every collaborator arrives through the constructor,
which is why the test for this file needs no database, no network and no
monkeypatching, and why pointing the whole thing at Postgres is a change in one
other file.
"""

from __future__ import annotations

from lending.application.dto import BorrowBookCommand, LoanView, loan_view
from lending.application.ports.driven import (
    BookRepository,
    Clock,
    LoanRepository,
    MemberRepository,
    NotificationPort,
)
from lending.domain.errors import BookNotFoundError, MemberNotFoundError
from lending.domain.model import ISBN, Loan, MemberId
from lending.domain.policy import LoanPolicy

__all__ = ["BorrowBook"]


class BorrowBook:
    """Implements ``BorrowBookUseCase``.

    Note the absence of an explicit ``implements`` or a base class: the protocol
    is structural, so this class satisfies the driving port simply by having an
    ``execute`` with the right signature.
    """

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
        # Keyword-only arguments: six collaborators of similar shape are very
        # easy to mis-order positionally, and the composition root is the only
        # caller, so the extra verbosity costs nothing.
        self._books = books
        self._members = members
        self._loans = loans
        self._notifications = notifications
        self._clock = clock
        self._policy = policy

    def execute(self, command: BorrowBookCommand) -> LoanView:
        # 1. Parse. ``ISBN`` raises InvalidISBNError on a malformed value, so
        #    from here on the rest of the method works with a valid identifier.
        isbn = ISBN(command.isbn)
        member_id = MemberId(command.member_id)

        # 2. Load. "Not found" is a business decision, so the repository's None
        #    becomes a domain error here rather than inside the adapter.
        member = self._members.get(member_id)
        if member is None:
            raise MemberNotFoundError("No such member.", member_id=command.member_id)

        book = self._books.get(isbn)
        if book is None:
            raise BookNotFoundError("This title is not in the catalogue.", isbn=str(isbn))

        today = self._clock.today()

        # 3. Gather the facts the policy needs, then let the policy judge them.
        #    The use case asks the questions; it does not answer them.
        self._policy.ensure_member_may_borrow(
            member=member,
            book=book,
            open_loans_by_member=self._loans.count_open_for_member(member_id),
            overdue_loans_by_member=self._loans.count_overdue_for_member(member_id, today),
            copies_on_loan=self._loans.count_open_for_isbn(isbn),
            member_already_holds_title=self._loans.has_open_loan(member_id, isbn),
        )

        # 4. Mutate state through the domain, then persist and announce it.
        loan = Loan.open(
            loan_id=self._loans.next_identity(),
            isbn=isbn,
            member_id=member_id,
            borrowed_on=today,
            loan_period_days=self._policy.loan_period_days,
        )
        self._loans.add(loan)

        # Notification comes after persistence: a member who is told they have a
        # book should have a record of it. In a real system with a real broker
        # this is where you would publish through an outbox rather than inline,
        # and the port shape would not change.
        self._notifications.loan_confirmed(member=member, book=book, loan=loan)

        return loan_view(loan=loan, book=book, as_of=today, policy=self._policy)
