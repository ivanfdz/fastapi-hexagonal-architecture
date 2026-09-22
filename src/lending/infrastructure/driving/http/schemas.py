"""Pydantic models: the HTTP contract, and nothing but the HTTP contract.

This is where Pydantic belongs in a hexagonal codebase -- on the boundary, doing
the job it is best at: parsing untrusted input, rejecting malformed shapes, and
generating the OpenAPI schema that makes ``/docs`` useful.

The schemas mirror the application's DTOs, and people reasonably ask why not
just return ``LoanView`` and skip a layer.  Because they answer to different
masters.  ``LoanView`` is shaped by what the use cases produce; ``LoanResponse``
is shaped by what published JSON must keep promising.  Keeping them separate is
what lets you rename a field in the core without breaking a client, or expose a
field over HTTP that the core computes but does not name the same way.  On a
small project the two files look redundant; the first time you need to version an
endpoint, the seam is already there.

If you want to collapse them, the ``from_view`` classmethods are the only place
that knows both shapes, so the coupling stays in one readable spot either way.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from lending.application.dto import BookView, LoanView

__all__ = [
    "BookResponse",
    "BorrowBookRequest",
    "CatalogueResponse",
    "ErrorResponse",
    "HealthResponse",
    "LoanListResponse",
    "LoanResponse",
    "PolicyResponse",
]


# Money crosses the wire as a fixed-precision string, never as a JSON number.
# A float round-trip is capable of turning 1.15 into 1.1499999999999999, and a
# fee is not the place to find that out. Clients parse it with their own decimal
# type; the schema documents the format.
MoneyString = Annotated[
    Decimal,
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str, when_used="json"),
    Field(description="Amount with two decimal places, serialised as a string.", examples=["1.50"]),
]


class BorrowBookRequest(BaseModel):
    """Body of ``POST /loans``.

    ``extra="forbid"`` makes a typo in a field name a 422 instead of a silently
    ignored key, which is the behaviour you want the day someone sends
    ``{"isbn_": ...}`` and cannot work out why nothing happened.

    Validation here is structural only -- is it a non-empty string of plausible
    length. Whether the digits form a valid ISBN-13 is a domain rule and lives in
    the ``ISBN`` value object, so it holds for every adapter, not just this one.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"member_id": "M-001", "isbn": "978-0-13-235088-4"}]
        },
    )

    member_id: str = Field(
        min_length=1,
        max_length=64,
        description="Identifier of the borrowing member.",
        examples=["M-001"],
    )
    isbn: str = Field(
        min_length=10,
        max_length=32,
        description="ISBN-13 of the title, with or without hyphens.",
        examples=["978-0-13-235088-4"],
    )


class LoanResponse(BaseModel):
    """A loan as published over HTTP."""

    model_config = ConfigDict(extra="forbid")

    loan_id: str = Field(examples=["LOAN-0001"])
    isbn: str = Field(description="Normalised ISBN-13, digits only.", examples=["9780132350884"])
    title: str = Field(examples=["Clean Code"])
    member_id: str = Field(examples=["M-001"])
    borrowed_on: date
    due_on: date
    returned_on: date | None = Field(default=None, description="Null while the loan is open.")
    is_open: bool
    days_overdue: int = Field(ge=0, description="Whole days past the due date; 0 when on time.")
    late_fee: MoneyString

    @classmethod
    def from_view(cls, view: LoanView) -> Self:
        """The single point of contact between the application DTO and the wire
        format. Change the core's field names and only this line breaks."""
        return cls(
            loan_id=view.loan_id,
            isbn=view.isbn,
            title=view.title,
            member_id=view.member_id,
            borrowed_on=view.borrowed_on,
            due_on=view.due_on,
            returned_on=view.returned_on,
            is_open=view.is_open,
            days_overdue=view.days_overdue,
            late_fee=view.late_fee,
        )


class LoanListResponse(BaseModel):
    """Envelope rather than a bare array: it leaves room to add paging metadata
    later without turning the response into a different JSON type."""

    model_config = ConfigDict(extra="forbid")

    member_id: str
    count: int
    loans: list[LoanResponse]


class BookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isbn: str
    title: str
    author: str
    total_copies: int
    copies_available: int = Field(description="Derived from open loans, never stored.")

    @classmethod
    def from_view(cls, view: BookView) -> Self:
        return cls(
            isbn=view.isbn,
            title=view.title,
            author=view.author,
            total_copies=view.total_copies,
            copies_available=view.copies_available,
        )


class CatalogueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    books: list[BookResponse]


class ErrorResponse(BaseModel):
    """One error shape for every failure this API can produce.

    ``code`` comes straight from ``DomainError.code``, so clients branch on a
    stable identifier instead of pattern-matching English. ``details`` carries the
    numbers behind the refusal -- the limit that was hit, the copies on loan --
    which is what lets a UI say something useful.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "loan_limit_reached",
                    "message": "This member already holds the maximum number of loans.",
                    "details": {"member_id": "M-001", "open_loans": 3, "limit": 3},
                }
            ]
        },
    )

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    repository: str = Field(description="Which persistence adapter is wired in.")


class PolicyResponse(BaseModel):
    """The active lending rules, so a client can explain them to a user rather
    than hardcoding a copy that drifts."""

    model_config = ConfigDict(extra="forbid")

    loan_period_days: int
    max_active_loans_per_member: int
    late_fee_per_day: MoneyString
