"""The demonstration: one use case, three different sets of adapters.

    python examples/swap_adapters.py

The script runs the same borrow-and-return story three times:

1. in-memory repositories, printing notifier, today's date
2. SQLite repositories on a temporary file, same printing notifier
3. in-memory repositories, a notifier that records instead of printing, and a
   clock frozen twenty days in the past -- which makes the return arrive late and
   produces a fee

The output differs only in the loan ids and the dates.  The interesting part is
what is *not* in this file: no ``if backend == "sqlite"`` inside the use case, no
SQL, no date patching, no mocks.  ``BorrowBook`` is constructed with different
collaborators and behaves identically, because it only ever knew about ports.

The third run is the one to sit with.  Testing "a fee applies after the due date"
normally means either waiting, or monkeypatching ``date.today``, or both.  Here
it is a constructor argument.
"""

from __future__ import annotations

import sys
import tempfile
import threading
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# Make the script runnable straight from a clone, with or without an install.
# Fine for an example; application code should never manipulate sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lending.application.dto import BorrowBookCommand, ReturnBookCommand  # noqa: E402
from lending.application.ports.driven import (  # noqa: E402
    BookRepository,
    Clock,
    LoanRepository,
    MemberRepository,
    NotificationPort,
)
from lending.application.use_cases import BorrowBook, ReturnBook  # noqa: E402
from lending.domain.model import Book, Loan, Member  # noqa: E402
from lending.domain.policy import LoanPolicy  # noqa: E402
from lending.infrastructure.driven.clock import FrozenClock, SystemClock  # noqa: E402
from lending.infrastructure.driven.memory import (  # noqa: E402
    InMemoryBookRepository,
    InMemoryLoanRepository,
    InMemoryMemberRepository,
)
from lending.infrastructure.driven.notifications import ConsoleNotifier  # noqa: E402
from lending.infrastructure.driven.sqlite import (  # noqa: E402
    SQLiteBookRepository,
    SQLiteLoanRepository,
    SQLiteMemberRepository,
    connect,
    create_schema,
)
from lending.infrastructure.seed import seed  # noqa: E402

POLICY = LoanPolicy(loan_period_days=14, max_active_loans_per_member=3,
                    late_fee_per_day=Decimal("0.50"))
ISBN_CLEAN_CODE = "978-0-13-235088-4"


class RecordingNotifier:
    """Satisfies ``NotificationPort`` by collecting what it was told.

    Three methods, no base class, no import from the ports module. That is
    structural typing doing its job: this class is a valid adapter because its
    shape matches, and the use case cannot tell the difference.
    """

    def __init__(self) -> None:
        self.events: list[str] = []

    def loan_confirmed(self, *, member: Member, book: Book, loan: Loan) -> None:
        self.events.append(f"confirmed {loan.loan_id} for {member.member_id}")

    def loan_returned(
        self, *, member: Member, book: Book, loan: Loan, late_fee: Decimal
    ) -> None:
        self.events.append(f"returned {loan.loan_id} with fee {late_fee}")


def run_story(
    *,
    label: str,
    books: BookRepository,
    members: MemberRepository,
    loans: LoanRepository,
    notifications: NotificationPort,
    clock: Clock,
) -> None:
    """Borrow a book, then return it. Identical code for every wiring."""
    print(f"\n=== {label} ===")
    seed(books=books, members=members)

    borrow = BorrowBook(
        books=books,
        members=members,
        loans=loans,
        notifications=notifications,
        clock=clock,
        policy=POLICY,
    )
    give_back = ReturnBook(
        books=books,
        members=members,
        loans=loans,
        notifications=notifications,
        clock=clock,
        policy=POLICY,
    )

    borrowed = borrow.execute(BorrowBookCommand(member_id="M-001", isbn=ISBN_CLEAN_CODE))
    print(
        f"borrowed   {borrowed.loan_id}  {borrowed.title!r}  "
        f"on {borrowed.borrowed_on}  due {borrowed.due_on}"
    )

    returned = give_back.execute(ReturnBookCommand(loan_id=borrowed.loan_id))
    print(
        f"returned   {returned.loan_id}  on {returned.returned_on}  "
        f"{returned.days_overdue} day(s) late  fee {returned.late_fee}"
    )


def with_memory() -> None:
    run_story(
        label="1. in-memory repositories, system clock",
        books=InMemoryBookRepository(),
        members=InMemoryMemberRepository(),
        loans=InMemoryLoanRepository(),
        notifications=ConsoleNotifier(),
        clock=SystemClock(),
    )


def with_sqlite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        connection = connect(Path(directory) / "demo.db")
        create_schema(connection)
        # One lock shared by the three repositories, as they share a connection.
        lock = threading.Lock()
        try:
            run_story(
                label="2. SQLite repositories, system clock",
                books=SQLiteBookRepository(connection, lock),
                members=SQLiteMemberRepository(connection, lock),
                loans=SQLiteLoanRepository(connection, lock),
                notifications=ConsoleNotifier(),
                clock=SystemClock(),
            )
        finally:
            connection.close()


def with_frozen_clock() -> None:
    """The overdue path, produced by injection rather than by waiting."""
    borrowed_on = date.today() - timedelta(days=20)
    clock = FrozenClock(borrowed_on)
    notifier = RecordingNotifier()

    books = InMemoryBookRepository()
    members = InMemoryMemberRepository()
    loans = InMemoryLoanRepository()
    seed(books=books, members=members)

    borrow = BorrowBook(
        books=books, members=members, loans=loans,
        notifications=notifier, clock=clock, policy=POLICY,
    )
    give_back = ReturnBook(
        books=books, members=members, loans=loans,
        notifications=notifier, clock=clock, policy=POLICY,
    )

    print("\n=== 3. in-memory repositories, clock frozen 20 days ago ===")
    borrowed = borrow.execute(BorrowBookCommand(member_id="M-001", isbn=ISBN_CLEAN_CODE))
    print(f"borrowed   {borrowed.loan_id}  on {borrowed.borrowed_on}  due {borrowed.due_on}")

    # Move the clock forward past the due date. Six days late at 0.50/day = 3.00.
    clock.set(date.today())
    returned = give_back.execute(ReturnBookCommand(loan_id=borrowed.loan_id))
    print(
        f"returned   {returned.loan_id}  on {returned.returned_on}  "
        f"{returned.days_overdue} day(s) late  fee {returned.late_fee}"
    )
    print("notifier recorded:")
    for event in notifier.events:
        print(f"  - {event}")


def main() -> None:
    with_memory()
    with_sqlite()
    with_frozen_clock()
    print(
        "\nSame BorrowBook and ReturnBook classes in all three runs. "
        "Only the adapters changed."
    )


if __name__ == "__main__":
    main()
