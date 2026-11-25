# 0001 — Layered architecture with ports and adapters on a synchronous stack

**Status:** accepted

## Context

The service has a small core (when to send, how to sign, when to retry) and a lot of
plumbing around it (HTTP API, PostgreSQL, Redis, Celery, outbound HTTP). The core rules are
where the bugs that matter live — double deliveries, lost retries — so they must be testable
in milliseconds, without containers.

## Decision

Four layers, with dependencies pointing inwards only:

- **domain** — entities and rules, standard library only (`Delivery`, `RetryPolicy`, signing,
  `is_public_ip`).
- **application** — one use case per operation (`CreateMessage`, `DeliverMessage`, …) and the
  *ports* they need, declared as `typing.Protocol` (`UnitOfWork`, `HttpSender`, `TaskQueue`,
  `DestinationGuard`, `RateLimiter`, `Clock`).
- **infrastructure** — adapters implementing the ports (SQLAlchemy, httpx2, Celery, Redis).
- **entrypoints** — FastAPI routers, Celery tasks and a CLI. They translate input, call a use
  case and translate the result.

`container.py` is the only composition root: it is the one place that knows which adapter
implements which port. Reads that only feed the API (listings, stats) go straight to SQL in
`queries.py` instead of going through repositories and entities.

The stack is **synchronous**: FastAPI with sync handlers, SQLAlchemy 2 sync sessions, Celery
prefork workers.

## Alternatives considered

- **Framework-shaped code (models and logic inside routers).** Faster to start, but every
  test of the retry logic would need a database and an HTTP client.
- **Async stack (async SQLAlchemy, async httpx).** The API spends its time waiting on
  PostgreSQL, and the slow part — calling receivers — already runs in separate worker
  processes. Async would add colouring of every function and subtler transaction bugs for no
  measurable gain at this scale (see the load test in the README).
- **Repositories for reads too.** Listing pages would load full entities only to throw most
  fields away; projections in plain SQL are simpler and faster.

## Consequences

- 390+ unit tests run in about 3 seconds against in-memory fakes.
- Swapping an adapter (e.g. another queue) touches one module and `container.py`.
- There is more code than a single-file FastAPI app: ports, fakes and mapping functions.
- `mypy` checks that every adapter satisfies its port (the `SqlAlchemyUnitOfWork` attributes
  are declared with the port types).
