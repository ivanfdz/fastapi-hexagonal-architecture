"""The domain model: entities and value objects at the centre of the hexagon.

Read the import block below before anything else.  It is the whole point of the
exercise: ``dataclasses``, ``datetime``, ``decimal``, ``enum``, ``typing``.  No
FastAPI, no Pydantic, no SQL driver, no HTTP client, no logger configuration.
This module can be imported, exercised and reasoned about with nothing
installed, which is exactly why the business rules are cheap to test and
survive a change of framework.

Two kinds of object live here:

* **Value objects** (``ISBN``) have no identity, are immutable and are equal
  when their contents are equal.  They are the natural home for format rules,
  so an invalid ISBN is unrepresentable rather than merely undesirable.
* **Entities** (``Book``, ``Member``, ``Loan``) have identity and a lifecycle.
  ``Loan`` is the interesting one: it owns the rules that depend only on a
  single loan (is it overdue, how late was it returned, may it be closed).
  Rules that need to look across several loans live in ``policy.py`` instead,
  because an entity should not have to know how to query its own siblings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Final, NewType, Self

from lending.domain.errors import InvalidISBNError, LoanAlreadyReturnedError

__all__ = ["ISBN", "Book", "Loan", "LoanId", "Member", "MemberId", "MemberStatus"]


# ``NewType`` gives identifiers a distinct static type at zero runtime cost, so
# passing a member id where a loan id is expected is a type error rather than a
# mystery 404 in production.
MemberId = NewType("MemberId", str)
LoanId = NewType("LoanId", str)

_ISBN13_LENGTH: Final = 13
_ISBN_SEPARATORS: Final = str.maketrans({"-": None, " ": None})
# Real ISBN-13s are GS1 product codes under the 978 or 979 prefix. Checking the
# prefix as well as the check digit is what stops degenerate strings such as
# "0000000000000" -- which happens to have a valid checksum -- from being
# accepted. The rule is small, but it belongs here rather than in a request
# schema: otherwise every adapter has to remember it.
_ISBN13_PREFIXES: Final = ("978", "979")


def _isbn13_checksum(digits: str) -> int:
    """Weighted sum of an ISBN-13, which is valid when divisible by ten."""
    return sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(digits)) % 10


@dataclass(frozen=True, slots=True, order=True)
class ISBN:
    """A validated, normalised ISBN-13.

    Construction accepts the hyphenated form humans type and stores the
    thirteen digits, so ``ISBN("978-0-13-235088-4") == ISBN("9780132350884")``.
    Because the type is frozen, normalisation goes through
    ``object.__setattr__``; that is the standard escape hatch for a frozen
    dataclass that canonicalises its own input.
    """

    value: str

    def __post_init__(self) -> None:
        digits = self.value.strip().translate(_ISBN_SEPARATORS)
        if len(digits) != _ISBN13_LENGTH or not digits.isdigit():
            raise InvalidISBNError(
                "An ISBN-13 must contain exactly 13 digits, optionally separated by hyphens.",
                isbn=self.value,
            )
        if not digits.startswith(_ISBN13_PREFIXES):
            raise InvalidISBNError(
                "An ISBN-13 must start with the 978 or 979 prefix.",
                isbn=self.value,
            )
        if _isbn13_checksum(digits) != 0:
            raise InvalidISBNError(
                "ISBN-13 check digit does not match the rest of the number.",
                isbn=self.value,
            )
        object.__setattr__(self, "value", digits)

    def __str__(self) -> str:
        return self.value


class MemberStatus(StrEnum):
    """Whether a member is allowed to take new loans at all."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class Member:
    """A library member. Immutable here because nothing in these use cases
    changes a member; add an ``update`` path and this would grow behaviour."""

    member_id: MemberId
    full_name: str
    email: str
    status: MemberStatus = MemberStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.member_id.strip():
            raise ValueError("member_id must not be blank")
        if not self.full_name.strip():
            raise ValueError("full_name must not be blank")
        if "@" not in self.email:
            raise ValueError(f"{self.email!r} is not a usable email address")

    @property
    def is_active(self) -> bool:
        return self.status is MemberStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class Book:
    """A title in the catalogue, identified by its ISBN.

    ``total_copies`` is how many physical copies the library owns.  How many are
    *available* depends on the loans currently open, which this object cannot
    know on its own -- hence a method that takes that number as an argument
    rather than a property that would need a database.
    """

    isbn: ISBN
    title: str
    author: str
    total_copies: int

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if self.total_copies < 1:
            raise ValueError("a catalogued book must have at least one copy")

    def copies_available(self, copies_on_loan: int) -> int:
        if copies_on_loan < 0:
            raise ValueError("copies_on_loan cannot be negative")
        return max(self.total_copies - copies_on_loan, 0)


@dataclass(slots=True)
class Loan:
    """One copy of one title, in the hands of one member, until returned.

    This is the only mutable entity in the model: closing a loan is a state
    transition on an existing thing, not the creation of a new thing, and
    modelling it as mutation keeps the invariant ("a loan can only be closed
    once") in one obvious place.
    """

    loan_id: LoanId
    isbn: ISBN
    member_id: MemberId
    borrowed_on: date
    due_on: date
    returned_on: date | None = None

    def __post_init__(self) -> None:
        if self.due_on < self.borrowed_on:
            raise ValueError("due_on cannot precede borrowed_on")
        if self.returned_on is not None and self.returned_on < self.borrowed_on:
            raise ValueError("returned_on cannot precede borrowed_on")

    @classmethod
    def open(
        cls,
        *,
        loan_id: LoanId,
        isbn: ISBN,
        member_id: MemberId,
        borrowed_on: date,
        loan_period_days: int,
    ) -> Self:
        """Named constructor: the only blessed way to start a loan.

        Callers hand over a period and get a due date; they never compute
        ``due_on`` themselves, so the lending term cannot drift between the HTTP
        adapter, a CLI adapter and a nightly batch job.
        """
        if loan_period_days < 1:
            raise ValueError("loan_period_days must be at least 1")
        return cls(
            loan_id=loan_id,
            isbn=isbn,
            member_id=member_id,
            borrowed_on=borrowed_on,
            due_on=borrowed_on + timedelta(days=loan_period_days),
        )

    @property
    def is_open(self) -> bool:
        return self.returned_on is None

    @property
    def is_returned(self) -> bool:
        return self.returned_on is not None

    def is_overdue(self, as_of: date) -> bool:
        """True only for loans still out past their due date."""
        return self.is_open and as_of > self.due_on

    def days_overdue(self, as_of: date) -> int:
        """Lateness in whole days: accruing while open, frozen once returned."""
        reference = self.returned_on or as_of
        return max((reference - self.due_on).days, 0)

    def close(self, returned_on: date) -> int:
        """Return the copy and report how many days late it was.

        Raises ``LoanAlreadyReturnedError`` on a second attempt.  The guard
        lives here rather than in the use case so that *every* caller inherits
        it, including future ones nobody has written yet.
        """
        if self.is_returned:
            raise LoanAlreadyReturnedError(
                "This loan was already returned.",
                loan_id=self.loan_id,
                returned_on=self.returned_on.isoformat() if self.returned_on else None,
            )
        if returned_on < self.borrowed_on:
            raise ValueError("a copy cannot be returned before it was borrowed")
        self.returned_on = returned_on
        return self.days_overdue(returned_on)
