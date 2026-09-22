"""FastAPI dependencies: how a route handler gets hold of a use case.

The container is built once during startup and parked on ``app.state``.  These
providers read it back out.  Two things to notice:

* The return annotations are *ports*, not implementations.  A handler declaring
  ``BorrowBookUseCase`` cannot accidentally reach for something only the concrete
  ``BorrowBook`` class offers, so the coupling stays at the contract.
* Nothing here constructs anything.  If a provider started calling
  ``BorrowBook(...)``, wiring would be scattered between startup and request
  handling, and overriding it in a test would stop working.

The ``Annotated[...] `` aliases at the bottom exist so handler signatures read as
``borrow_book: BorrowBookDep`` instead of repeating ``Depends`` in every route.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from lending.application.ports.driving import (
    BorrowBookUseCase,
    ListCatalogueUseCase,
    ListMemberLoansUseCase,
    ReturnBookUseCase,
)
from lending.infrastructure.container import Container

__all__ = [
    "BorrowBookDep",
    "ContainerDep",
    "ListCatalogueDep",
    "ListMemberLoansDep",
    "ReturnBookDep",
    "get_container",
]


def get_container(request: Request) -> Container:
    """The single seam between FastAPI's request scope and our wiring.

    Every other provider goes through this one, which means a test that wants a
    different wiring overrides exactly one dependency.
    """
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_borrow_book(container: ContainerDep) -> BorrowBookUseCase:
    return container.borrow_book


def get_return_book(container: ContainerDep) -> ReturnBookUseCase:
    return container.return_book


def get_list_member_loans(container: ContainerDep) -> ListMemberLoansUseCase:
    return container.list_member_loans


def get_list_catalogue(container: ContainerDep) -> ListCatalogueUseCase:
    return container.list_catalogue


BorrowBookDep = Annotated[BorrowBookUseCase, Depends(get_borrow_book)]
ReturnBookDep = Annotated[ReturnBookUseCase, Depends(get_return_book)]
ListMemberLoansDep = Annotated[ListMemberLoansUseCase, Depends(get_list_member_loans)]
ListCatalogueDep = Annotated[ListCatalogueUseCase, Depends(get_list_catalogue)]
