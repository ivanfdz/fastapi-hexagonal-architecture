"""Use case tests for returning, including the fee arithmetic.

The overdue cases are the ones to look at.  "A book returned six days late costs
three euros" is normally an awkward thing to test -- you either wait six days or
patch ``date.today`` and hope the patch target never moves.  With the clock behind
a port it is two lines and an exact assertion.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lending.application.dto import BorrowBookCommand, ListMemberLoansQuery, ReturnBookCommand
from lending.domain.errors import LoanAlreadyReturnedError, LoanNotFoundError
from tests.conftest import ISBN_CLEAN_CODE, MEMBER_ACTIVE, TODAY, Harness


def borrow(harness: Harness, isbn: str = ISBN_CLEAN_CODE) -> str:
    return harness.borrow.execute(
        BorrowBookCommand(member_id=MEMBER_ACTIVE, isbn=isbn)
    ).loan_id


class TestOnTimeReturn:
    def test_closes_the_loan_with_no_fee(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.clock.advance(5)

        view = harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        assert view.is_open is False
        assert view.returned_on == date(2026, 3, 7)
        assert view.days_overdue == 0
        assert view.late_fee == Decimal("0.00")

    def test_returning_on_the_due_date_is_on_time(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.clock.advance(14)  # exactly the due date

        view = harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))
        assert view.days_overdue == 0
        assert view.late_fee == Decimal("0.00")

    def test_notifies_the_member(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        assert harness.notifier.kinds() == ["loan_confirmed", "loan_returned"]
        assert harness.notifier.sent[-1].late_fee == Decimal("0.00")

    def test_frees_the_copy(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        available = {book.isbn: book.copies_available for book in harness.catalogue.execute()}
        assert available["9780132350884"] == 2  # both copies back on the shelf


class TestLateReturn:
    @pytest.mark.parametrize(
        ("days_held", "expected_overdue", "expected_fee"),
        [
            (15, 1, "0.50"),
            (18, 4, "2.00"),
            (20, 6, "3.00"),
            (44, 30, "15.00"),
        ],
    )
    def test_fee_is_charged_per_day_past_the_due_date(
        self, harness: Harness, days_held: int, expected_overdue: int, expected_fee: str
    ) -> None:
        loan_id = borrow(harness)
        harness.clock.advance(days_held)

        view = harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        assert view.days_overdue == expected_overdue
        assert view.late_fee == Decimal(expected_fee)

    def test_the_fee_stops_accruing_once_returned(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.clock.advance(20)
        harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        # A year later, the same loan still owes exactly six days.
        harness.clock.advance(365)
        history = harness.list_loans.execute(
            ListMemberLoansQuery(member_id=MEMBER_ACTIVE, include_returned=True)
        )
        assert [(view.days_overdue, view.late_fee) for view in history] == [
            (6, Decimal("3.00"))
        ]

    def test_an_open_loan_accrues_while_it_stays_out(self, harness: Harness) -> None:
        borrow(harness)
        harness.clock.advance(18)

        open_loans = harness.list_loans.execute(ListMemberLoansQuery(member_id=MEMBER_ACTIVE))
        assert open_loans[0].late_fee == Decimal("2.00")
        assert open_loans[0].is_open is True


class TestRefusals:
    def test_unknown_loan(self, harness: Harness) -> None:
        with pytest.raises(LoanNotFoundError) as raised:
            harness.give_back.execute(ReturnBookCommand(loan_id="LOAN-9999"))
        assert raised.value.details == {"loan_id": "LOAN-9999"}

    def test_returning_twice_is_refused(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        with pytest.raises(LoanAlreadyReturnedError):
            harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

    def test_the_second_return_sends_no_notification(self, harness: Harness) -> None:
        loan_id = borrow(harness)
        harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))
        before = len(harness.notifier.sent)

        with pytest.raises(LoanAlreadyReturnedError):
            harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))

        # The entity guards the transition, so the side effects never run.
        assert len(harness.notifier.sent) == before


class TestProjection:
    def test_the_view_carries_the_title_joined_from_the_catalogue(
        self, harness: Harness
    ) -> None:
        loan_id = borrow(harness)
        view = harness.give_back.execute(ReturnBookCommand(loan_id=loan_id))
        assert view.title == "Clean Code"
        assert view.borrowed_on == TODAY
