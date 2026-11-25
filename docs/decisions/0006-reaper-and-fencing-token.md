# 0006 — A reaper rescues stuck deliveries; a fencing token stops zombies

**Status:** accepted

## Context

Because of ADR 0004, a worker that dies (OOM kill, node loss) between its two transactions
leaves the delivery in `sending` forever. A worker can also be *paused* rather than dead —
long GC, a frozen VM, a network partition — and wake up minutes later believing it still
owns the delivery.

## Decision

- **Reaper:** Celery Beat publishes `recover_stuck` every 60 s. It moves deliveries that have
  been in `queued` or `sending` for more than 5 minutes back to `pending`, so the scheduler
  picks them up again. 5 minutes is far above the 20 s HTTP timeout.
- **Fencing token:** the `lease_id` column. `start_sending()` writes a fresh UUID and the
  worker keeps it. The reaper sets `lease_id = NULL`. In its second transaction the worker
  passes its token to `record_attempt(lease_id, …)`:
  - the attempt is **always recorded** and `attempt_count` always increments — the request
    did happen and the history must show it;
  - the delivery **state** changes only if it is still `sending` with the same lease. A
    zombie whose lease was revoked logs a warning and changes nothing.
- The attempt number is taken from the row re-read under lock, never from the copy read in
  the first transaction, so a zombie and its replacement never collide on
  `(delivery_id, number)`.

## Alternatives considered

- **Rely on Celery `acks_late` redelivery.** Covers a crashed worker but not a paused one, and
  the redelivered task finds the row in `sending` and (correctly) refuses to send.
- **Heartbeats from the worker.** More precise detection, but another write per in-flight
  delivery per few seconds and more code. 5 minutes of delay in a rare failure is acceptable.
- **Distributed locks in Redis.** Redis locks without fencing have the same zombie problem.

## Consequences

- No delivery stays stuck for more than ~6 minutes.
- A paused worker can still deliver a duplicate (at-least-once, ADR 0002), but it cannot
  overwrite the outcome decided by its replacement. This interleaving is covered by an
  integration test with two threads.
- Known cost: under a backlog older than 5 minutes (very slow receivers and high volume),
  the reaper re-enqueues deliveries that are still waiting in Redis. The extra tasks find the
  delivery in another state and do nothing, but they add queue traffic.
