"""A small demo dataset, written through the ports.

Note the signature: ``seed`` takes ``BookRepository`` and ``MemberRepository``,
not a connection and not a file path.  So the same function seeds the in-memory
adapter for a test and the SQLite adapter for a local run, and adding a Postgres
adapter tomorrow gets seeding for free.  Anything you can express in terms of
ports is something you never have to write twice.

The ISBNs are real, hyphenated ISBN-13s.  They are stored hyphenated here on
purpose: ``ISBN`` normalises to thirteen digits, so ``GET`` by either form finds
the same book, which is easy to confirm from the docs page.
"""

from __future__ import annotations

from typing import Final

from lending.application.ports.driven import BookRepository, MemberRepository
from lending.domain.model import ISBN, Book, Member, MemberId, MemberStatus

__all__ = ["DEMO_BOOKS", "DEMO_MEMBERS", "seed"]

DEMO_BOOKS: Final = (
    Book(
        isbn=ISBN("978-0-13-235088-4"),
        title="Clean Code",
        author="Robert C. Martin",
        total_copies=2,
    ),
    Book(
        isbn=ISBN("978-0-321-12521-7"),
        title="Domain-Driven Design",
        author="Eric Evans",
        total_copies=1,
    ),
    Book(
        isbn=ISBN("978-0-13-475759-9"),
        title="Refactoring",
        author="Martin Fowler",
        total_copies=3,
    ),
    Book(
        isbn=ISBN("978-0-201-63361-0"),
        title="Design Patterns",
        author="Gamma, Helm, Johnson, Vlissides",
        total_copies=1,
    ),
)

DEMO_MEMBERS: Final = (
    Member(
        member_id=MemberId("M-001"),
        full_name="Ada Lovelace",
        email="ada@example.com",
    ),
    Member(
        member_id=MemberId("M-002"),
        full_name="Alan Turing",
        email="alan@example.com",
    ),
    # A suspended member exists in the seed so the 409 path is reachable from the
    # docs page without any setup: borrow as M-003 and the policy refuses.
    Member(
        member_id=MemberId("M-003"),
        full_name="Grace Hopper",
        email="grace@example.com",
        status=MemberStatus.SUSPENDED,
    ),
)


def seed(*, books: BookRepository, members: MemberRepository) -> None:
    """Insert the demo catalogue and members. Idempotent for both adapters."""
    for book in DEMO_BOOKS:
        books.add(book)
    for member in DEMO_MEMBERS:
        members.add(member)
