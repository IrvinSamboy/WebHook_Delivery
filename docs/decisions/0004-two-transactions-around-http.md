# 0004 — Two short transactions with the HTTP call outside both

**Status:** accepted

## Context

Sending a webhook means: lock the delivery, call the receiver, record the result. The
receiver may take up to 20 seconds (5 s connect + 15 s read). Holding a database transaction
and a row lock for that long ties up connections and blocks every other writer of the row.

## Decision

`DeliverMessage` runs in three steps:

1. **Transaction 1:** `SELECT … FOR UPDATE` the delivery; if it is not `queued`, do nothing
   (a duplicate task). Otherwise move it to `sending`, take a new lease (ADR 0006) and commit.
2. **No transaction:** sign and send the HTTP request.
3. **Transaction 2:** lock the row again, read the *fresh* `attempt_count`, store the attempt
   and decide the next state (`succeeded`, `pending` with `next_attempt_at`, or `failed`).

## Alternatives considered

- **One transaction around everything.** Simplest code; a slow receiver then holds a
  connection and a lock for 20 s. With a pool of a few dozen connections, a handful of slow
  receivers would stall the whole service.
- **Optimistic concurrency (version column) instead of row locks.** Avoids locks but turns
  every conflict into a retry loop; the locks here are held for milliseconds.

## Consequences

- Connections and locks are held for milliseconds regardless of how slow receivers are.
- A worker can die between steps 1 and 3, leaving a delivery in `sending` forever. That is
  the job of the reaper (ADR 0006).
- Because state may change between steps 1 and 3, step 3 must re-read the row and must not
  trust what it read in step 1.
