"""Use case: the catalogue with live availability.

Availability is not stored anywhere.  It is ``total_copies`` minus the number of
open loans, and the fact that it is derived rather than persisted is why it
cannot drift out of sync with reality.  The subtraction itself belongs to
``Book.copies_available``; this use case only supplies the count.
"""

from __future__ import annotations

from typing import Sequence

from lending.application.dto import BookView, book_view
from lending.application.ports.driven import BookRepository, LoanRepository

__all__ = ["ListCatalogue"]


class ListCatalogue:
    """Implements ``ListCatalogueUseCase``."""

    def __init__(self, *, books: BookRepository, loans: LoanRepository) -> None:
        self._books = books
        self._loans = loans

    def execute(self) -> Sequence[BookView]:
        views = [
            book_view(book=book, copies_on_loan=self._loans.count_open_for_isbn(book.isbn))
            for book in self._books.list_all()
        ]
        views.sort(key=lambda view: (view.title.casefold(), view.isbn))
        return tuple(views)
