"""The application layer: use cases, the ports they speak through, and the DTOs
that cross the boundary.

This layer orchestrates; it does not decide.  Deciding is the domain's job.  A
use case loads what the rules need, asks the rules, applies the outcome and
hands back a view.  When a use case starts containing ``if`` statements about
business conditions, that logic wants to move inward to an entity or a policy.

Like the domain, this layer imports no framework.  It imports ``lending.domain``
and the standard library, which is what makes the use case tests in
``tests/application`` run in milliseconds with nothing but fakes.
"""

from lending.application.dto import (
    BookView,
    BorrowBookCommand,
    ListMemberLoansQuery,
    LoanView,
    ReturnBookCommand,
)
from lending.application.use_cases import BorrowBook, ListCatalogue, ListMemberLoans, ReturnBook

__all__ = [
    "BookView",
    "BorrowBook",
    "BorrowBookCommand",
    "ListCatalogue",
    "ListMemberLoans",
    "ListMemberLoansQuery",
    "LoanView",
    "ReturnBook",
    "ReturnBookCommand",
]
