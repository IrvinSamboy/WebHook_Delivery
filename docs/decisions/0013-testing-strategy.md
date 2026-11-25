# 0013 — Fakes for unit tests, a real database for integration, sabotage

**Status:** accepted

## Context

The bugs that hurt in this service live in two places: the rules (state machine, retry
policy, signing, lease handling) and the database behaviour the rules rely on (locks,
`SKIP LOCKED`, unique indexes, constraints, migrations). Mocks cannot reproduce the second
group.

## Decision

- **Unit tests** (`tests/unit`, ~390 tests, ~3 s): use cases run against in-memory fakes of
  every port (`tests/fakes.py`). Fakes return copies so a test cannot pass by mutating shared
  objects. The API is tested through FastAPI's `TestClient` with the container overridden.
- **Integration tests** (`tests/integration`, marker `integration`, excluded by default): run
  against a real PostgreSQL in a separate database `<name>_test`, created and migrated from
  scratch for every run (which also tests the migrations), with tables truncated after each
  test. They cover repositories, constraints, `SKIP LOCKED`, the idempotency race, the
  zombie-worker interleaving with two threads, migration round-trips and drift between models
  and migrations, and the Redis rate limiter (on Redis DB 15).
- **Sabotage checks:** after writing a test, break the code it protects (remove `SKIP LOCKED`,
  ignore the lease, drop a constraint) and confirm the test fails. Tests that kept passing
  were rewritten.
- **CI** runs lint (`ruff`), type checks (`mypy`), both suites with PostgreSQL and Redis as
  service containers, and a Docker build on every push.

## Alternatives considered

- **Testcontainers.** Starts a fresh PostgreSQL per run. Docker Compose already provides one
  locally and GitHub Actions provides service containers, so deriving a `_test` database from
  `DATABASE_URL` gives the same isolation with no extra dependency.
- **SQLite for integration tests.** No `SKIP LOCKED`, no partial indexes, different locking:
  the tests would pass against the wrong database.
- **Mocking SQLAlchemy.** Tests the calls, not the behaviour.

## Consequences

- The fast suite gives feedback in seconds; the slow one proves the SQL actually works.
- Fakes must be kept in sync with the real adapters; integration tests catch drift.
- The `_test` fixture refuses to drop any database whose name does not end in `_test`.
