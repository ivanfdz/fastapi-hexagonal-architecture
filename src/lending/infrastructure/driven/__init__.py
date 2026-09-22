"""Driven adapters: the concrete things behind the driven ports.

``memory`` and ``sqlite`` implement the same three repository protocols and are
interchangeable at startup. Neither imports the other, and neither is imported
by the application layer -- the composition root picks one and injects it.
"""

from lending.infrastructure.driven.clock import FrozenClock, SystemClock, UTCClock
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

__all__ = [
    "ConsoleNotifier",
    "FrozenClock",
    "InMemoryBookRepository",
    "InMemoryLoanRepository",
    "InMemoryMemberRepository",
    "LoggingNotifier",
    "NullNotifier",
    "SQLiteBookRepository",
    "SQLiteLoanRepository",
    "SQLiteMemberRepository",
    "SystemClock",
    "UTCClock",
    "connect",
    "create_schema",
]
