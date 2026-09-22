"""Tests for the HTTP adapter.

These deliberately do *not* re-test the business rules -- those are covered in
``tests/domain`` and ``tests/application``, without a web server.  What is left
for this layer is translation, and translation is all that can break here:

* Does a command get built correctly from the request body?
* Does each domain error land on the right status code?
* Does the JSON carry the fields the contract promises, in the promised types?

The application is built with ``create_app(Settings(...))``, which is why there
are no environment variables, no patched globals and no database. Passing
settings to the factory is the whole configuration story.

Worth noting what is absent from the API itself: authentication. Every endpoint
is open, which is fine for a teaching example and would not be fine in a
deployment -- see the README for where an auth dependency would go.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from lending.infrastructure.config import Settings
from lending.infrastructure.driving.http.app import create_app

ISBN_CLEAN_CODE = "978-0-13-235088-4"
ISBN_CLEAN_CODE_PLAIN = "9780132350884"
ISBN_DDD = "978-0-321-12521-7"
ISBN_REFACTORING = "978-0-13-475759-9"
ISBN_PATTERNS = "978-0-201-63361-0"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An app wired to in-memory repositories and a silent notifier.

    ``TestClient`` as a context manager is what triggers the lifespan, so the
    container really is built and closed the way it is in production.
    """
    settings = Settings(
        repository="memory",
        notifier="null",
        seed_demo_data=True,
        loan_period_days=14,
        max_active_loans_per_member=3,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def borrow(client: TestClient, member_id: str = "M-001", isbn: str = ISBN_CLEAN_CODE):
    return client.post("/loans", json={"member_id": member_id, "isbn": isbn})


class TestOperations:
    def test_health_reports_the_active_adapter(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "repository": "memory"}

    def test_policy_exposes_the_rules_in_force(self, client: TestClient) -> None:
        assert client.get("/policy").json() == {
            "loan_period_days": 14,
            "max_active_loans_per_member": 3,
            "late_fee_per_day": "0.50",
        }

    def test_openapi_schema_is_generated(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "/loans" in schema["paths"]
        # The failure modes are documented, not just the happy path.
        assert "409" in schema["paths"]["/loans"]["post"]["responses"]


class TestCatalogue:
    def test_lists_the_seeded_titles(self, client: TestClient) -> None:
        body = client.get("/books").json()
        assert body["count"] == 4
        assert [book["title"] for book in body["books"]][0] == "Clean Code"

    def test_availability_drops_after_borrowing(self, client: TestClient) -> None:
        borrow(client)
        clean_code = next(
            book for book in client.get("/books").json()["books"] if book["title"] == "Clean Code"
        )
        assert clean_code == {
            "isbn": ISBN_CLEAN_CODE_PLAIN,
            "title": "Clean Code",
            "author": "Robert C. Martin",
            "total_copies": 2,
            "copies_available": 1,
        }


class TestBorrowEndpoint:
    def test_returns_201_and_the_loan(self, client: TestClient) -> None:
        response = borrow(client)

        assert response.status_code == 201
        body = response.json()
        assert body["member_id"] == "M-001"
        assert body["isbn"] == ISBN_CLEAN_CODE_PLAIN  # normalised by the domain
        assert body["title"] == "Clean Code"
        assert body["is_open"] is True
        assert body["returned_on"] is None
        assert body["days_overdue"] == 0
        # Money is a string with two decimals, never a JSON float.
        assert body["late_fee"] == "0.00"

    def test_due_date_is_the_term_after_the_borrow_date(self, client: TestClient) -> None:
        from datetime import date, timedelta

        body = borrow(client).json()
        borrowed_on = date.fromisoformat(body["borrowed_on"])
        assert date.fromisoformat(body["due_on"]) == borrowed_on + timedelta(days=14)

    def test_unknown_member_is_404_with_a_code(self, client: TestClient) -> None:
        response = borrow(client, member_id="M-999")
        assert response.status_code == 404
        assert response.json() == {
            "code": "member_not_found",
            "message": "No such member.",
            "details": {"member_id": "M-999"},
        }

    def test_uncatalogued_title_is_404(self, client: TestClient) -> None:
        response = borrow(client, isbn="978-1-59327-584-6")
        assert response.status_code == 404
        assert response.json()["code"] == "book_not_found"

    def test_malformed_isbn_is_422_from_the_domain(self, client: TestClient) -> None:
        # Long enough to clear the Pydantic min_length, so the check digit rule in
        # the ISBN value object is what rejects it: one digit off a real ISBN.
        response = borrow(client, isbn="9780132350883")
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_isbn"

    def test_too_short_isbn_is_422_from_pydantic(self, client: TestClient) -> None:
        # The other kind of 422: structural validation at the edge. Note the body
        # shape differs, because this one never reached the domain.
        response = borrow(client, isbn="123")
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_unknown_body_field_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/loans", json={"member_id": "M-001", "isbn": ISBN_CLEAN_CODE, "oops": 1}
        )
        assert response.status_code == 422

    def test_suspended_member_is_409(self, client: TestClient) -> None:
        response = borrow(client, member_id="M-003")
        assert response.status_code == 409
        assert response.json()["code"] == "member_suspended"

    def test_loan_limit_is_409_with_the_numbers(self, client: TestClient) -> None:
        for isbn in (ISBN_CLEAN_CODE, ISBN_DDD, ISBN_REFACTORING):
            assert borrow(client, isbn=isbn).status_code == 201

        response = borrow(client, isbn=ISBN_PATTERNS)
        assert response.status_code == 409
        assert response.json() == {
            "code": "loan_limit_reached",
            "message": "This member already holds the maximum number of loans.",
            "details": {"member_id": "M-001", "open_loans": 3, "limit": 3},
        }

    def test_duplicate_title_is_409(self, client: TestClient) -> None:
        borrow(client)
        response = borrow(client)
        assert response.status_code == 409
        assert response.json()["code"] == "duplicate_loan"

    def test_last_copy_is_409_for_the_second_member(self, client: TestClient) -> None:
        assert borrow(client, member_id="M-001", isbn=ISBN_DDD).status_code == 201
        response = borrow(client, member_id="M-002", isbn=ISBN_DDD)
        assert response.status_code == 409
        assert response.json()["code"] == "no_copies_available"


class TestReturnEndpoint:
    def test_closes_the_loan(self, client: TestClient) -> None:
        loan_id = borrow(client).json()["loan_id"]

        response = client.post(f"/loans/{loan_id}/return")

        assert response.status_code == 200
        body = response.json()
        assert body["is_open"] is False
        assert body["returned_on"] is not None
        assert body["late_fee"] == "0.00"

    def test_unknown_loan_is_404(self, client: TestClient) -> None:
        response = client.post("/loans/LOAN-9999/return")
        assert response.status_code == 404
        assert response.json()["code"] == "loan_not_found"

    def test_returning_twice_is_409(self, client: TestClient) -> None:
        loan_id = borrow(client).json()["loan_id"]
        client.post(f"/loans/{loan_id}/return")

        response = client.post(f"/loans/{loan_id}/return")
        assert response.status_code == 409
        assert response.json()["code"] == "loan_already_returned"

    def test_returning_frees_the_limit(self, client: TestClient) -> None:
        loan_id = borrow(client).json()["loan_id"]
        for isbn in (ISBN_DDD, ISBN_REFACTORING):
            borrow(client, isbn=isbn)
        client.post(f"/loans/{loan_id}/return")

        assert borrow(client, isbn=ISBN_PATTERNS).status_code == 201


class TestMemberLoansEndpoint:
    def test_empty_envelope_for_a_member_with_no_loans(self, client: TestClient) -> None:
        assert client.get("/members/M-002/loans").json() == {
            "member_id": "M-002",
            "count": 0,
            "loans": [],
        }

    def test_unknown_member_is_404(self, client: TestClient) -> None:
        assert client.get("/members/M-999/loans").status_code == 404

    def test_open_loans_only_by_default(self, client: TestClient) -> None:
        kept = borrow(client).json()["loan_id"]
        closed = borrow(client, isbn=ISBN_DDD).json()["loan_id"]
        client.post(f"/loans/{closed}/return")

        body = client.get("/members/M-001/loans").json()
        assert body["count"] == 1
        assert body["loans"][0]["loan_id"] == kept

    def test_include_returned_shows_the_history(self, client: TestClient) -> None:
        borrow(client)
        closed = borrow(client, isbn=ISBN_DDD).json()["loan_id"]
        client.post(f"/loans/{closed}/return")

        body = client.get("/members/M-001/loans", params={"include_returned": True}).json()
        assert body["count"] == 2


class TestAdapterIsInterchangeable:
    def test_the_same_requests_work_against_sqlite(self, tmp_path) -> None:
        """The architectural claim, asserted.

        Only ``repository`` changes. The routes, the payloads and the status codes
        are identical, because nothing above the composition root knows which
        adapter was chosen.
        """
        settings = Settings(
            repository="sqlite",
            sqlite_path=tmp_path / "http.db",
            notifier="null",
            seed_demo_data=True,
        )
        with TestClient(create_app(settings)) as sqlite_client:
            assert sqlite_client.get("/health").json()["repository"] == "sqlite"

            created = borrow(sqlite_client)
            assert created.status_code == 201
            loan_id = created.json()["loan_id"]

            assert borrow(sqlite_client).status_code == 409  # duplicate title
            assert sqlite_client.post(f"/loans/{loan_id}/return").status_code == 200
            assert sqlite_client.get("/members/M-001/loans").json()["count"] == 0

    def test_data_survives_a_restart_with_sqlite(self, tmp_path) -> None:
        """And the difference that does show: persistence.

        Two separate app instances over the same file. The in-memory adapter would
        start empty; that is the only observable distinction, and it is the one you
        actually wanted.
        """
        settings = Settings(
            repository="sqlite",
            sqlite_path=tmp_path / "restart.db",
            notifier="null",
            seed_demo_data=True,
        )

        with TestClient(create_app(settings)) as first:
            loan_id = borrow(first).json()["loan_id"]

        with TestClient(create_app(settings)) as second:
            body = second.get("/members/M-001/loans").json()
            assert body["count"] == 1
            assert body["loans"][0]["loan_id"] == loan_id
