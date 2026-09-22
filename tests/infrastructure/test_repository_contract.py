"""One contract suite, run against every repository adapter.

This is the technique that makes swappable adapters trustworthy rather than
aspirational.  The tests are written entirely in terms of the *ports*, and
``pytest`` parametrises the fixture over each implementation, so the identical
assertions run against dictionaries and against SQL.

What it catches, in practice:

* A ``count_overdue_for_member`` that treats the due date as inclusive in Python
  and exclusive in SQL.
* ``list_for_member`` returning returned loans in one adapter and not the other.
* Date round-tripping bugs -- a ``date`` that comes back as a string.
* ``update`` silently doing nothing when the row is absent.

Adding a Postgres adapter means adding one entry to ``params`` below.  If it
passes, it is a drop-in replacement, and that is a much stronger statement than
"it implements the protocol".
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

import pytest

from lending.application.ports.driven import BookRepository, LoanRepository, MemberRepository
from lending.domain.model import ISBN, Book, Loan, LoanId, Member, MemberId, MemberStatus
from lending.infrastructure.driven.memory import (
    InMemoryBookRepository,
    InMemoryLoanRepository,
    InMemoryMemberRepository,
)
from lending.infrastructure.driven.sqlite import (
    SQLiteBookRepository,
    SQLiteLoanRepository,
    SQLiteMemberRepository,
    connect,
    create_schema,
)

BORROWED_ON = date(2026, 3, 2)
DUE_ON = date(2026, 3, 16)
BOOK = Book(isbn=ISBN("9780132350884"), title="Clean Code", author="RCM", total_copies=2)
OTHER_BOOK = Book(isbn=ISBN("9780321125217"), title="DDD", author="Evans", total_copies=1)
MEMBER = Member(member_id=MemberId("M-001"), full_name="Ada", email="ada@example.com")
OTHER_MEMBER = Member(member_id=MemberId("M-002"), full_name="Alan", email="alan@example.com")


@dataclass
class Repositories:
    books: BookRepository
    members: MemberRepository
    loans: LoanRepository


def _memory(_: Path) -> tuple[Repositories, Callable[[], None]]:
    return (
        Repositories(
            books=InMemoryBookRepository(),
            members=InMemoryMemberRepository(),
            loans=InMemoryLoanRepository(),
        ),
        lambda: None,
    )


def _sqlite(tmp_path: Path) -> tuple[Repositories, Callable[[], None]]:
    connection: sqlite3.Connection = connect(tmp_path / "contract.db")
    create_schema(connection)
    lock = threading.Lock()
    return (
        Repositories(
            books=SQLiteBookRepository(connection, lock),
            members=SQLiteMemberRepository(connection, lock),
            loans=SQLiteLoanRepository(connection, lock),
        ),
        connection.close,
    )


@pytest.fixture(params=[_memory, _sqlite], ids=["memory", "sqlite"])
def repositories(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Repositories]:
    """Every test in this module runs twice, once per adapter."""
    build = request.param
    repos, close = build(tmp_path)
    # The SQLite schema declares foreign keys, so books and members must exist
    # before loans reference them. Seeding here keeps each test focused.
    repos.books.add(BOOK)
    repos.books.add(OTHER_BOOK)
    repos.members.add(MEMBER)
    repos.members.add(OTHER_MEMBER)
    try:
        yield repos
    finally:
        close()


def make_loan(
    repositories: Repositories,
    *,
    member: Member = MEMBER,
    book: Book = BOOK,
    borrowed_on: date = BORROWED_ON,
    returned_on: date | None = None,
) -> Loan:
    loan = Loan(
        loan_id=repositories.loans.next_identity(),
        isbn=book.isbn,
        member_id=member.member_id,
        borrowed_on=borrowed_on,
        due_on=DUE_ON,
        returned_on=returned_on,
    )
    repositories.loans.add(loan)
    return loan


class TestBookRepository:
    def test_round_trips_a_book(self, repositories: Repositories) -> None:
        found = repositories.books.get(ISBN("9780132350884"))
        assert found == BOOK

    def test_lookup_accepts_the_hyphenated_form(self, repositories: Repositories) -> None:
        # Normalisation lives in the value object, so every adapter inherits it.
        assert repositories.books.get(ISBN("978-0-13-235088-4")) == BOOK

    def test_returns_none_for_an_unknown_isbn(self, repositories: Repositories) -> None:
        assert repositories.books.get(ISBN("9781593275846")) is None

    def test_lists_everything_added(self, repositories: Repositories) -> None:
        assert {str(book.isbn) for book in repositories.books.list_all()} == {
            "9780132350884",
            "9780321125217",
        }

    def test_adding_the_same_isbn_twice_updates_rather_than_duplicates(
        self, repositories: Repositories
    ) -> None:
        repositories.books.add(
            Book(isbn=BOOK.isbn, title="Clean Code", author="RCM", total_copies=5)
        )
        found = repositories.books.get(BOOK.isbn)
        assert found is not None and found.total_copies == 5
        assert len(repositories.books.list_all()) == 2


class TestMemberRepository:
    def test_round_trips_a_member(self, repositories: Repositories) -> None:
        assert repositories.members.get(MemberId("M-001")) == MEMBER

    def test_preserves_status(self, repositories: Repositories) -> None:
        suspended = Member(
            member_id=MemberId("M-003"),
            full_name="Grace",
            email="grace@example.com",
            status=MemberStatus.SUSPENDED,
        )
        repositories.members.add(suspended)
        found = repositories.members.get(MemberId("M-003"))
        assert found is not None and found.status is MemberStatus.SUSPENDED

    def test_returns_none_for_an_unknown_member(self, repositories: Repositories) -> None:
        assert repositories.members.get(MemberId("M-999")) is None


class TestLoanIdentity:
    def test_identifiers_are_non_empty_and_unique(self, repositories: Repositories) -> None:
        # The contract is uniqueness, not a format. The in-memory adapter counts
        # and the SQLite adapter uses a UUID suffix; both are valid.
        minted = {repositories.loans.next_identity() for _ in range(50)}
        assert len(minted) == 50
        assert all(identifier for identifier in minted)


class TestLoanPersistence:
    def test_round_trips_an_open_loan_with_real_dates(
        self, repositories: Repositories
    ) -> None:
        loan = make_loan(repositories)
        found = repositories.loans.get(loan.loan_id)

        assert found is not None
        # Dates come back as dates, not ISO strings. The SQLite adapter stores
        # TEXT, and this assertion is what stops that detail from escaping.
        assert found.borrowed_on == BORROWED_ON
        assert found.due_on == DUE_ON
        assert found.returned_on is None
        assert found.isbn == BOOK.isbn

    def test_round_trips_a_returned_loan(self, repositories: Repositories) -> None:
        loan = make_loan(repositories, returned_on=date(2026, 3, 10))
        found = repositories.loans.get(loan.loan_id)
        assert found is not None and found.returned_on == date(2026, 3, 10)

    def test_returns_none_for_an_unknown_loan(self, repositories: Repositories) -> None:
        assert repositories.loans.get(LoanId("LOAN-nope")) is None

    def test_update_persists_the_state_transition(self, repositories: Repositories) -> None:
        loan = make_loan(repositories)
        loan.close(date(2026, 3, 20))
        repositories.loans.update(loan)

        found = repositories.loans.get(loan.loan_id)
        assert found is not None
        assert found.is_open is False
        assert found.returned_on == date(2026, 3, 20)

    def test_update_of_an_unstored_loan_is_an_error(
        self, repositories: Repositories
    ) -> None:
        # Both adapters must refuse, rather than one silently writing nothing.
        stray = Loan(
            loan_id=LoanId("LOAN-absent"),
            isbn=BOOK.isbn,
            member_id=MEMBER.member_id,
            borrowed_on=BORROWED_ON,
            due_on=DUE_ON,
        )
        with pytest.raises(ValueError):
            repositories.loans.update(stray)


class TestLoanCounting:
    def test_counts_open_loans_per_member(self, repositories: Repositories) -> None:
        make_loan(repositories, book=BOOK)
        make_loan(repositories, book=OTHER_BOOK)
        make_loan(repositories, member=OTHER_MEMBER, book=BOOK)

        assert repositories.loans.count_open_for_member(MEMBER.member_id) == 2
        assert repositories.loans.count_open_for_member(OTHER_MEMBER.member_id) == 1

    def test_returned_loans_are_not_open(self, repositories: Repositories) -> None:
        loan = make_loan(repositories)
        loan.close(date(2026, 3, 10))
        repositories.loans.update(loan)
        assert repositories.loans.count_open_for_member(MEMBER.member_id) == 0

    def test_counts_open_loans_per_title(self, repositories: Repositories) -> None:
        make_loan(repositories, book=BOOK)
        make_loan(repositories, member=OTHER_MEMBER, book=BOOK)
        assert repositories.loans.count_open_for_isbn(BOOK.isbn) == 2
        assert repositories.loans.count_open_for_isbn(OTHER_BOOK.isbn) == 0

    @pytest.mark.parametrize(
        ("as_of", "expected"),
        [
            (date(2026, 3, 15), 0),  # before the due date
            (date(2026, 3, 16), 0),  # on the due date: still on time
            (date(2026, 3, 17), 1),  # the day after: overdue
        ],
    )
    def test_overdue_counting_agrees_on_the_boundary(
        self, repositories: Repositories, as_of: date, expected: int
    ) -> None:
        # The boundary is the whole reason this test exists. ``Loan.is_overdue``
        # uses ``as_of > due_on`` and the SQL uses ``due_on < ?``; they have to
        # mean the same thing, and only a shared test proves it.
        make_loan(repositories)
        assert repositories.loans.count_overdue_for_member(MEMBER.member_id, as_of) == expected

    def test_a_returned_loan_is_never_overdue(self, repositories: Repositories) -> None:
        loan = make_loan(repositories)
        loan.close(date(2026, 3, 30))
        repositories.loans.update(loan)
        assert (
            repositories.loans.count_overdue_for_member(
                MEMBER.member_id, date(2026, 4, 30)
            )
            == 0
        )

    def test_has_open_loan_is_scoped_to_member_and_title(
        self, repositories: Repositories
    ) -> None:
        make_loan(repositories, book=BOOK)
        assert repositories.loans.has_open_loan(MEMBER.member_id, BOOK.isbn) is True
        assert repositories.loans.has_open_loan(MEMBER.member_id, OTHER_BOOK.isbn) is False
        assert repositories.loans.has_open_loan(OTHER_MEMBER.member_id, BOOK.isbn) is False

    def test_has_open_loan_is_false_after_the_return(
        self, repositories: Repositories
    ) -> None:
        loan = make_loan(repositories)
        loan.close(date(2026, 3, 10))
        repositories.loans.update(loan)
        assert repositories.loans.has_open_loan(MEMBER.member_id, BOOK.isbn) is False


class TestLoanListing:
    def test_open_loans_only_by_default(self, repositories: Repositories) -> None:
        kept = make_loan(repositories, book=BOOK)
        closed = make_loan(repositories, book=OTHER_BOOK)
        closed.close(date(2026, 3, 10))
        repositories.loans.update(closed)

        listed = repositories.loans.list_for_member(MEMBER.member_id)
        assert [loan.loan_id for loan in listed] == [kept.loan_id]

    def test_include_returned_shows_both(self, repositories: Repositories) -> None:
        make_loan(repositories, book=BOOK)
        closed = make_loan(repositories, book=OTHER_BOOK)
        closed.close(date(2026, 3, 10))
        repositories.loans.update(closed)

        listed = repositories.loans.list_for_member(
            MEMBER.member_id, include_returned=True
        )
        assert len(listed) == 2

    def test_never_leaks_another_members_loans(self, repositories: Repositories) -> None:
        make_loan(repositories, member=OTHER_MEMBER)
        assert repositories.loans.list_for_member(MEMBER.member_id) == ()
