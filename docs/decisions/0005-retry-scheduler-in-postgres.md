# 0005 — Retries are scheduled in PostgreSQL, not with Celery ETAs

**Status:** accepted

## Context

A failed delivery must be retried later — up to about four hours later. Celery can delay a
task with `countdown`/`eta`, but with the Redis broker delayed tasks are held by the worker
that reserved them, are redelivered after `visibility_timeout`, and are invisible to the
database: you cannot ask "what is due in the next minute?" or change a pending retry when the
customer fixes their URL.

## Decision

- A failed attempt sets the delivery back to `pending` with `next_attempt_at`.
- Celery Beat publishes `schedule_due` every 5 seconds. It claims due deliveries in batches
  of 100 and enqueues them:

  ```sql
  WITH due AS MATERIALIZED (
      SELECT id FROM deliveries
      WHERE status = 'pending' AND next_attempt_at <= :now
      ORDER BY next_attempt_at LIMIT :limit
      FOR UPDATE SKIP LOCKED
  )
  UPDATE deliveries SET status = 'queued', updated_at = now()
  FROM due WHERE deliveries.id = due.id
  RETURNING deliveries.id
  ```

- `SKIP LOCKED` lets several schedulers run at once without claiming the same row or waiting
  on each other.
- The CTE is `MATERIALIZED` so PostgreSQL evaluates the `LIMIT` once. With
  `WHERE id IN (subquery)` the planner may re-run the subquery and claim more rows than the
  limit (observed: 165 rows with `LIMIT 100`).
- A partial index on `(next_attempt_at) WHERE status = 'pending'` keeps the scan small; the
  reaper has its own on `(updated_at) WHERE status IN ('queued', 'sending')`.
- Beat ticks have `expires` equal to their interval, so busy workers do not accumulate
  stale ticks.

## Alternatives considered

- **Celery `countdown`/`eta`.** No visibility, no way to update pending retries, memory
  pressure on workers with long delays.
- **A dedicated scheduler (cron, APScheduler) outside Celery.** One more process to run; Beat
  is already part of the stack.
- **Redis sorted set as a delay queue.** Fast, but duplicates the state that already lives in
  PostgreSQL and can be lost.

## Consequences

- Retries survive restarts of every component except PostgreSQL.
- Changing an endpoint's URL immediately affects its pending retries.
- Up to 5 seconds of extra latency on retries (not on first attempts, which are enqueued
  directly).
- Beat must run as a single replica; two would publish every tick twice (harmless thanks to
  `SKIP LOCKED`, but wasteful).
