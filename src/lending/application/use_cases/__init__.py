"""One module per use case.

Grouping by use case rather than by technical kind ("services", "handlers")
keeps the reason a file changes aligned with the file itself: a change to the
borrowing rules touches ``borrow_book.py`` and nothing else.  A 900-line
``LendingService`` class, by contrast, is a file that every ticket touches.
"""

from lending.application.use_cases.borrow_book import BorrowBook
from lending.application.use_cases.list_catalogue import ListCatalogue
from lending.application.use_cases.list_member_loans import ListMemberLoans
from lending.application.use_cases.return_book import ReturnBook

__all__ = ["BorrowBook", "ListCatalogue", "ListMemberLoans", "ReturnBook"]
