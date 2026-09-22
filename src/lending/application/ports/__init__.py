"""Ports: the holes in the side of the hexagon.

Split by the direction the call travels, which is the distinction that actually
matters when you are trying to find something:

* ``driving``  -- the outside calls in.  Use case contracts.  Implemented here,
  called by HTTP handlers, CLI commands, queue consumers, tests.
* ``driven``   -- the application calls out.  Repositories, notifications, clock.
  Declared here, implemented by infrastructure.

"Driving" and "driven" beat "input/output" because they survive the awkward
cases: a repository read returns data *into* the application, yet it is still a
driven port, because the application is the one initiating the call.
"""

from lending.application.ports.driven import (
    BookRepository,
    Clock,
    LoanRepository,
    MemberRepository,
    NotificationPort,
)
from lending.application.ports.driving import (
    BorrowBookUseCase,
    ListCatalogueUseCase,
    ListMemberLoansUseCase,
    ReturnBookUseCase,
)

__all__ = [
    "BookRepository",
    "BorrowBookUseCase",
    "Clock",
    "ListCatalogueUseCase",
    "ListMemberLoansUseCase",
    "LoanRepository",
    "MemberRepository",
    "NotificationPort",
    "ReturnBookUseCase",
]
