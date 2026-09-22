"""The composition root: the one place that knows every concrete type.

If you want to understand what this codebase actually runs, read this file.  It
is the only module that imports both an adapter and a use case, and therefore the
only module that has to change when you swap a dependency.  Everywhere else,
collaborators arrive as constructor arguments.

Two properties are worth stating explicitly, because they are what "hexagonal"
buys you and they are both verifiable from here:

* **Switching persistence is a branch in one function.**  ``_build_repositories``
  returns in-memory or SQLite repositories depending on a setting.  No use case,
  no entity and no route handler is aware of the choice.
* **Nothing imports this file except the entry points.**  ``http.app`` builds a
  container during startup; ``examples/swap_adapters.py`` builds two of them by
  hand.  The dependency arrow points from the outside in, always.

This is hand-rolled dependency injection: explicit constructor calls, no
container library, no decorators, no runtime graph resolution.  For a system of
this size that is a feature -- the wiring is a function you can read top to
bottom and step through in a debugger.  Reach for a DI framework when the graph
genuinely outgrows a screen, not before.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable

from lending.application.ports.driven import (
    BookRepository,
    Clock,
    LoanRepository,
    MemberRepository,
    NotificationPort,
)
from lending.application.use_cases import BorrowBook, ListCatalogue, ListMemberLoans, ReturnBook
from lending.domain.policy import LoanPolicy
from lending.infrastructure.config import Settings
from lending.infrastructure.driven.clock import UTCClock
from lending.infrastructure.driven.memory import (
    InMemoryBookRepository,
    InMemoryLoanRepository,
    InMemoryMemberRepository,
)
from lending.infrastructure.driven.notifications import (
    ConsoleNotifier,
    LoggingNotifier,
    NullNotifier,
)
from lending.infrastructure.driven.sqlite import (
    SQLiteBookRepository,
    SQLiteLoanRepository,
    SQLiteMemberRepository,
    connect,
    create_schema,
)
from lending.infrastructure.seed import seed

__all__ = ["Container", "build_container"]


@dataclass(frozen=True, slots=True)
class Container:
    """The assembled application, exposed as four use cases.

    Adapters are kept as fields too, which is a small pragmatic concession: the
    seeding step and the tests occasionally need to reach a repository directly.
    Route handlers should not -- they depend on the driving ports only.
    """

    settings: Settings
    policy: LoanPolicy
    clock: Clock
    books: BookRepository
    members: MemberRepository
    loans: LoanRepository
    notifications: NotificationPort
    borrow_book: BorrowBook
    return_book: ReturnBook
    list_member_loans: ListMemberLoans
    list_catalogue: ListCatalogue
    _closers: tuple[Callable[[], None], ...] = ()

    def close(self) -> None:
        """Release adapter resources. Called from the FastAPI lifespan on
        shutdown; the in-memory wiring has nothing to release and that asymmetry
        stays hidden behind this method."""
        for closer in self._closers:
            closer()


def build_container(settings: Settings | None = None) -> Container:
    """Assemble the whole application from configuration."""
    settings = settings or Settings()

    # The domain's thresholds come from configuration; their meaning does not.
    policy = LoanPolicy(
        loan_period_days=settings.loan_period_days,
        max_active_loans_per_member=settings.max_active_loans_per_member,
        late_fee_per_day=settings.late_fee_per_day,
    )
    clock: Clock = UTCClock()
    notifications = _build_notifier(settings)
    books, members, loans, closers = _build_repositories(settings)

    if settings.seed_demo_data:
        seed(books=books, members=members)

    # Four use cases, each handed exactly the ports it needs and nothing more.
    # ListCatalogue takes two collaborators, BorrowBook takes six: the
    # constructor is an honest declaration of what each operation depends on.
    return Container(
        settings=settings,
        policy=policy,
        clock=clock,
        books=books,
        members=members,
        loans=loans,
        notifications=notifications,
        borrow_book=BorrowBook(
            books=books,
            members=members,
            loans=loans,
            notifications=notifications,
            clock=clock,
            policy=policy,
        ),
        return_book=ReturnBook(
            books=books,
            members=members,
            loans=loans,
            notifications=notifications,
            clock=clock,
            policy=policy,
        ),
        list_member_loans=ListMemberLoans(
            books=books,
            members=members,
            loans=loans,
            clock=clock,
            policy=policy,
        ),
        list_catalogue=ListCatalogue(books=books, loans=loans),
        _closers=closers,
    )


def _build_notifier(settings: Settings) -> NotificationPort:
    match settings.notifier:
        case "console":
            return ConsoleNotifier()
        case "null":
            return NullNotifier()
        case "logging":
            return LoggingNotifier()
    raise ValueError(f"unsupported notifier: {settings.notifier!r}")


def _build_repositories(
    settings: Settings,
) -> tuple[BookRepository, MemberRepository, LoanRepository, tuple[Callable[[], None], ...]]:
    """Pick a persistence adapter. The entire cost of supporting two backends.

    Adding Postgres means adding a branch here and a module next to
    ``driven/sqlite.py``. The return type is stated in terms of ports, so the
    type checker enforces that whatever is returned honours the contracts.
    """
    if settings.repository == "memory":
        return (
            InMemoryBookRepository(),
            InMemoryMemberRepository(),
            InMemoryLoanRepository(),
            (),
        )

    connection: sqlite3.Connection = connect(settings.sqlite_path)
    create_schema(connection)
    # One lock shared by all three repositories, since they share one connection.
    lock = threading.Lock()
    return (
        SQLiteBookRepository(connection, lock),
        SQLiteMemberRepository(connection, lock),
        SQLiteLoanRepository(connection, lock),
        (connection.close,),
    )
