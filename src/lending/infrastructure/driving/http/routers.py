"""HTTP routes: a thin translation layer, and nothing more.

Read any handler below and you will find the same three steps: build a command
from the request, call a use case, wrap the view in a response model.  No rules,
no ``try/except``, no repository access, no date arithmetic.  That is the test for
whether a driving adapter is doing its job -- if you deleted this file and wrote a
CLI instead, no business behaviour would be lost, because none of it lives here.

The ``responses=`` declarations are not decoration.  They put the 404 and 409
payloads into the OpenAPI schema, so the failure modes are documented on ``/docs``
rather than discovered in production.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query, status

from lending.application.dto import BorrowBookCommand, ListMemberLoansQuery, ReturnBookCommand
from lending.infrastructure.driving.http.errors import HTTP_422_UNPROCESSABLE
from lending.infrastructure.driving.http.dependencies import (
    BorrowBookDep,
    ContainerDep,
    ListCatalogueDep,
    ListMemberLoansDep,
    ReturnBookDep,
)
from lending.infrastructure.driving.http.schemas import (
    BookResponse,
    BorrowBookRequest,
    CatalogueResponse,
    ErrorResponse,
    HealthResponse,
    LoanListResponse,
    LoanResponse,
    PolicyResponse,
)

__all__ = ["router"]

router = APIRouter()

# Reusable OpenAPI response declarations, so the documented failure modes stay
# consistent across endpoints instead of being retyped per route.
_CONFLICT = {
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "A lending rule refused the request.",
    }
}
_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Unknown member, book or loan.",
    }
}
_INVALID = {
    HTTP_422_UNPROCESSABLE: {
        "model": ErrorResponse,
        "description": "Malformed payload or ISBN.",
    }
}


@router.get("/health", response_model=HealthResponse, tags=["operations"], summary="Liveness probe")
def health(container: ContainerDep) -> HealthResponse:
    return HealthResponse(status="ok", repository=container.settings.repository)


@router.get(
    "/policy",
    response_model=PolicyResponse,
    tags=["operations"],
    summary="The lending rules currently in force",
)
def policy(container: ContainerDep) -> PolicyResponse:
    # Read straight off the domain object rather than off Settings: what is in
    # force is what the policy holds, and those two could in principle diverge.
    active = container.policy
    return PolicyResponse(
        loan_period_days=active.loan_period_days,
        max_active_loans_per_member=active.max_active_loans_per_member,
        late_fee_per_day=active.late_fee_per_day,
    )


@router.get(
    "/books",
    response_model=CatalogueResponse,
    tags=["catalogue"],
    summary="List the catalogue with live availability",
)
def list_catalogue(list_catalogue_use_case: ListCatalogueDep) -> CatalogueResponse:
    views = list_catalogue_use_case.execute()
    return CatalogueResponse(
        count=len(views),
        books=[BookResponse.from_view(view) for view in views],
    )


@router.post(
    "/loans",
    response_model=LoanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["loans"],
    summary="Borrow a copy of a title",
    responses={**_NOT_FOUND, **_CONFLICT, **_INVALID},
)
def borrow_book(payload: BorrowBookRequest, borrow: BorrowBookDep) -> LoanResponse:
    # Three lines, and the middle one is the only one that matters. Every rule
    # that could reject this request lives in the domain, and every way of
    # reporting the rejection lives in errors.py.
    view = borrow.execute(BorrowBookCommand(member_id=payload.member_id, isbn=payload.isbn))
    return LoanResponse.from_view(view)


@router.post(
    "/loans/{loan_id}/return",
    response_model=LoanResponse,
    tags=["loans"],
    summary="Return a borrowed copy and settle any late fee",
    responses={**_NOT_FOUND, **_CONFLICT},
)
def return_book(
    returns: ReturnBookDep,
    loan_id: str = Path(min_length=1, max_length=64, examples=["LOAN-0001"]),
) -> LoanResponse:
    # POST rather than PUT or DELETE: returning a book is an event with a side
    # effect (the fee), not the removal of a loan. The loan record survives and
    # is exactly what the response describes.
    view = returns.execute(ReturnBookCommand(loan_id=loan_id))
    return LoanResponse.from_view(view)


@router.get(
    "/members/{member_id}/loans",
    response_model=LoanListResponse,
    tags=["loans"],
    summary="List the loans of one member",
    responses={**_NOT_FOUND},
)
def list_member_loans(
    loans: ListMemberLoansDep,
    member_id: str = Path(min_length=1, max_length=64, examples=["M-001"]),
    include_returned: bool = Query(
        default=False, description="Include loans that have already been returned."
    ),
) -> LoanListResponse:
    views = loans.execute(
        ListMemberLoansQuery(member_id=member_id, include_returned=include_returned)
    )
    return LoanListResponse(
        member_id=member_id,
        count=len(views),
        loans=[LoanResponse.from_view(view) for view in views],
    )
