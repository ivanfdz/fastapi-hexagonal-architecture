"""In-memory adapters for the three repository ports.

Dictionaries behind the same interfaces the SQLite adapter implements.  This is
not a toy: it is the adapter the HTTP tests run against, which is why the suite
finishes in well under a second with no container, no migration and no cleanup.

Because ``tests/infrastructure/test_repository_contract.py`` runs the identical
contract suite against this and the SQLite adapter, "passes in memory but breaks
in SQL" is caught by the test run rather than by staging.
"""

from __future__ import annotations

from datetime import date
from itertools import count
from typing import Iterator, Sequence

from lending.domain.model import ISBN, Book, Loan, LoanId, Member, MemberId

__all__ = ["InMemoryBookRepository", "InMemoryLoanRepository", "InMemoryMemberRepository"]


class InMemoryBookRepository:
    """Satisfies ``BookRepository``."""

    def __init__(self) -> None:
        self._books: dict[str, Book] = {}

    def add(self, book: Book) -> None:
        self._books[str(book.isbn)] = book

    def get(self, isbn: ISBN) -> Book | None:
        return self._books.get(str(isbn))

    def list_all(self) -> Sequence[Book]:
        return tuple(self._books.values())


class InMemoryMemberRepository:
    """Satisfies ``MemberRepository``."""

    def __init__(self) -> None:
        self._members: dict[str, Member] = {}

    def add(self, member: Member) -> None:
        self._members[str(member.member_id)] = member

    def get(self, member_id: MemberId) -> Member | None:
        return self._members.get(str(member_id))


class InMemoryLoanRepository:
    """Satisfies ``LoanRepository``.

    Identifiers are a readable sequence (``LOAN-0001``) because that makes demo
    output and failing assertions easy to follow.  The SQLite adapter mints UUID
    suffixes instead, and the contract test only requires that ids be unique and
    non-empty.  Identity generation is genuinely an infrastructure decision, and
    letting the two adapters differ here is the proof.
    """

    def __init__(self) -> None:
        self._loans: dict[str, Loan] = {}
        self._sequence: Iterator[int] = count(1)

    def next_identity(self) -> LoanId:
        return LoanId(f"LOAN-{next(self._sequence):04d}")

    def add(self, loan: Loan) -> None:
        if str(loan.loan_id) in self._loans:
            raise ValueError(f"loan {loan.loan_id} already stored")
        self._loans[str(loan.loan_id)] = loan

    def update(self, loan: Loan) -> None:
        if str(loan.loan_id) not in self._loans:
            raise ValueError(f"loan {loan.loan_id} is not stored")
        self._loans[str(loan.loan_id)] = loan

    def get(self, loan_id: LoanId) -> Loan | None:
        return self._loans.get(str(loan_id))

    def count_open_for_member(self, member_id: MemberId) -> int:
        return sum(
            1
            for loan in self._loans.values()
            if loan.member_id == member_id and loan.is_open
        )

    def count_open_for_isbn(self, isbn: ISBN) -> int:
        return sum(
            1 for loan in self._loans.values() if loan.isbn == isbn and loan.is_open
        )

    def count_overdue_for_member(self, member_id: MemberId, as_of: date) -> int:
        return sum(
            1
            for loan in self._loans.values()
            if loan.member_id == member_id and loan.is_overdue(as_of)
        )

    def has_open_loan(self, member_id: MemberId, isbn: ISBN) -> bool:
        return any(
            loan.member_id == member_id and loan.isbn == isbn and loan.is_open
            for loan in self._loans.values()
        )

    def list_for_member(
        self, member_id: MemberId, *, include_returned: bool = False
    ) -> Sequence[Loan]:
        return tuple(
            loan
            for loan in self._loans.values()
            if loan.member_id == member_id and (include_returned or loan.is_open)
        )
