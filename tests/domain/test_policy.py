"""Policy tests: the business rules, one assertion each.

Note that no repository appears anywhere in this file.  The policy takes counts
as integers, so testing "the fourth loan is refused" means passing ``3`` rather
than creating three loans in a database.  That is the payoff of keeping
cross-entity rules in an object that receives facts instead of fetching them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lending.domain.errors import (
    DuplicateLoanError,
    LoanLimitReachedError,
    MemberHasOverdueLoansError,
    MemberSuspendedError,
    NoCopiesAvailableError,
)
from lending.domain.model import ISBN, Book, Member, MemberId, MemberStatus
from lending.domain.policy import LoanPolicy

POLICY = LoanPolicy(
    loan_period_days=14, max_active_loans_per_member=3, late_fee_per_day=Decimal("0.50")
)
ACTIVE = Member(member_id=MemberId("M-001"), full_name="Ada", email="ada@example.com")
SUSPENDED = Member(
    member_id=MemberId("M-003"),
    full_name="Grace",
    email="grace@example.com",
    status=MemberStatus.SUSPENDED,
)
BOOK = Book(isbn=ISBN("9780132350884"), title="Clean Code", author="RCM", total_copies=2)


def check(**overrides: object) -> None:
    """Call the rule with everything permissive, then override one fact.

    Each test changes exactly one input, so a failure names the rule that broke
    rather than leaving you to diff six arguments.
    """
    kwargs: dict[str, object] = {
        "member": ACTIVE,
        "book": BOOK,
        "open_loans_by_member": 0,
        "overdue_loans_by_member": 0,
        "copies_on_loan": 0,
        "member_already_holds_title": False,
    }
    kwargs.update(overrides)
    POLICY.ensure_member_may_borrow(**kwargs)  # type: ignore[arg-type]


class TestBorrowingRules:
    def test_permits_a_clean_request(self) -> None:
        check()  # no exception is the assertion

    def test_refuses_a_suspended_member(self) -> None:
        with pytest.raises(MemberSuspendedError):
            check(member=SUSPENDED)

    def test_refuses_a_member_with_overdue_items(self) -> None:
        with pytest.raises(MemberHasOverdueLoansError):
            check(overdue_loans_by_member=1)

    def test_permits_the_last_loan_within_the_limit(self) -> None:
        check(open_loans_by_member=2)

    def test_refuses_the_loan_that_exceeds_the_limit(self) -> None:
        with pytest.raises(LoanLimitReachedError) as raised:
            check(open_loans_by_member=3)
        assert raised.value.details == {"member_id": "M-001", "open_loans": 3, "limit": 3}

    def test_refuses_a_second_copy_of_a_title_the_member_already_holds(self) -> None:
        with pytest.raises(DuplicateLoanError):
            check(member_already_holds_title=True)

    def test_permits_borrowing_while_one_of_two_copies_is_out(self) -> None:
        check(copies_on_loan=1)

    def test_refuses_when_every_copy_is_out(self) -> None:
        with pytest.raises(NoCopiesAvailableError) as raised:
            check(copies_on_loan=2)
        assert raised.value.details["copies_on_loan"] == 2

    def test_suspension_is_reported_before_availability(self) -> None:
        # Rule ordering is a product decision, so it gets a test: tell the member
        # why *they* cannot borrow before telling them the shelf is empty.
        with pytest.raises(MemberSuspendedError):
            check(member=SUSPENDED, copies_on_loan=2)


class TestFees:
    @pytest.mark.parametrize(
        ("days_overdue", "expected"),
        [(-3, "0.00"), (0, "0.00"), (1, "0.50"), (4, "2.00"), (30, "15.00")],
    )
    def test_fee_scales_with_lateness_and_is_never_negative(
        self, days_overdue: int, expected: str
    ) -> None:
        assert POLICY.late_fee_for(days_overdue) == Decimal(expected)

    def test_fee_is_quantized_to_cents(self) -> None:
        # 0.33 * 3 = 0.99 exactly; the point is that the result carries two
        # decimal places rather than trailing precision.
        policy = LoanPolicy(late_fee_per_day=Decimal("0.33"))
        assert str(policy.late_fee_for(3)) == "0.99"

    def test_fee_rounds_half_up(self) -> None:
        policy = LoanPolicy(late_fee_per_day=Decimal("0.125"))
        assert str(policy.late_fee_for(1)) == "0.13"


class TestConfiguration:
    def test_due_date_follows_the_configured_period(self) -> None:
        assert LoanPolicy(loan_period_days=7).due_date_for(date(2026, 3, 2)) == date(2026, 3, 9)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"loan_period_days": 0},
            {"max_active_loans_per_member": 0},
            {"late_fee_per_day": Decimal("-1")},
        ],
    )
    def test_rejects_nonsensical_configuration_at_construction(
        self, kwargs: dict[str, object]
    ) -> None:
        with pytest.raises(ValueError):
            LoanPolicy(**kwargs)  # type: ignore[arg-type]

    def test_describe_is_printable(self) -> None:
        assert POLICY.describe()["late_fee_per_day"] == "0.50"
