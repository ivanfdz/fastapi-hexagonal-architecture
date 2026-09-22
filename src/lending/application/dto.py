"""Commands, queries and views: the data that crosses the application boundary.

Two rules are being enforced by this module existing at all.

**Nothing outside gets a domain object.**  Use cases accept commands and return
views, never ``Loan`` or ``Member``.  If a route handler held a real ``Loan`` it
could mutate it, serialise its internals into a public contract, or quietly
depend on a field the domain wanted to rename.  Views make the published shape
explicit and let the model evolve behind it.

**Nothing inside gets a framework type.**  These are plain frozen dataclasses,
not Pydantic models, so the application layer stays importable with zero
dependencies and one obvious answer to "where does validation happen?":
structural validation at the edge (Pydantic, in the HTTP adapter), business
validation in the domain (``ISBN``, ``LoanPolicy``).  Using Pydantic here too is
a perfectly common shortcut; the cost is that the core stops being framework-free
and the two kinds of validation start blurring together.  The README expands on
the trade-off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lending.domain.model import Book, Loan
from lending.domain.policy import LoanPolicy

__all__ = [
    "BookView",
    "BorrowBookCommand",
    "ListMemberLoansQuery",
    "LoanView",
    "ReturnBookCommand",
    "book_view",
    "loan_view",
]


@dataclass(frozen=True, slots=True)
class BorrowBookCommand:
    """A request to lend a copy. Strings, not value objects, on purpose: the
    caller is untrusted, so parsing into ``ISBN`` is the use case's job and an
    invalid ISBN becomes a domain error instead of an adapter crash."""

    member_id: str
    isbn: str


@dataclass(frozen=True, slots=True)
class ReturnBookCommand:
    loan_id: str


@dataclass(frozen=True, slots=True)
class ListMemberLoansQuery:
    member_id: str
    include_returned: bool = False


@dataclass(frozen=True, slots=True)
class LoanView:
    """A loan as the outside world sees it.

    Note what has been added relative to the entity: ``title`` (joined from the
    catalogue, because a client showing a loan always wants it) and ``late_fee``
    (derived through the policy).  Note what has been dropped: nothing mutable.
    """

    loan_id: str
    isbn: str
    title: str
    member_id: str
    borrowed_on: date
    due_on: date
    returned_on: date | None
    is_open: bool
    days_overdue: int
    late_fee: Decimal


@dataclass(frozen=True, slots=True)
class BookView:
    isbn: str
    title: str
    author: str
    total_copies: int
    copies_available: int


def loan_view(*, loan: Loan, book: Book, as_of: date, policy: LoanPolicy) -> LoanView:
    """Project a loan into its published shape.

    ``as_of`` is passed in rather than read from the clock so the projection is a
    pure function: same inputs, same output, trivially testable.
    """
    days_overdue = loan.days_overdue(as_of)
    return LoanView(
        loan_id=str(loan.loan_id),
        isbn=str(loan.isbn),
        title=book.title,
        member_id=str(loan.member_id),
        borrowed_on=loan.borrowed_on,
        due_on=loan.due_on,
        returned_on=loan.returned_on,
        is_open=loan.is_open,
        days_overdue=days_overdue,
        late_fee=policy.late_fee_for(days_overdue),
    )


def book_view(*, book: Book, copies_on_loan: int) -> BookView:
    return BookView(
        isbn=str(book.isbn),
        title=book.title,
        author=book.author,
        total_copies=book.total_copies,
        copies_available=book.copies_available(copies_on_loan),
    )
