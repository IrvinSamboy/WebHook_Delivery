# 0007 — Exponential backoff with jitter, 10 attempts, honouring Retry-After

**Status:** accepted

## Context

Receivers fail for minutes (deploys) or hours (outages). Retrying too fast hammers a service
that is already down; retrying too slowly delays recovery. When many deliveries fail at the
same moment, retrying them all at the same instant creates a thundering herd.

## Decision

- **Success** is a `2xx` response. Anything else — `3xx` (redirects are not followed),
  `4xx`, `5xx`, timeouts and connection errors — is a failed attempt.
- **Backoff:** `base × 2^(attempt-1)`, multiplied by a random factor in `[0.8, 1.2]`.
  With the production base of 30 s the waits are 30 s, 1, 2, 4, 8, 16, 32, 64 and 128 minutes:
  about 4 h 15 min across 10 attempts. After the 10th failure the delivery is `failed`.
- **Retry-After:** if the receiver sends it (seconds or HTTP date), we wait
  `max(backoff, Retry-After)`, capped at 1 hour so a receiver cannot freeze a delivery.
- A `failed` delivery can be retried by hand with `POST /v1/deliveries/{id}/retry`; that
  attempt is recorded with `trigger = manual`.
- `BACKOFF_BASE_SECONDS` is configurable (2 s in development to watch the whole cycle in
  ~17 minutes).

## Alternatives considered

- **Treat 4xx as permanent and stop.** A `404` during a receiver's deploy or a `401` from a
  misconfigured secret is often temporary; stopping would lose events that a later attempt
  would deliver. Manual retry covers the rest.
- **Fixed interval.** Either too aggressive during long outages or too slow for short ones.
- **Unbounded retries.** Keeps work alive forever for endpoints that are gone.

## Consequences

- Recovery after a short outage is fast; long outages cost at most 10 attempts per delivery.
- Some attempts are wasted on permanent errors (`410 Gone`). Disabling endpoints
  automatically after repeated failures is listed as future work.
