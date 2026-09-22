"""Driving ports, also called primary or inbound ports.

This file *is* the public API of the application, and it fits on one screen.
Four operations, each a command or query in and a view out.  A new contributor
can read it in thirty seconds and know everything the system can do, which is a
claim you cannot make about a folder of route handlers.

Driving ports are less talked about than driven ones, and they are optional in
the sense that you could type the FastAPI dependencies against the concrete
``BorrowBook`` class and everything would still run.  Declaring them buys three
things:

* The HTTP adapter depends on an abstraction, so it can be wired to a decorated
  or instrumented implementation without noticing.
* Adding a caching, retrying or authorisation decorator means writing a class
  that satisfies the protocol and swapping it in the composition root.  No use
  case and no adapter changes.
* The set of supported operations is documented in one place instead of being
  implied by whatever routers happen to exist.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from lending.application.dto import (
    BookView,
    BorrowBookCommand,
    ListMemberLoansQuery,
    LoanView,
    ReturnBookCommand,
)

__all__ = [
    "BorrowBookUseCase",
    "ListCatalogueUseCase",
    "ListMemberLoansUseCase",
    "ReturnBookUseCase",
]


@runtime_checkable
class BorrowBookUseCase(Protocol):
    def execute(self, command: BorrowBookCommand) -> LoanView:
        """Lend one copy of a title to a member.

        Raises a ``DomainError`` subclass when a rule forbids it; the caller is
        expected to translate, not to guess.
        """
        ...


@runtime_checkable
class ReturnBookUseCase(Protocol):
    def execute(self, command: ReturnBookCommand) -> LoanView:
        """Close an open loan and report the fee owed, if any."""
        ...


@runtime_checkable
class ListMemberLoansUseCase(Protocol):
    def execute(self, query: ListMemberLoansQuery) -> Sequence[LoanView]: ...


@runtime_checkable
class ListCatalogueUseCase(Protocol):
    def execute(self) -> Sequence[BookView]: ...
