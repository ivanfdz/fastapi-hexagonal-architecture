"""Tests for the two read-only use cases."""

from __future__ import annotations

import pytest

from lending.application.dto import BorrowBookCommand, ListMemberLoansQuery, ReturnBookCommand
from lending.domain.errors import MemberNotFoundError
from tests.conftest import (
    ISBN_CLEAN_CODE,
    ISBN_DDD,
    MEMBER_ACTIVE,
    MEMBER_OTHER,
    Harness,
)


class TestListMemberLoans:
    def test_empty_for_a_member_with_no_loans(self, harness: Harness) -> None:
        assert harness.list_loans.execute(ListMemberLoansQuery(member_id=MEMBER_ACTIVE)) == ()

    def test_unknown_member_is_distinguished_from_no_loans(self, harness: Harness) -> None:
        # An empty list would be ambiguous, so the use case raises instead.
        with pytest.raises(MemberNotFoundError):
            harness.list_loans.execute(ListMemberLoansQuery(member_id="M-999"))

    def test_open_loans_only_by_default(self, harness: Harness) -> None:
        kept = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE)
        )
        given_back = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_DDD)
        )
        harness.give_back.execute(ReturnBookCommand(loan_id=given_back.loan_id))

        views = harness.list_loans.execute(ListMemberLoansQuery(member_id=MEMBER_ACTIVE))
        assert [view.loan_id for view in views] == [kept.loan_id]

    def test_include_returned_shows_the_full_history(self, harness: Harness) -> None:
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE))
        second = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_DDD)
        )
        harness.give_back.execute(ReturnBookCommand(loan_id=second.loan_id))

        views = harness.list_loans.execute(
            ListMemberLoansQuery(member_id=MEMBER_ACTIVE, include_returned=True)
        )
        assert len(views) == 2

    def test_does_not_leak_another_members_loans(self, harness: Harness) -> None:
        harness.borrow.execute(BorrowBookCommand(member_id=MEMBER_OTHER, isbn=ISBN_CLEAN_CODE))
        assert harness.list_loans.execute(ListMemberLoansQuery(member_id=MEMBER_ACTIVE)) == ()

    def test_newest_first(self, harness: Harness) -> None:
        first = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE)
        )
        harness.clock.advance(1)
        second = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_DDD)
        )

        views = harness.list_loans.execute(ListMemberLoansQuery(member_id=MEMBER_ACTIVE))
        assert [view.loan_id for view in views] == [second.loan_id, first.loan_id]


class TestListCatalogue:
    def test_lists_the_seeded_titles_alphabetically(self, harness: Harness) -> None:
        titles = [book.title for book in harness.catalogue.execute()]
        assert titles == [
            "Clean Code",
            "Design Patterns",
            "Domain-Driven Design",
            "Refactoring",
        ]

    def test_availability_starts_at_the_full_stock(self, harness: Harness) -> None:
        stock = {
            book.title: (book.total_copies, book.copies_available)
            for book in harness.catalogue.execute()
        }
        assert stock["Clean Code"] == (2, 2)
        assert stock["Refactoring"] == (3, 3)

    def test_availability_reflects_open_loans_only(self, harness: Harness) -> None:
        view = harness.borrow.execute(
            BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=ISBN_CLEAN_CODE)
        )
        on_loan = {b.title: b.copies_available for b in harness.catalogue.execute()}
        assert on_loan["Clean Code"] == 1

        harness.give_back.execute(ReturnBookCommand(loan_id=view.loan_id))
        returned = {b.title: b.copies_available for b in harness.catalogue.execute()}
        assert returned["Clean Code"] == 2
