"""Shared fixtures.

The shape of this file is itself an argument for the architecture. Assembling a
fully functional lending application takes eight lines and no I/O, so the
"integration" tests in ``tests/application`` run as fast as unit tests while
exercising real repository implementations rather than mocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from lending.application.use_cases import (
    BorrowBook,
    ListCatalogue,
    ListMemberLoans,
    ReturnBook,
)
from lending.domain.policy import LoanPolicy
from lending.infrastructure.driven.memory import (
    InMemoryBookRepository,
    InMemoryLoanRepository,
    InMemoryMemberRepository,
)
from lending.infrastructure.seed import seed
from tests.fakes import FixedClock, RecordingNotifier

# A Monday, chosen so date arithmetic in the assertions is easy to follow.
TODAY = date(2026, 3, 2)
ISBN_CLEAN_CODE = "978-0-13-235088-4"       # 2 copies in the demo catalogue
ISBN_DDD = "978-0-321-12521-7"              # 1 copy
ISBN_REFACTORING = "978-0-13-475759-9"      # 3 copies
ISBN_PATTERNS = "978-0-201-63361-0"         # 1 copy
ISBN_NOT_CATALOGUED = "978-1-59327-584-6"   # valid ISBN-13, absent from the seed

MEMBER_ACTIVE = "M-001"
MEMBER_OTHER = "M-002"
MEMBER_SUSPENDED = "M-003"


@dataclass
class Harness:
    """Everything a use case test needs, wired together and inspectable."""

    policy: LoanPolicy
    clock: FixedClock
    notifier: RecordingNotifier
    books: InMemoryBookRepository
    members: InMemoryMemberRepository
    loans: InMemoryLoanRepository
    borrow: BorrowBook
    give_back: ReturnBook
    list_loans: ListMemberLoans
    catalogue: ListCatalogue


@pytest.fixture
def policy() -> LoanPolicy:
    return LoanPolicy(
        loan_period_days=14,
        max_active_loans_per_member=3,
        late_fee_per_day=Decimal("0.50"),
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(TODAY)


@pytest.fixture
def harness(policy: LoanPolicy, clock: FixedClock) -> Harness:
    books = InMemoryBookRepository()
    members = InMemoryMemberRepository()
    loans = InMemoryLoanRepository()
    notifier = RecordingNotifier()
    seed(books=books, members=members)

    return Harness(
        policy=policy,
        clock=clock,
        notifier=notifier,
        books=books,
        members=members,
        loans=loans,
        borrow=BorrowBook(
            books=books, members=members, loans=loans,
            notifications=notifier, clock=clock, policy=policy,
        ),
        give_back=ReturnBook(
            books=books, members=members, loans=loans,
            notifications=notifier, clock=clock, policy=policy,
        ),
        list_loans=ListMemberLoans(
            books=books, members=members, loans=loans, clock=clock, policy=policy,
        ),
        catalogue=ListCatalogue(books=books, loans=loans),
    )
