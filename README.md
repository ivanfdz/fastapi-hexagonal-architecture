# Hexagonal Architecture in Python

A book lending service, small enough to read in one sitting and complete enough to
run, built as a hexagon. The business rules live in plain Python classes that
import nothing but the standard library. FastAPI is a driving adapter bolted onto
one side of them. Storage is a driven adapter bolted onto the other, and there are
two interchangeable implementations of it, chosen by an environment variable.

Most hexagonal architecture write-ups stop at the diagram, and the diagram is the
easy part. What is rarely shown is the payoff: what the swap actually looks like in
code, what the tests look like when the rules have no dependencies, and what
"translation layer" means once you try to write one. So this repository leans on
three things a diagram cannot give you. `examples/swap_adapters.py` runs the same
use case against three different sets of adapters and prints the results.
`tests/infrastructure/test_repository_contract.py` runs one contract suite against
both storage backends, so "interchangeable" is asserted rather than claimed.
`tests/test_architecture.py` parses the import statements of every module in the
core and fails the build if one points the wrong way.

Every file carries comments explaining why it is shaped the way it is, not just
what it does. The code is the tutorial.

## The one rule

Hexagonal architecture, ports and adapters, clean architecture and the onion all
reduce to the same constraint:

> Source code dependencies point inward. The things that change for business
> reasons never depend on the things that change for technical reasons.

Your lending rules do not change because you moved from SQLite to Postgres. So
they must not import a database driver. They do not change because you added a
GraphQL endpoint next to the REST one, so they must not import a web framework.
Turn that into a directory structure and enforce it, and you have the whole idea.

Everything else in this README is consequences.

## Architecture

```
                         DRIVING SIDE                                  DRIVEN SIDE
                     (the world calls in)                        (the app calls out)

   ┌──────────────────┐                                                  ┌──────────────────────┐
   │  HTTP client     │                                                  │  in-memory dicts     │
   │  curl, /docs     │                                                  │  driven/memory.py    │
   └────────┬─────────┘                                                  └──────────▲───────────┘
            │                                                                       │
            │ JSON                        ┌─ ─ ─ ─ ─ ─ ─ ─ ─┐              implements│
            ▼                            ╱                   ╲                       │
   ┌──────────────────┐                 ╱    lending.domain   ╲             ┌─────────┴────────────┐
   │  FastAPI adapter │   BorrowBook-  ╱                       ╲  Book-     │  SQLite              │
   │  driving/http/   │───UseCase────▶▕  ISBN  Book  Member     ▏──Repo────▶│  driven/sqlite.py    │
   │  routers.py      │   (driving     ▏ Loan   LoanPolicy      ▏  Loan-    └──────────────────────┘
   │  schemas.py      │    port)       ▏                        ▏  Repo-
   │  errors.py       │                 ╲   lending.application ╱   sitory   ┌─────────────────────┐
   └──────────────────┘                  ╲  BorrowBook          ╱            │  console / logging  │
            ▲                             ╲ ReturnBook        ╱  Notifi-     │  / null notifier    │
            │                              └─ ─ ─ ─ ─ ─ ─ ─ ─┘  cation──────▶│  notifications.py   │
   ┌────────┴─────────┐                                          Port        └─────────────────────┘
   │  a CLI, a queue  │                    ▲                                 ┌─────────────────────┐
   │  consumer, a     │                    │                       Clock     │  UTC / system /     │
   │  cron job ...    │              built by the             ─────────────▶ │  frozen clock       │
   │  (not written)   │          composition root                            └─────────────────────┘
   └──────────────────┘          infrastructure/container.py
```

Two kinds of hole in the side of the hexagon, and the distinction is about who
initiates the call, not which way the data flows:

- **Driving ports** (primary, inbound). The outside calls in. They are the use
  case contracts in `application/ports/driving.py` — four operations, one screen,
  the complete public API of the application.
- **Driven ports** (secondary, outbound). The application calls out. Repositories,
  notifications and the clock, declared in `application/ports/driven.py` and
  implemented out in `infrastructure/driven/`.

A repository read returns data *into* the application and is still a driven port,
because the application is the caller. That is why "driving/driven" survives the
edge cases better than "input/output".

## The domain

A small library lends books. The rules are arbitrary but interlocking enough to be
interesting:

- A loan runs for **14 days**. The due date is derived on creation, never typed in.
- A member may hold **3 open loans** at once.
- A member cannot hold **two copies of the same title**.
- A **suspended** member cannot borrow at all.
- A member with anything **overdue** cannot borrow until they return it.
- A title can only be lent while a copy is available: `total_copies` minus open
  loans. Availability is never stored, so it cannot go stale.
- Returning late costs **0.50 per day**, rounded to cents, computed with `Decimal`.
- A loan can be returned exactly **once**.
- Lateness **freezes on return**. A book returned four days late stays four days
  late a year later.

Where each rule lives is the interesting part, and the split is mechanical:

| Rule | Owner | Why |
| --- | --- | --- |
| ISBN-13 format and check digit | `ISBN` value object | A value object can make an invalid value unrepresentable. |
| Due date from a term | `Loan.open` | Derived from one entity's own fields. |
| Overdue, days late, freeze on return | `Loan` | Same: one loan, its own fields. |
| Cannot return twice | `Loan.close` | A guard on a state transition belongs with the transition. |
| Loan limit, duplicate title, availability, suspension | `LoanPolicy` | Needs facts about *other* loans, so it takes counts as arguments. |
| Fee arithmetic | `LoanPolicy` | Depends on a configured rate. |
| "Not found" is an error | use case | A storage miss is a fact; treating it as a failure is a decision. |

The heuristic: rules a single entity can check from its own fields go on the
entity. Rules that need several entities or a configured threshold go in a policy
that *receives* the facts instead of fetching them. That is why every rule in
`tests/domain/test_policy.py` is a two-line test with no fixtures — the policy is
handed `open_loans_by_member=3` rather than having to find three loans somewhere.

## Layout

```
src/lending/
├── domain/                     ← no dependencies at all
│   ├── model.py                  ISBN, Book, Member, Loan
│   ├── policy.py                 LoanPolicy: the cross-entity rules
│   └── errors.py                 the vocabulary for refusing an operation
│
├── application/                ← depends on domain only
│   ├── dto.py                    commands, queries, views
│   ├── ports/
│   │   ├── driving.py            use case contracts (the app's public API)
│   │   └── driven.py             repositories, notifications, clock
│   └── use_cases/
│       ├── borrow_book.py        the richest one; read this first
│       ├── return_book.py
│       ├── list_member_loans.py
│       └── list_catalogue.py
│
└── infrastructure/             ← depends on both; nothing depends on it
    ├── config.py                 pydantic-settings, reads LENDING_* env vars
    ├── container.py              THE COMPOSITION ROOT: the only file that
    │                             knows every concrete type
    ├── seed.py                   demo data, written through ports
    ├── driven/
    │   ├── memory.py             dict-backed repositories
    │   ├── sqlite.py             the same ports over SQL, stdlib sqlite3
    │   ├── notifications.py      console / logging / null
    │   └── clock.py              UTC / system / frozen
    └── driving/http/
        ├── app.py                create_app() factory + lifespan
        ├── routers.py            URL and verb → use case call
        ├── schemas.py            Pydantic request/response models
        ├── dependencies.py       how a handler gets a use case
        └── errors.py             domain error → status code, in one table
```

Two files tell you almost everything. `application/ports/driven.py` is the
complete list of external facilities the system relies on. `infrastructure/container.py`
is the complete list of things those facilities actually are.

## One request, end to end

`POST /loans {"member_id": "M-001", "isbn": "978-0-13-235088-4"}`

1. **FastAPI** parses the body into `BorrowBookRequest`. Structural validation
   only: non-empty strings of plausible length. `extra="forbid"`, so a typo in a
   field name is a 422 rather than a silently ignored key.
2. **The route handler** (`routers.py`) builds a `BorrowBookCommand` and calls
   `borrow.execute(...)`. It is three lines and contains no rules.
   The use case arrived through `Depends`, typed as the *port*.
3. **The use case** (`borrow_book.py`) parses `"978-0-13-235088-4"` into an `ISBN`,
   which normalises it to `9780132350884` and verifies the check digit. A bad ISBN
   raises `InvalidISBNError` here, before any lookup happens.
4. It loads the member and the book through repository ports. A `None` becomes
   `MemberNotFoundError` or `BookNotFoundError` — the repository reports absence,
   the use case decides it is a failure.
5. It asks the clock for today, then gathers four counts through the loan
   repository: open loans for this member, overdue loans, copies of this title out,
   whether this member already holds it.
6. It hands those counts to `LoanPolicy.ensure_member_may_borrow`, which raises the
   first rule that fails. **This is the only place the decision is made.**
7. `Loan.open(...)` mints the entity and derives `due_on`. The repository stores it.
   The notification port is called *after* persistence.
8. `loan_view(...)` projects the entity into a `LoanView`, joining in the title and
   computing the accrued fee.
9. Back in the handler, `LoanResponse.from_view(view)` turns that into the wire
   format. `201 Created`.

If a rule refused, no `try/except` runs anywhere on that path. The exception
propagates to the single handler in `errors.py`, which looks up a status code and
emits `{"code", "message", "details"}`:

```json
{
  "code": "loan_limit_reached",
  "message": "This member already holds the maximum number of loans.",
  "details": {"member_id": "M-001", "open_loans": 3, "limit": 3}
}
```

`code` comes straight from the domain exception, so clients branch on a stable
identifier instead of pattern-matching English, and `details` carries the numbers
a UI needs to say something useful.

## Running it

Requires Python 3.12 or newer, for `StrEnum`, `Self` and PEP 604 unions.

```bash
git clone https://github.com/ivanfdz/fastapi-hexagonal-architecture
cd fastapi-hexagonal-architecture

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -c "import sys; print(sys.version)"   # confirm you are on 3.12+
```

That last line is worth running. If your shell opens with a conda `base`
environment active, `python` may still resolve to conda's interpreter even after
`source .venv/bin/activate`, and an older one will fail on `StrEnum`. The package
raises a `RuntimeError` naming the interpreter and the fix rather than letting a
cryptic `ImportError` surface from inside the domain. Calling
`.venv/bin/python` directly always works.

**The demonstration.** One use case, three wirings, no mocks:

```bash
python examples/swap_adapters.py
```

```
=== 1. in-memory repositories, system clock ===
[notification] to ada@example.com: you borrowed 'Clean Code' (loan LOAN-0001), due 2026-10-06.
borrowed   LOAN-0001  'Clean Code'  on 2026-09-22  due 2026-10-06
[notification] to ada@example.com: thanks for returning 'Clean Code' (loan LOAN-0001); no fee owed.
returned   LOAN-0001  on 2026-09-22  0 day(s) late  fee 0.00

=== 2. SQLite repositories, system clock ===
[notification] to ada@example.com: you borrowed 'Clean Code' (loan LOAN-ba81d62298fe), due 2026-10-06.
borrowed   LOAN-ba81d62298fe  'Clean Code'  on 2026-09-22  due 2026-10-06
[notification] to ada@example.com: thanks for returning 'Clean Code' (loan LOAN-ba81d62298fe); no fee owed.
returned   LOAN-ba81d62298fe  on 2026-09-22  0 day(s) late  fee 0.00

=== 3. in-memory repositories, clock frozen 20 days ago ===
borrowed   LOAN-0001  on 2026-09-02  due 2026-09-16
returned   LOAN-0001  on 2026-09-22  6 day(s) late  fee 3.00
notifier recorded:
  - confirmed LOAN-0001 for M-001
  - returned LOAN-0001 with fee 3.00

Same BorrowBook and ReturnBook classes in all three runs. Only the adapters changed.
```

Runs 1 and 2 differ only in the loan id format, which is an adapter decision. Run 3
is the one to sit with: testing "a fee applies after the due date" normally means
waiting six days or patching `date.today`, and here it is a constructor argument,
because the clock is a port. It also swaps the notifier for one that records
instead of printing — three methods, no base class, no import.

**The API.**

```bash
python -m lending                              # in-memory, http://127.0.0.1:8000/docs
LENDING_REPOSITORY=sqlite python -m lending    # same API, persisted to lending.db
```

Equivalent, if you would rather not install the package at all:

```bash
PYTHONPATH=src python -m uvicorn lending.asgi:app --reload
```

**The tests.**

```bash
pytest                                  # 197 tests, ~0.5s, no containers
pytest --cov=lending                    # 94% line coverage
flake8 src tests examples
```

The suite runs straight from a clone whether or not you installed the package:
`pythonpath = ["src"]` is set in `pyproject.toml`.

## The API

The demo catalogue and members are seeded on startup, so every endpoint works
immediately. Member `M-001` and `M-002` are active, `M-003` is suspended.
"Domain-Driven Design" has a single copy, which makes the out-of-stock path easy to
reach.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Reports which repository adapter is wired in. |
| `GET` | `/policy` | The rules in force, read off the domain object. |
| `GET` | `/books` | Catalogue with derived availability. |
| `POST` | `/loans` | Borrow. `201`, or `404` / `409` / `422`. |
| `POST` | `/loans/{loan_id}/return` | Return and settle the fee. |
| `GET` | `/members/{member_id}/loans` | `?include_returned=true` for history. |

```bash
curl -X POST localhost:8000/loans \
  -H 'Content-Type: application/json' \
  -d '{"member_id":"M-001","isbn":"978-0-13-235088-4"}'

# {"loan_id":"LOAN-0001","isbn":"9780132350884","title":"Clean Code",
#  "member_id":"M-001","borrowed_on":"2026-09-22","due_on":"2026-10-06",
#  "returned_on":null,"is_open":true,"days_overdue":0,"late_fee":"0.00"}
```

Note that the hyphenated ISBN came back as thirteen digits. The `ISBN` value object
normalised it, so a lookup by either form finds the same book, in every adapter,
for free.

Things to try that produce a `409` from the domain rather than from this API:
borrow the same title twice, borrow as `M-003`, borrow "Domain-Driven Design" from
two different members, return the same loan twice, or take a fourth concurrent
loan.

**No authentication.** Every endpoint is open. That is deliberate for an example
you are meant to poke at with `curl`, and it is not acceptable in a deployment. The
place to add it is a FastAPI dependency in `driving/http/dependencies.py`: who the
caller is and whether they may act is a concern of the driving adapter, and it
should reach the use case as a value in the command, not as a request object.

## Configuration

Every setting has a working default, so a fresh clone runs with no `.env`.

| Variable | Default | Effect |
| --- | --- | --- |
| `LENDING_REPOSITORY` | `memory` | `memory` or `sqlite`. |
| `LENDING_SQLITE_PATH` | `lending.db` | File used when `repository=sqlite`. |
| `LENDING_NOTIFIER` | `logging` | `logging`, `console` or `null`. |
| `LENDING_SEED_DEMO_DATA` | `true` | Insert the demo catalogue on startup. |
| `LENDING_LOAN_PERIOD_DAYS` | `14` | Lending term. |
| `LENDING_MAX_ACTIVE_LOANS_PER_MEMBER` | `3` | Concurrent loan limit. |
| `LENDING_LATE_FEE_PER_DAY` | `0.50` | Fee rate, parsed as `Decimal`. |

The thresholds are configuration; their *meaning* is not. The environment chooses
the number `3`, and `LoanPolicy` owns what that number does. Set
`LENDING_LOAN_PERIOD_DAYS=7` and no code changes, because the use case asks the
policy for the term instead of hardcoding it.

## What this buys you, with receipts

Architecture claims are cheap. Each of these is checkable in the repo.

**Storage is genuinely swappable.** `container.py` branches on one setting;
`test_http_api.py::TestAdapterIsInterchangeable` fires identical requests at both
backends and asserts identical status codes and payloads, then proves the only
observable difference is the one you wanted — data surviving a restart.

**"Interchangeable" is asserted, not hoped for.**
`test_repository_contract.py` is one suite parametrised over both adapters, so
every assertion runs twice. It catches the real bugs: the overdue boundary
(`as_of > due_on` in Python versus `due_on < ?` in SQL) has a three-case
parametrised test precisely because those two expressions have to mean the same
thing. Dates coming back as ISO strings instead of `date` objects would fail here.
Adding a Postgres adapter means adding one entry to a list; if it passes, it is a
drop-in replacement.

**The dependency rule is executable.** `tests/test_architecture.py` walks the AST
of every module under `domain/` and `application/` and fails on any import of
`fastapi`, `pydantic`, `sqlite3` and friends. One test goes further and imports the
entire core in a subprocess, then inspects `sys.modules` to confirm no web
framework was pulled in transitively. A README can rot; this cannot.

**Tests are fast because the rules have no dependencies.** 197 tests in about half
a second, no database and no container. Not one `unittest.mock` in the suite — when
every collaborator arrives through a constructor, a fake is a small honest class,
and `FixedClock` keeps working through refactors in a way that
`mock.patch("module.date")` does not.

| Layer | Tests | Time | What it needs |
| --- | --- | --- | --- |
| `tests/domain` | 48 | 0.02s | nothing |
| `tests/application` | 40 | 0.02s | in-memory adapters, two fakes |
| `tests/infrastructure` | 78 | 0.39s | tmp SQLite files, `TestClient` |
| `tests/test_architecture` | 31 | — | the AST |

The distribution is not discipline, it is a consequence. When the rules have no
dependencies, testing them requires no setup, so that is where tests accumulate.
The HTTP tests deliberately do not re-test business rules; they check translation,
which is the only thing that layer can get wrong.

## Where Pydantic lives, and why

Pydantic appears in exactly two places, both of them boundaries where untrusted
text arrives: `driving/http/schemas.py` and `config.py`. It does not appear in the
domain or the application.

That is a choice with a real trade-off, so here is the reasoning rather than a
rule. Pydantic is excellent at parsing and at generating OpenAPI, and both of those
are edge concerns. Keeping it at the edge gives one unambiguous answer to "where
does validation happen?":

- **Structural validation** at the edge. Is `isbn` a string of plausible length? Is
  `LENDING_LATE_FEE_PER_DAY` a non-negative number? Pydantic, in `schemas.py` and
  `config.py`.
- **Business validation** in the domain. Is that string a real ISBN-13 with a valid
  check digit? May this member borrow? `ISBN` and `LoanPolicy`.

The second kind must hold for every caller, not just HTTP ones. A CLI, a queue
consumer and a data import script all get the ISBN check digit rule for free
because it lives in the value object rather than in a request schema. Putting
`@field_validator` on `BorrowBookRequest` would mean the rule holds for the API and
silently does not hold anywhere else.

Using Pydantic models as your DTOs throughout is a perfectly common and pragmatic
choice, and plenty of good codebases do it. The cost is that the core stops being
importable without the dependency, the two kinds of validation start blurring, and
`model_config` decisions made for JSON serialisation begin leaking into objects the
domain passes around. This repo takes the stricter route because it is a teaching
example and the seams should be visible. `LoanResponse.from_view` is the single
point of contact between the two shapes, so collapsing them later is a small,
localised change.

One detail worth stealing regardless: money crosses the wire as a fixed-precision
string, never a JSON number.

```python
MoneyString = Annotated[
    Decimal,
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str, when_used="json"),
]
```

A float round-trip is capable of turning `1.15` into `1.1499999999999999`, and a
fee is not the place to discover that.

## Design decisions

**`typing.Protocol` for ports, not `abc.ABC`.** Structural typing means an adapter
satisfies a port by having the right methods — no import, no inheritance — so the
dependency really only points one way, even for third-party objects you do not
control. Test doubles become ordinary classes with no base to inherit. The cost is
that mistakes surface in a type checker rather than at import time, which is a good
trade if mypy or pyright runs in CI.

**Hand-rolled dependency injection.** `container.py` is explicit constructor calls:
no DI library, no decorators, no runtime graph resolution. For a graph this size
that is a feature, because the wiring is a function you can read top to bottom and
step through in a debugger. Reach for a framework when the graph genuinely outgrows
a screen, not before.

**Keyword-only constructor arguments.** `BorrowBook` takes six collaborators of
similar shape. Positional arguments would be easy to mis-order, the composition
root is the only caller, and the verbosity costs nothing.

**The port shape reflects the application, not the technology.**
`NotificationPort` exposes `loan_confirmed` and `loan_returned`, not
`send_email(subject, body)`. With the first shape, swapping email for a push
notification or a Kafka topic is an adapter change. With the second, the templates
have already leaked into the use cases.

**Counting methods on `LoanRepository`.** `count_open_for_member` exists so that
the SQLite adapter can answer with `SELECT COUNT(*)` while the in-memory one uses a
generator expression. `list_for_member` plus a Python-side filter would have
dragged the whole table into memory to answer one question.

**Identity is minted before persistence.** `next_identity()` lets the domain build
a fully valid `Loan` in one step, instead of the half-built "saved but not yet
identified" state that autoincrement columns impose. The in-memory adapter returns
`LOAN-0001`, SQLite returns a UUID suffix, and the contract test only requires
uniqueness — identity generation really is an infrastructure decision.

**Rehydration bypasses the named constructor.** `_to_loan` in the SQLite adapter
calls `Loan(...)` rather than `Loan.open(...)`. A named constructor enforces the
rules for *new* loans; reproducing a stored row must reproduce it exactly, including
a due date that a since-changed policy would now compute differently.

**Stdlib `sqlite3`, no ORM.** So the mapping is visible instead of generated.
`_to_loan` and `_to_row` are the only functions in the codebase that know a loan has
columns. A production adapter would probably use SQLAlchemy and Alembic; that is a
change confined to one file, which is the point.

## Extending it

**Add a Postgres adapter.** Write `infrastructure/driven/postgres.py` with three
classes matching the repository protocols. Add one entry to the `params` list in
`test_repository_contract.py` and run the suite — it will tell you whether it is
truly a drop-in replacement. Add a branch to `_build_repositories` in
`container.py`. Nothing in `domain/` or `application/` is touched, and the HTTP
tests keep passing unchanged.

**Add a CLI adapter.** Create `infrastructure/driving/cli.py`, build a container,
parse `argv` into a `BorrowBookCommand`, call the use case, print the view, and map
domain errors to exit codes instead of status codes. Every rule applies
automatically, because none of them live in the HTTP layer.

**Add a use case.** Say "renew a loan". Put the rule on the entity or the policy —
probably `LoanPolicy.ensure_renewable`, since it needs to know whether anyone is
waiting. Add `RenewLoan` in `application/use_cases/`, add its contract to
`ports/driving.py`, wire it in `container.py`, add a route. If you find yourself
adding a repository method, that is the port growing from a real need, which is the
right reason.

**Add a rule.** Define the exception in `domain/errors.py`, enforce it in
`LoanPolicy`, add a row to `_STATUS_BY_ERROR` in `driving/http/errors.py`. Forget
the last step and the fallback still returns a well-formed error with the right
code, just a coarser status.

## What it deliberately leaves out

Being honest about the edges, since a small example that pretends to be complete is
worse than one that says where it stops.

- **Transactions and a unit of work.** Each repository call commits on its own.
  `BorrowBook` writes one row, so it happens to be atomic, but a use case touching
  two aggregates would need a `UnitOfWork` port wrapping the operation. That is the
  first thing to add for real work.
- **Concurrency.** Two simultaneous requests for the last copy can both pass the
  availability check. The fix is storage-level: a unique constraint, `SELECT FOR
  UPDATE`, or optimistic locking on a version column. All three are adapter
  concerns, which is convenient, but the port would need to surface the conflict.
- **Authentication and authorisation.** See the API section.
- **Domain events.** `BorrowBook` calls the notification port inline. A real system
  would collect events on the aggregate and publish them through an outbox after
  commit. The port shape would not change.
- **Pagination.** `GET /books` and the loans endpoint return everything. The list
  response is an envelope rather than a bare array specifically so paging metadata
  can be added without changing the JSON type.
- **Aggregate boundaries.** `Book`, `Member` and `Loan` are treated as three small
  aggregates with no transactional consistency between them. In strict DDD terms,
  "copies available" is a `Book` invariant that `Loan` writes affect, which deserves
  more care than an example needs.

## License

MIT. See [LICENSE](LICENSE).
