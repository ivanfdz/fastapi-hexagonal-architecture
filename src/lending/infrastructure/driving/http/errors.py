"""Domain errors to HTTP status codes, in one table.

This file is the reason no route handler in this project contains a
``try/except``.  The use cases raise domain errors; a single exception handler
translates them; handlers stay three lines long and describe the happy path only.

The mapping being data rather than control flow matters.  Adding a rule means
adding an exception class in the domain and one row below -- and if you forget
the row, the fallback still produces a well-formed ``ErrorResponse`` with the
right code, just with a coarser status.  Compare that to scattered
``except`` blocks, where forgetting one yields a 500 and a stack trace in the
client's face.

Status choices, since they are the arguable part:

* **404** for anything that does not exist.
* **409 Conflict** for a request that is well formed and refused by a business
  rule. The state of the resource is the problem, not the syntax of the request,
  and the client may well succeed after returning a book. 422 would suggest the
  payload was wrong, which it was not.
* **422** for a malformed ISBN, matching what FastAPI already returns for schema
  violations, since a bad check digit really is a malformed field.
* **400** as the fallback for an unmapped ``DomainError``.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from lending.domain.errors import (
    DomainError,
    DuplicateLoanError,
    InvalidISBNError,
    LoanAlreadyReturnedError,
    LoanLimitReachedError,
    MemberHasOverdueLoansError,
    MemberSuspendedError,
    NoCopiesAvailableError,
    NotFoundError,
)

__all__ = ["HTTP_422_UNPROCESSABLE", "register_exception_handlers", "status_for"]

# Spelled as a literal rather than taken from ``fastapi.status``: Starlette
# renamed HTTP_422_UNPROCESSABLE_ENTITY to HTTP_422_UNPROCESSABLE_CONTENT and
# deprecated the old name, so referencing either one pins the project to a
# version window. The number has not changed since RFC 4918.
HTTP_422_UNPROCESSABLE: Final = 422

_STATUS_BY_ERROR: Final[dict[type[DomainError], int]] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    MemberSuspendedError: status.HTTP_409_CONFLICT,
    MemberHasOverdueLoansError: status.HTTP_409_CONFLICT,
    LoanLimitReachedError: status.HTTP_409_CONFLICT,
    NoCopiesAvailableError: status.HTTP_409_CONFLICT,
    DuplicateLoanError: status.HTTP_409_CONFLICT,
    LoanAlreadyReturnedError: status.HTTP_409_CONFLICT,
    InvalidISBNError: HTTP_422_UNPROCESSABLE,
}


def status_for(error: DomainError) -> int:
    """Walk the exception's MRO for the most specific mapped status.

    Walking the MRO rather than doing an exact type lookup means a new subclass
    of ``NotFoundError`` is a 404 automatically, without touching this file.
    """
    for error_type in type(error).__mro__:
        if error_type in _STATUS_BY_ERROR:
            return _STATUS_BY_ERROR[error_type]
    return status.HTTP_400_BAD_REQUEST


def register_exception_handlers(app: FastAPI) -> None:
    """Install one handler for the whole ``DomainError`` hierarchy.

    Starlette resolves handlers by walking the raised exception's MRO, so
    registering the base class catches every subclass, including ones added
    later.
    """

    async def handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
        # Starlette types the handler against ``Exception``; the registration
        # below guarantees what actually arrives.
        assert isinstance(exc, DomainError)
        return JSONResponse(
            status_code=status_for(exc),
            content={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    app.add_exception_handler(DomainError, handle_domain_error)
