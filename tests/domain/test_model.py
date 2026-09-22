"""Domain tests: no fixtures, no I/O, no framework.

Every test below constructs its subject inline and asserts on a return value.
That is what the dependency rule buys: the rules of the business are testable
with nothing installed, so these tests stay fast and keep passing through changes
of database, framework and transport.
"""

from __future__ import annotations

from datetime import date

import pytest

from lending.domain.errors import InvalidISBNError, LoanAlreadyReturnedError
from lending.domain.model import ISBN, Book, Loan, LoanId, Member, MemberId, MemberStatus

BORROWED_ON = date(2026, 3, 2)


class TestISBN:
    def test_normalises_hyphenated_input(self) -> None:
        assert ISBN("978-0-13-235088-4").value == "9780132350884"

    def test_hyphenated_and_plain_forms_are_equal(self) -> None:
        # Value object equality is by content, which is what lets a repository
        # key on the ISBN without caring how the caller typed it.
        assert ISBN("978-0-13-235088-4") == ISBN("9780132350884")

    def test_is_hashable_so_it_can_key_a_dict(self) -> None:
        assert {ISBN("9780132350884"): "clean code"}[ISBN("978-0-13-235088-4")] == "clean code"

    @pytest.mark.parametrize(
        "raw",
        [
            "9780132350883",  # correct length, wrong check digit
            "978013235088",  # twelve digits
            "97801323508845",  # fourteen digits
            "978-0-13-23508X-4",  # non-digit
            "",
        ],
    )
    def test_rejects_anything_that_is_not_an_isbn13(self, raw: str) -> None:
        with pytest.raises(InvalidISBNError):
            ISBN(raw)

    def test_rejects_a_degenerate_string_with_an_accidentally_valid_checksum(self) -> None:
        # Thirteen zeros satisfy the check digit, which is exactly why the prefix
        # rule exists. A regex in a request schema would have let this through.
        with pytest.raises(InvalidISBNError):
            ISBN("0000000000000")

    def test_accepts_the_979_prefix(self) -> None:
        assert ISBN("9791234567896").value == "9791234567896"

    def test_is_immutable(self) -> None:
        isbn = ISBN("9780132350884")
        with pytest.raises(Exception):
            isbn.value = "9780321125217"  # type: ignore[misc]


class TestBook:
    def test_availability_is_derived_not_stored(self) -> None:
        book = Book(isbn=ISBN("9780132350884"), title="Clean Code", author="RCM", total_copies=3)
        assert book.copies_available(copies_on_loan=2) == 1

    def test_availability_never_goes_negative(self) -> None:
        book = Book(isbn=ISBN("9780132350884"), title="Clean Code", author="RCM", total_copies=1)
        assert book.copies_available(copies_on_loan=5) == 0

    def test_a_catalogued_book_needs_at_least_one_copy(self) -> None:
        with pytest.raises(ValueError):
            Book(isbn=ISBN("9780132350884"), title="Clean Code", author="RCM", total_copies=0)


class TestMember:
    def test_active_by_default(self) -> None:
        member = Member(member_id=MemberId("M-001"), full_name="Ada", email="ada@example.com")
        assert member.is_active is True

    def test_suspended_member_is_not_active(self) -> None:
        member = Member(
            member_id=MemberId("M-003"),
            full_name="Grace",
            email="grace@example.com",
            status=MemberStatus.SUSPENDED,
        )
        assert member.is_active is False

    def test_rejects_an_unusable_email(self) -> None:
        with pytest.raises(ValueError):
            Member(member_id=MemberId("M-001"), full_name="Ada", email="not-an-email")


def _loan(**overrides: object) -> Loan:
    defaults: dict[str, object] = {
        "loan_id": LoanId("LOAN-0001"),
        "isbn": ISBN("9780132350884"),
        "member_id": MemberId("M-001"),
        "borrowed_on": BORROWED_ON,
        "loan_period_days": 14,
    }
    defaults.update(overrides)
    return Loan.open(**defaults)  # type: ignore[arg-type]


class TestLoan:
    def test_named_constructor_derives_the_due_date(self) -> None:
        loan = _loan()
        assert loan.borrowed_on == BORROWED_ON
        assert loan.due_on == date(2026, 3, 16)
        assert loan.is_open is True

    def test_rejects_a_non_positive_loan_period(self) -> None:
        with pytest.raises(ValueError):
            _loan(loan_period_days=0)

    def test_is_not_overdue_on_the_due_date_itself(self) -> None:
        # The boundary case that everyone gets wrong once. The due date is the
        # last day you may hold the book, so lateness starts the day after.
        loan = _loan()
        assert loan.is_overdue(date(2026, 3, 16)) is False
        assert loan.is_overdue(date(2026, 3, 17)) is True

    def test_days_overdue_is_zero_while_within_the_term(self) -> None:
        assert _loan().days_overdue(date(2026, 3, 10)) == 0

    def test_days_overdue_counts_whole_days_past_the_due_date(self) -> None:
        assert _loan().days_overdue(date(2026, 3, 20)) == 4

    def test_closing_reports_lateness_and_flips_the_state(self) -> None:
        loan = _loan()
        assert loan.close(date(2026, 3, 20)) == 4
        assert loan.is_open is False
        assert loan.returned_on == date(2026, 3, 20)

    def test_lateness_freezes_once_returned(self) -> None:
        # A loan returned four days late stays four days late forever, however
        # long ago that was. Reading "now" inside the entity would break this.
        loan = _loan()
        loan.close(date(2026, 3, 20))
        assert loan.days_overdue(date(2027, 1, 1)) == 4

    def test_a_returned_loan_is_no_longer_overdue(self) -> None:
        loan = _loan()
        loan.close(date(2026, 3, 20))
        assert loan.is_overdue(date(2026, 3, 25)) is False

    def test_cannot_be_closed_twice(self) -> None:
        loan = _loan()
        loan.close(date(2026, 3, 10))
        with pytest.raises(LoanAlreadyReturnedError) as raised:
            loan.close(date(2026, 3, 11))
        # The error carries the data an adapter needs to explain itself.
        assert raised.value.details["loan_id"] == "LOAN-0001"
        assert raised.value.code == "loan_already_returned"

    def test_cannot_be_returned_before_it_was_borrowed(self) -> None:
        with pytest.raises(ValueError):
            _loan().close(date(2026, 3, 1))
