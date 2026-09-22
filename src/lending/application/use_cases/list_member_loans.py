"""Use case: list the loans of one member.

A read-only use case, and a deliberately boring one.  It exists to make two
points.

First, queries are use cases too.  The temptation is to let the HTTP layer
"just call the repository" for reads, and the moment that happens the projection
logic (joining titles, computing accrued fees) ends up duplicated in every
adapter that needs it.

Second, this is where a CQRS split would begin if the read volume ever justified
it: swap the repository calls for a denormalised read model behind the same
driving port and no caller notices.  Until then, reusing the write-side
repositories is the right amount of machinery.
"""

from __future__ import annotations

from typing import Sequence

from lending.application.dto import ListMemberLoansQuery, LoanView, loan_view
from lending.application.ports.driven import (
    BookRepository,
    Clock,
    LoanRepository,
    MemberRepository,
)
from lending.domain.errors import MemberNotFoundError
from lending.domain.model import Book, MemberId
from lending.domain.policy import LoanPolicy

__all__ = ["ListMemberLoans"]


class ListMemberLoans:
    """Implements ``ListMemberLoansUseCase``."""

    def __init__(
        self,
        *,
        books: BookRepository,
        members: MemberRepository,
        loans: LoanRepository,
        clock: Clock,
        policy: LoanPolicy,
    ) -> None:
        self._books = books
        self._members = members
        self._loans = loans
        self._clock = clock
        self._policy = policy

    def execute(self, query: ListMemberLoansQuery) -> Sequence[LoanView]:
        member_id = MemberId(query.member_id)
        if self._members.get(member_id) is None:
            # An empty list would be ambiguous: no loans, or no such member?
            # Distinguishing them is a courtesy the caller cannot provide itself.
            raise MemberNotFoundError("No such member.", member_id=query.member_id)

        today = self._clock.today()
        loans = self._loans.list_for_member(member_id, include_returned=query.include_returned)

        # Titles are cached per ISBN because a member typically holds a handful
        # of loans and repeating the lookup per row is how an N+1 starts. Note
        # that this is a perfectly ordinary optimisation and it stays inside the
        # use case: no adapter had to grow a bespoke join to enable it.
        titles: dict[str, Book] = {}
        views: list[LoanView] = []
        for loan in loans:
            key = str(loan.isbn)
            book = titles.get(key)
            if book is None:
                found = self._books.get(loan.isbn)
                if found is None:
                    # A loan for a de-catalogued title is still a real debt, so
                    # it is reported with a placeholder rather than hidden.
                    book = Book(
                        isbn=loan.isbn,
                        title="(no longer in catalogue)",
                        author="unknown",
                        total_copies=1,
                    )
                else:
                    book = found
                titles[key] = book
            views.append(loan_view(loan=loan, book=book, as_of=today, policy=self._policy))

        # Most recent first: the ordering a UI almost always wants, decided once
        # here instead of separately in every adapter.
        views.sort(key=lambda view: (view.borrowed_on, view.loan_id), reverse=True)
        return tuple(views)
