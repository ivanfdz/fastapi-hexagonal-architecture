"""Driven ports, also called secondary or outbound ports.

These are the interfaces the application *needs*: storage, notifications, the
current date.  The direction of the dependency is the whole trick.  The
application declares what it wants, in its own vocabulary, and infrastructure
comes along afterwards and satisfies it.  Nothing here imports an adapter, so a
reader can see the full set of external facilities the use cases rely on without
opening a single infrastructure file.

Why ``typing.Protocol`` rather than ``abc.ABC``:

* Structural typing means an adapter satisfies a port by having the right
  methods, with no ``import`` and no inheritance.  The dependency really only
  points one way, and it stays that way even for third-party objects you do not
  control.
* Test doubles become ordinary classes.  There is no base class to inherit, no
  abstract method to stub out just to keep Python quiet.
* The cost is that mistakes surface in the type checker rather than at import
  time.  Run mypy or pyright in CI and that trade is a good one.

A note on granularity: ``NotificationPort`` deliberately exposes
``loan_confirmed`` and ``loan_returned`` instead of a generic ``send_email``.
Ports should speak the language of the application, not of the technology behind
them.  With this shape, swapping email for a push notification or a Kafka topic
is an adapter change; with ``send_email(subject, body)`` the templates would
already have leaked into the use cases.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, Sequence, runtime_checkable

from lending.domain.model import ISBN, Book, Loan, LoanId, Member, MemberId

__all__ = [
    "BookRepository",
    "Clock",
    "LoanRepository",
    "MemberRepository",
    "NotificationPort",
]


@runtime_checkable
class Clock(Protocol):
    """Today's date, as an injected dependency.

    Calling ``date.today()`` inside a use case would make "a loan is overdue
    after fourteen days" untestable without either sleeping or monkeypatching.
    A two-line port removes that problem permanently: tests inject a fixed date
    and assert on exact fees.
    """

    def today(self) -> date: ...


@runtime_checkable
class BookRepository(Protocol):
    """The catalogue. Keyed by ISBN, which is the domain's natural identifier."""

    def add(self, book: Book) -> None: ...

    def get(self, isbn: ISBN) -> Book | None:
        """Return the book or ``None``.

        Returning ``None`` rather than raising is intentional: "there is no such
        book" is a fact about storage, while "you cannot borrow a book we do not
        have" is a business decision.  The use case makes that decision, so the
        same repository can serve a caller that treats a miss as harmless.
        """
        ...

    def list_all(self) -> Sequence[Book]: ...


@runtime_checkable
class MemberRepository(Protocol):
    def add(self, member: Member) -> None: ...

    def get(self, member_id: MemberId) -> Member | None: ...


@runtime_checkable
class LoanRepository(Protocol):
    """Loans, plus the aggregate questions the lending policy needs answered.

    The counting methods are not incidental convenience.  The policy needs "how
    many loans does this member have open?" and a ``list_for_member`` followed by
    a Python-side filter would drag the whole table into memory to answer it.
    Pushing the question into the port lets the SQLite adapter answer it with
    ``SELECT COUNT(*)`` and the in-memory adapter answer it with a generator,
    each doing the sensible thing for its own storage.
    """

    def next_identity(self) -> LoanId:
        """Mint an id *before* persisting.

        This keeps identity generation out of the use case and lets the domain
        build a fully valid ``Loan`` in one step, instead of the half-built
        "saved but not yet identified" state that autoincrement columns impose.
        """
        ...

    def add(self, loan: Loan) -> None: ...

    def update(self, loan: Loan) -> None: ...

    def get(self, loan_id: LoanId) -> Loan | None: ...

    def count_open_for_member(self, member_id: MemberId) -> int: ...

    def count_open_for_isbn(self, isbn: ISBN) -> int: ...

    def count_overdue_for_member(self, member_id: MemberId, as_of: date) -> int: ...

    def has_open_loan(self, member_id: MemberId, isbn: ISBN) -> bool: ...

    def list_for_member(
        self, member_id: MemberId, *, include_returned: bool = False
    ) -> Sequence[Loan]: ...


@runtime_checkable
class NotificationPort(Protocol):
    """Telling a member something happened.

    Both methods take domain objects. The adapter decides what a "message" is:
    an SMTP body, a log line, a row in an outbox table.
    """

    def loan_confirmed(self, *, member: Member, book: Book, loan: Loan) -> None: ...

    def loan_returned(
        self, *, member: Member, book: Book, loan: Loan, late_fee: Decimal
    ) -> None: ...
