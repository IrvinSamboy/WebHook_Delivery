# 0002 — PostgreSQL is the source of truth; the queue only carries ids

**Status:** accepted

## Context

A webhook service must never lose an event it accepted, and it has to explain later what
happened to it (which attempts, which responses). Redis can lose data on restart and Celery
messages disappear once acknowledged.

## Decision

- Accepting a message writes, in **one transaction**, the `messages` row and one `deliveries`
  row per subscribed endpoint (fan-out). The API returns `202` only after the commit.
- The Celery task is enqueued **after** the commit and carries only the delivery id. Its
  arguments are never the source of any decision: the worker re-reads the row.
- Every attempt is stored in `attempts` (status, duration, truncated response body, error).
- A delivery is a small state machine: `queued → sending → succeeded | pending | failed`,
  and the scheduler moves `pending → queued` when a retry is due. Only the domain entity
  changes its state.
- The guarantee is **at-least-once**. Each request carries the message id in `webhook-id`
  so receivers can deduplicate.

## Alternatives considered

- **Redis/Celery as the store of pending work.** Loses work on a Redis flush and offers no
  history to query.
- **Transactional outbox with a relay process.** Solves the same "enqueue after commit"
  problem with lower recovery latency, but here the reaper and the scheduler (ADRs 0005 and
  0006) already recover a delivery whose task never reached the queue, without another
  moving part.
- **Exactly-once delivery.** Impossible over HTTP: if the receiver processes the request and
  the response is lost, the sender cannot know. Pretending otherwise just hides duplicates.

## Consequences

- Deliveries are created directly as `queued`. If the process dies between commit and
  enqueue (or Redis loses the task), the delivery stays `queued`; after 5 minutes the reaper
  returns it to `pending` and the scheduler sends it. Nothing is lost; it is only late.
- Receivers must be idempotent on `webhook-id`. The README says so explicitly.
- No ordering guarantee between messages: retries and parallel workers reorder them.
