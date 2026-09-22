"""Use case tests for borrowing.

These are the tests that would normally require a running database and a mocked
clock.  Here they need neither: the harness wires real in-memory repositories, a
recording notifier and a clock whose date is a constructor argument.

That combination is worth naming, because it is not the usual trade-off.  These
are not unit tests with mocks standing in for collaborators, and they are not
integration tests that need infrastructure.  They exercise the real use case
against real adapters, in memory, in milliseconds.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lending.application.dto import BorrowBookCommand, ReturnBookCommand
from lending.domain.errors import (
    BookNotFoundError,
    DuplicateLoanError,
    InvalidISBNError,
    LoanLimitReachedError,
    MemberHasOverdueLoansError,
    MemberNotFoundError,
    NoCopiesAvailableError,
)
from tests.conftest import (
    ISBN_CLEAN_CODE,
    ISBN_DDD,
    ISBN_NOT_CATALOGUED,
    ISBN_PATTERNS,
    ISBN_REFACTORING,
    MEMBER_ACTIVE,
    MEMBER_OTHER,
    MEMBER_SUSPENDED,
    TODAY,
    Harness,
)


class TestHappyPath:
    def test_returns_a_view_describing_the_new_loan(self, harness: Harness) -> None:
        view = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE)
        )

        assert view.member_id == MEMBER_ACTIVE
        assert view.title == "Clean Code"
        assert view.borrowed_on == TODAY
        assert view.due_on == date(2026, 3, 16)  # TODAY + 14 days
        assert view.returned_on is None
        assert view.is_open is True
        assert view.days_overdue == 0
        assert view.late_fee == Decimal("0.00")

    def test_normalises_the_isbn_on_the_way_through(self, harness: Harness) -> None:
        # Hyphens in, digits out: the value object canonicalises once and the
        # published contract is consistent regardless of how callers type it.
        view = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn="978-0-13-235088-4")
        )
        assert view.isbn == "9780132350884"

    def test_persists_the_loan_through_the_repository_port(self, harness: Harness) -> None:
        view = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE)
        )
        assert harness.loans.get(view.loan_id) is not None  # type: ignore[arg-type]

    def test_notifies_the_member_exactly_once(self, harness: Harness) -> None:
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))
        assert harness.notifier.kinds() == ["loan_confirmed"]
        assert harness.notifier.sent[0].member_id == MEMBER_ACTIVE

    def test_availability_drops_by_one(self, harness: Harness) -> None:
        before = {book.isbn: book.copies_available for book in harness.catalogue.execute()}
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))
        after = {book.isbn: book.copies_available for book in harness.catalogue.execute()}
        assert before["9780132350884"] - after["9780132350884"] == 1


class TestUnknownReferences:
    def test_unknown_member_is_a_domain_error(self, harness: Harness) -> None:
        with pytest.raises(MemberNotFoundError) as raised:
            harness.borrow.execute(BorrowBookCommand(member_id="M-999", isbn=ISBN_CLEAN_CODE))
        assert raised.value.details == {"member_id": "M-999"}

    def test_uncatalogued_title_is_a_domain_error(self, harness: Harness) -> None:
        with pytest.raises(BookNotFoundError):
            harness.borrow.execute(
                BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_NOT_CATALOGUED)
            )

    def test_malformed_isbn_fails_before_any_lookup(self, harness: Harness) -> None:
        # Parsing happens first, so a bad ISBN never reaches the repositories.
        with pytest.raises(InvalidISBNError):
            harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn="nope"))

    def test_nothing_is_persisted_or_sent_when_a_rule_refuses(self, harness: Harness) -> None:
        with pytest.raises(MemberNotFoundError):
            harness.borrow.execute(BorrowBookCommand(member_id="M-999", isbn=ISBN_CLEAN_CODE))
        assert harness.notifier.sent == []
        assert harness.loans.count_open_for_member("M-999") == 0  # type: ignore[arg-type]


class TestRulesEnforcedEndToEnd:
    """The rules are unit-tested in ``tests/domain/test_policy.py``.

    These tests check the wiring: that the use case gathers the right facts and
    asks the policy. A test that passes here but fails there means the rule is
    wrong; passing there and failing here means the use case asked the wrong
    question, which is the far more likely mistake.
    """

    def test_fourth_concurrent_loan_is_refused(self, harness: Harness) -> None:
        for isbn in (ISBN_CLEAN_CODE, ISBN_DDD, ISBN_REFACTORING):
            harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=isbn))

        with pytest.raises(LoanLimitReachedError):
            harness.borrow.execute(
                BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_PATTERNS)
            )

    def test_returning_frees_a_slot(self, harness: Harness) -> None:
        views = [
            harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=isbn))
            for isbn in (ISBN_CLEAN_CODE, ISBN_DDD, ISBN_REFACTORING)
        ]
        harness.give_back.execute(ReturnBookCommand(loan_id=views[0].loan_id))

        # Four loans created in total, three of them open at any one time.
        fourth = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_PATTERNS)
        )
        assert fourth.is_open is True

    def test_suspended_member_cannot_borrow(self, harness: Harness) -> None:
        from lending.domain.errors import MemberSuspendedError

        with pytest.raises(MemberSuspendedError):
            harness.borrow.execute(
                BorrowBookCommand(member_id=MEMBER_SUSPENDED, isbn=ISBN_CLEAN_CODE)
            )

    def test_same_title_twice_is_refused(self, harness: Harness) -> None:
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))
        with pytest.raises(DuplicateLoanError):
            harness.borrow.execute(
                BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE)
            )

    def test_last_copy_goes_to_whoever_asks_first(self, harness: Harness) -> None:
        # Domain-Driven Design has a single copy in the seed catalogue.
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_DDD))
        with pytest.raises(NoCopiesAvailableError) as raised:
            harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_OTHER, isbn=ISBN_DDD))
        assert raised.value.details == {
            "isbn": "9780321125217",
            "total_copies": 1,
            "copies_on_loan": 1,
        }

    def test_two_members_can_share_a_two_copy_title(self, harness: Harness) -> None:
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))
        second = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_OTHER, isbn=ISBN_CLEAN_CODE)
        )
        assert second.is_open is True

    def test_an_overdue_loan_blocks_further_borrowing(self, harness: Harness) -> None:
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))

        # Injected time, not elapsed time. No sleep, no patching.
        harness.clock.advance(20)

        with pytest.raises(MemberHasOverdueLoansError) as raised:
            harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_DDD))
        assert raised.value.details["overdue_loans"] == 1


class TestPolicyIsConfigurable:
    def test_a_different_term_produces_a_different_due_date(self, harness: Harness) -> None:
        """The thresholds are injected, so a library with different rules needs
        no code change -- only a different ``LoanPolicy`` in the composition
        root. Here the harness is rebuilt with a 7-day term."""
        from lending.application.use_cases import BorrowBook
        from lending.domain.policy import LoanPolicy

        weekly = LoanPolicy(loan_period_days=7, max_active_loans_per_member=1)
        borrow = BorrowBook(
            books=harness.books,
            members=harness.members,
            loans=harness.loans,
            notifications=harness.notifier,
            clock=harness.clock,
            policy=weekly,
        )

        view = borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))
        assert view.due_on == date(2026, 3, 9)

        with pytest.raises(LoanLimitReachedError):
            borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_DDD))
