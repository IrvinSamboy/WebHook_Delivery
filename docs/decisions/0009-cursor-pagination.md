# 0009 — Keyset (cursor) pagination on `(created_at, id)`

**Status:** accepted

## Context

`GET /v1/messages` lists messages newest first while new messages keep arriving. Clients
page through it to reconcile or to find a specific event.

## Decision

- Order by `(created_at DESC, id DESC)` and page with a tuple comparison:
  `WHERE (created_at, id) < (:created_at, :id)`.
- The cursor is the last row's `(created_at, id)` as base64url JSON. It is opaque to clients
  and rejected if malformed or without a timezone.
- Fetch `limit + 1` rows to know whether there is a next page without a `COUNT`.
- Index `(app_id, created_at, id)` serves both the filter and the order; it was created with
  `CREATE INDEX CONCURRENTLY` so the migration does not block writes.

## Alternatives considered

- **`OFFSET`/`LIMIT`.** New rows shift every page: in a test with 230 messages, inserting
  while paging returned 5 duplicates. It also gets slower with depth because skipped rows
  are still read.
- **Cursor on `created_at` alone.** Many messages share a timestamp (a batch in one
  transaction gets the same `now()`): the same test skipped 23 messages. `id` breaks ties.

## Consequences

- Stable pages and constant cost per page, however deep.
- No "jump to page N" and no total count — neither is useful for an event log.
