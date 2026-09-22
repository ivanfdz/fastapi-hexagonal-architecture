"""Lending policy: the rules that span more than one entity.

``Loan`` can answer "am I overdue?" by itself.  It cannot answer "may this
member take another book?", because that depends on every other loan the member
holds and on how many copies of the title are out.  Putting that question on the
entity would force the entity to reach for a repository, and an entity that
queries the database is an entity you can no longer test in isolation.

So the rules live here, in a small immutable object that receives *facts as
numbers* and either returns or raises.  The use case is responsible for
gathering those numbers through ports; the policy is responsible for judging
them.  That split is why every rule below is a two-line test with no fixtures.

The thresholds are constructor arguments rather than module constants because
they are configuration: ``lending.infrastructure.config`` reads them from the
environment and the composition root injects them.  The domain still owns the
*meaning* of each number, and the outside world only chooses its value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from lending.domain.errors import (
    DuplicateLoanError,
    LoanLimitReachedError,
    MemberHasOverdueLoansError,
    MemberSuspendedError,
    NoCopiesAvailableError,
)
from lending.domain.model import Book, Member

__all__ = ["LoanPolicy"]

DEFAULT_LOAN_PERIOD_DAYS: Final = 14
DEFAULT_MAX_ACTIVE_LOANS: Final = 3
DEFAULT_LATE_FEE_PER_DAY: Final = Decimal("0.50")

# Money is always a Decimal quantized to cents. Floats are banned from this
# module on purpose: 0.1 + 0.2 is not 0.3 and a library that overcharges by a
# thousandth of a cent per day is a bug report waiting to happen.
_CENTS: Final = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class LoanPolicy:
    """How long a loan lasts, how many a member may hold, what lateness costs."""

    loan_period_days: int = DEFAULT_LOAN_PERIOD_DAYS
    max_active_loans_per_member: int = DEFAULT_MAX_ACTIVE_LOANS
    late_fee_per_day: Decimal = DEFAULT_LATE_FEE_PER_DAY

    def __post_init__(self) -> None:
        if self.loan_period_days < 1:
            raise ValueError("loan_period_days must be at least 1")
        if self.max_active_loans_per_member < 1:
            raise ValueError("max_active_loans_per_member must be at least 1")
        if self.late_fee_per_day < 0:
            raise ValueError("late_fee_per_day cannot be negative")

    def ensure_member_may_borrow(
        self,
        *,
        member: Member,
        book: Book,
        open_loans_by_member: int,
        overdue_loans_by_member: int,
        copies_on_loan: int,
        member_already_holds_title: bool,
    ) -> None:
        """Raise the first rule this request breaks, or return silently.

        The order matters and is deliberate: it reports the reason a human would
        consider most fundamental first.  A suspended member is told they are
        suspended, not that the book is out of stock.
        """
        if not member.is_active:
            raise MemberSuspendedError(
                "Suspended members cannot borrow.",
                member_id=member.member_id,
                status=str(member.status),
            )
        if overdue_loans_by_member > 0:
            raise MemberHasOverdueLoansError(
                "Return the overdue items before borrowing again.",
                member_id=member.member_id,
                overdue_loans=overdue_loans_by_member,
            )
        if open_loans_by_member >= self.max_active_loans_per_member:
            raise LoanLimitReachedError(
                "This member already holds the maximum number of loans.",
                member_id=member.member_id,
                open_loans=open_loans_by_member,
                limit=self.max_active_loans_per_member,
            )
        if member_already_holds_title:
            raise DuplicateLoanError(
                "This member already has a copy of this title on loan.",
                member_id=member.member_id,
                isbn=str(book.isbn),
            )
        available = book.copies_available(copies_on_loan)
        if available < 1:
            raise NoCopiesAvailableError(
                "Every copy of this title is currently on loan.",
                isbn=str(book.isbn),
                total_copies=book.total_copies,
                copies_on_loan=copies_on_loan,
            )

    def due_date_for(self, borrowed_on: date) -> date:
        """Exposed for callers that need to preview a due date without a loan."""
        return borrowed_on + timedelta(days=self.loan_period_days)

    def late_fee_for(self, days_overdue: int) -> Decimal:
        """Fee owed for a given lateness, rounded to cents, never negative."""
        if days_overdue <= 0:
            return Decimal("0.00").quantize(_CENTS)
        return (self.late_fee_per_day * days_overdue).quantize(_CENTS, rounding=ROUND_HALF_UP)

    def describe(self) -> dict[str, str]:
        """A flat, printable summary. Handy for a ``GET /policy`` endpoint or a
        CLI ``--explain`` flag, and it keeps formatting decisions out of the
        adapters."""
        return {
            "loan_period_days": str(self.loan_period_days),
            "max_active_loans_per_member": str(self.max_active_loans_per_member),
            "late_fee_per_day": f"{self.late_fee_per_day.quantize(_CENTS)}",
        }
