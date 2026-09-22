"""SQLite adapters for the same three repository ports.

The second implementation is where the architecture stops being a diagram and
starts paying for itself.  Everything specific to relational storage is in this
file: the DDL, the column types, the date-to-TEXT conversion, the
``SELECT COUNT(*)`` queries, the transaction boundaries.  Search the domain and
application packages for ``sqlite``, ``SELECT`` or ``commit`` and you will find
nothing, even though the system now persists to disk.

Design notes worth copying into a real project:

* **Row mapping is explicit.** ``_to_loan`` converts a ``sqlite3.Row`` into a
  ``Loan``, and ``_to_row`` goes the other way. With an ORM this is where the
  mapper configuration would sit. Either way, the translation belongs to the
  adapter, so the entity never grows a ``__tablename__`` and never has to make
  its fields fit what a column can hold.
* **Dates are stored as ISO-8601 text.** SQLite has no date type. The conversion
  happens at the boundary, so the domain keeps working with ``datetime.date``.
* **Counting happens in SQL.** The port asks "how many open loans does this
  member have?" precisely so this adapter can answer it with an aggregate
  instead of loading rows and filtering in Python.
* **No money in the database.** Late fees are derived from the policy on read.
  Storing them would create a second source of truth that goes stale the moment
  the fee changes.

Deliberately stdlib-only: no SQLAlchemy, so the mapping is visible rather than
generated. A production adapter would likely use an ORM and a migration tool;
that is a change confined to this file.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Final, Sequence

from lending.domain.model import ISBN, Book, Loan, LoanId, Member, MemberId, MemberStatus

__all__ = [
    "SQLiteBookRepository",
    "SQLiteLoanRepository",
    "SQLiteMemberRepository",
    "connect",
    "create_schema",
]

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS books (
    isbn         TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    author       TEXT NOT NULL,
    total_copies INTEGER NOT NULL CHECK (total_copies >= 1)
);

CREATE TABLE IF NOT EXISTS members (
    member_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email     TEXT NOT NULL,
    status    TEXT NOT NULL CHECK (status IN ('active', 'suspended'))
);

CREATE TABLE IF NOT EXISTS loans (
    loan_id     TEXT PRIMARY KEY,
    isbn        TEXT NOT NULL REFERENCES books (isbn),
    member_id   TEXT NOT NULL REFERENCES members (member_id),
    borrowed_on TEXT NOT NULL,
    due_on      TEXT NOT NULL,
    returned_on TEXT
);

-- The indexes exist because of the questions the port asks, which is the right
-- reason to add an index: driven by real access patterns rather than guesswork.
CREATE INDEX IF NOT EXISTS loans_by_member ON loans (member_id, returned_on);
CREATE INDEX IF NOT EXISTS loans_by_isbn   ON loans (isbn, returned_on);
"""


def connect(database: str | Path) -> sqlite3.Connection:
    """Open a connection configured the way these adapters expect.

    ``check_same_thread=False`` is required because FastAPI runs synchronous
    endpoints in a worker thread pool, so the connection created during startup
    is used from other threads. The repositories serialise access with a lock to
    make that safe. A pool would be the answer for a real workload; for a single
    SQLite file, a lock is honest and sufficient.
    """
    connection = sqlite3.connect(str(database), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    with connection:
        connection.executescript(_SCHEMA)


class _SQLiteRepository:
    """Shared connection handling. Not a port and not a base class the
    application knows about: purely an implementation detail of this file."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.Lock | None = None) -> None:
        self._connection = connection
        # Repositories sharing one connection must share one lock, otherwise the
        # serialisation is per-repository and a borrow that touches books and
        # loans can still interleave.
        self._lock = lock or threading.Lock()


class SQLiteBookRepository(_SQLiteRepository):
    """Satisfies ``BookRepository``."""

    def add(self, book: Book) -> None:
        # Upsert rather than INSERT OR REPLACE. REPLACE deletes the conflicting
        # row before inserting, which trips the foreign key from loans the second
        # time a populated database is seeded. ON CONFLICT updates in place.
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO books (isbn, title, author, total_copies) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(isbn) DO UPDATE SET "
                "title = excluded.title, author = excluded.author, "
                "total_copies = excluded.total_copies",
                (str(book.isbn), book.title, book.author, book.total_copies),
            )

    def get(self, isbn: ISBN) -> Book | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT isbn, title, author, total_copies FROM books WHERE isbn = ?",
                (str(isbn),),
            ).fetchone()
        return _to_book(row) if row else None

    def list_all(self) -> Sequence[Book]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT isbn, title, author, total_copies FROM books ORDER BY title"
            ).fetchall()
        return tuple(_to_book(row) for row in rows)


class SQLiteMemberRepository(_SQLiteRepository):
    """Satisfies ``MemberRepository``."""

    def add(self, member: Member) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO members (member_id, full_name, email, status) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(member_id) DO UPDATE SET "
                "full_name = excluded.full_name, email = excluded.email, "
                "status = excluded.status",
                (str(member.member_id), member.full_name, member.email, str(member.status)),
            )

    def get(self, member_id: MemberId) -> Member | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT member_id, full_name, email, status FROM members WHERE member_id = ?",
                (str(member_id),),
            ).fetchone()
        return _to_member(row) if row else None


class SQLiteLoanRepository(_SQLiteRepository):
    """Satisfies ``LoanRepository``."""

    def next_identity(self) -> LoanId:
        # Generated client-side rather than by AUTOINCREMENT so the domain can
        # build a complete, valid Loan before anything is written. It also means
        # ``add`` needs no round trip to discover the id it just created.
        return LoanId(f"LOAN-{uuid.uuid4().hex[:12]}")

    def add(self, loan: Loan) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO loans (loan_id, isbn, member_id, borrowed_on, due_on, returned_on) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                _to_row(loan),
            )

    def update(self, loan: Loan) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE loans SET isbn = ?, member_id = ?, borrowed_on = ?, due_on = ?, "
                "returned_on = ? WHERE loan_id = ?",
                (
                    str(loan.isbn),
                    str(loan.member_id),
                    loan.borrowed_on.isoformat(),
                    loan.due_on.isoformat(),
                    loan.returned_on.isoformat() if loan.returned_on else None,
                    str(loan.loan_id),
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"loan {loan.loan_id} is not stored")

    def get(self, loan_id: LoanId) -> Loan | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM loans WHERE loan_id = ?", (str(loan_id),)
            ).fetchone()
        return _to_loan(row) if row else None

    def count_open_for_member(self, member_id: MemberId) -> int:
        return self._scalar(
            "SELECT COUNT(*) FROM loans WHERE member_id = ? AND returned_on IS NULL",
            (str(member_id),),
        )

    def count_open_for_isbn(self, isbn: ISBN) -> int:
        return self._scalar(
            "SELECT COUNT(*) FROM loans WHERE isbn = ? AND returned_on IS NULL",
            (str(isbn),),
        )

    def count_overdue_for_member(self, member_id: MemberId, as_of: date) -> int:
        # ISO-8601 is lexicographically ordered, which is why a TEXT column can
        # be compared with ``>`` and still mean what a date comparison means.
        return self._scalar(
            "SELECT COUNT(*) FROM loans "
            "WHERE member_id = ? AND returned_on IS NULL AND due_on < ?",
            (str(member_id), as_of.isoformat()),
        )

    def has_open_loan(self, member_id: MemberId, isbn: ISBN) -> bool:
        return (
            self._scalar(
                "SELECT COUNT(*) FROM loans "
                "WHERE member_id = ? AND isbn = ? AND returned_on IS NULL",
                (str(member_id), str(isbn)),
            )
            > 0
        )

    def list_for_member(
        self, member_id: MemberId, *, include_returned: bool = False
    ) -> Sequence[Loan]:
        query = "SELECT * FROM loans WHERE member_id = ?"
        if not include_returned:
            query += " AND returned_on IS NULL"
        query += " ORDER BY borrowed_on DESC, loan_id DESC"
        with self._lock:
            rows = self._connection.execute(query, (str(member_id),)).fetchall()
        return tuple(_to_loan(row) for row in rows)

    def _scalar(self, query: str, parameters: tuple[object, ...]) -> int:
        with self._lock:
            row = self._connection.execute(query, parameters).fetchone()
        return int(row[0])


# --------------------------------------------------------------------------- #
# Row <-> entity mapping. The only place in the codebase that knows a loan has
# columns. Note that ``_to_loan`` reconstructs through the plain constructor,
# not through ``Loan.open``: a named constructor enforces the rules for *new*
# loans, while rehydrating an existing row must reproduce it exactly as stored,
# including a due date that a since-changed policy would compute differently.
# --------------------------------------------------------------------------- #


def _to_book(row: sqlite3.Row) -> Book:
    return Book(
        isbn=ISBN(row["isbn"]),
        title=row["title"],
        author=row["author"],
        total_copies=int(row["total_copies"]),
    )


def _to_member(row: sqlite3.Row) -> Member:
    return Member(
        member_id=MemberId(row["member_id"]),
        full_name=row["full_name"],
        email=row["email"],
        status=MemberStatus(row["status"]),
    )


def _to_loan(row: sqlite3.Row) -> Loan:
    returned_on = row["returned_on"]
    return Loan(
        loan_id=LoanId(row["loan_id"]),
        isbn=ISBN(row["isbn"]),
        member_id=MemberId(row["member_id"]),
        borrowed_on=date.fromisoformat(row["borrowed_on"]),
        due_on=date.fromisoformat(row["due_on"]),
        returned_on=date.fromisoformat(returned_on) if returned_on else None,
    )


def _to_row(loan: Loan) -> tuple[object, ...]:
    return (
        str(loan.loan_id),
        str(loan.isbn),
        str(loan.member_id),
        loan.borrowed_on.isoformat(),
        loan.due_on.isoformat(),
        loan.returned_on.isoformat() if loan.returned_on else None,
    )
