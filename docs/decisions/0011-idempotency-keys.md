# 0011 — `Idempotency-Key` on message creation, stored without expiry

**Status:** accepted

## Context

A customer calls `POST /v1/messages`, the response is lost to a timeout, and they retry.
Without protection the event is created — and delivered to every endpoint — twice.

## Decision

- Optional header `Idempotency-Key` (printable ASCII, max 255 characters).
- The key is stored on the message with `request_hash`: SHA-256 of the event type and the
  payload serialised with sorted keys, so key order does not matter.
- A unique partial index on `(app_id, idempotency_key) WHERE idempotency_key IS NOT NULL`
  makes the database the arbiter.
- On a repeated key:
  - same content → the original message is returned with `Idempotent-Replayed: true`;
  - different content → `422`, because the key was reused for a different request.
- **Races:** two concurrent requests with the same key both miss the lookup; the loser's
  `INSERT` violates the index, the repository translates the `IntegrityError` into
  `DuplicateIdempotencyKey`, and the use case re-reads and returns the winner. Verified with
  20 concurrent requests → 1 message.
- Keys **never expire**.

## Alternatives considered

- **Store keys in Redis with a TTL (24 h, like Stripe).** Fast, but a second source of truth
  that can be lost, and the check would not be atomic with the insert.
- **Expire keys after N days.** Needs a cleanup job and a column index for it; the key is a
  few bytes on a row we keep anyway.
- **Lock on the key (`pg_advisory_xact_lock`) before inserting.** Also correct, but the
  unique index already gives the same guarantee without extra round trips.

## Consequences

- A retry days later is still deduplicated.
- The unique index adds a small cost to every insert with a key.
- If message retention is added later, keys disappear with their messages — which is the
  natural expiry.
