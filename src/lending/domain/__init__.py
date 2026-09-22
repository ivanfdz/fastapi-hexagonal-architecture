"""The centre of the hexagon: entities, value objects and business rules.

The dependency rule for this package is absolute and easy to audit:

    grep -rn "^from \\|^import " src/lending/domain/

Everything listed is either the standard library or another module inside
``lending.domain``.  If a framework ever shows up in that output, the
architecture has been broken and the grep is the fastest way to find out.
"""

from lending.domain.errors import DomainError
from lending.domain.model import ISBN, Book, Loan, LoanId, Member, MemberId, MemberStatus
from lending.domain.policy import LoanPolicy

__all__ = [
    "ISBN",
    "Book",
    "DomainError",
    "Loan",
    "LoanId",
    "LoanPolicy",
    "Member",
    "MemberId",
    "MemberStatus",
]
