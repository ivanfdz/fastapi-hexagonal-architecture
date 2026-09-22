"""Domain errors: the vocabulary the core uses to reject an operation.

Every exception here describes a *business* outcome ("this member already holds
the maximum number of loans"), never a transport or storage outcome.  Nothing in
this module knows about HTTP status codes, SQL error codes or JSON payloads.
Translating a domain error into a protocol-specific answer is the job of a
driving adapter -- see ``lending.infrastructure.driving.http.errors`` for the
HTTP mapping.

Each error carries a stable ``code`` and a ``details`` mapping so adapters can
build machine-readable payloads without parsing English prose.  That is the
difference between an error that survives a refactor and one that does not.
"""

from __future__ import annotations

from typing import Any, ClassVar

__all__ = [
    "BookNotFoundError",
    "DomainError",
    "DuplicateLoanError",
    "InvalidISBNError",
    "LoanAlreadyReturnedError",
    "LoanLimitReachedError",
    "LoanNotFoundError",
    "MemberHasOverdueLoansError",
    "MemberNotFoundError",
    "MemberSuspendedError",
    "NoCopiesAvailableError",
    "NotFoundError",
    "RuleViolationError",
]


class DomainError(Exception):
    """Base class for anything the core refuses to do.

    ``code`` is the stable identifier clients can branch on.  ``details`` holds
    the data that made the operation fail, which is what turns a generic 409
    into an actionable message in the caller's UI.
    """

    code: ClassVar[str] = "domain_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details


class NotFoundError(DomainError):
    """Something the operation referred to does not exist."""

    code = "not_found"


class BookNotFoundError(NotFoundError):
    code = "book_not_found"


class MemberNotFoundError(NotFoundError):
    code = "member_not_found"


class LoanNotFoundError(NotFoundError):
    code = "loan_not_found"


class RuleViolationError(DomainError):
    """The request was understood, and the rules of the domain say no."""

    code = "rule_violation"


class MemberSuspendedError(RuleViolationError):
    code = "member_suspended"


class MemberHasOverdueLoansError(RuleViolationError):
    code = "member_has_overdue_loans"


class LoanLimitReachedError(RuleViolationError):
    code = "loan_limit_reached"


class NoCopiesAvailableError(RuleViolationError):
    code = "no_copies_available"


class DuplicateLoanError(RuleViolationError):
    code = "duplicate_loan"


class LoanAlreadyReturnedError(RuleViolationError):
    code = "loan_already_returned"


class InvalidISBNError(DomainError):
    """The string handed in is not a well-formed ISBN-13.

    Note that this is a *domain* rule, not input validation bolted on at the
    edge: an ``ISBN`` instance cannot exist unless it passes the check digit.
    The HTTP adapter happens to report it as 422, but a CLI adapter would print
    it and a message consumer would route it to a dead-letter queue.
    """

    code = "invalid_isbn"
