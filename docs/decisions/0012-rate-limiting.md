# 0012 — Fixed-window rate limit in Redis that fails open

**Status:** accepted

## Context

One customer sending a flood of messages creates rows, tasks and outbound requests that
slow everyone else down. We need a per-application limit on message creation.

## Decision

- **Fixed window of one minute** per application: key `ratelimit:<app_id>:<minute>`,
  `INCR` then `EXPIRE … NX` in one pipeline. Default `RATE_LIMIT_PER_MINUTE=600`.
- Applied only to `POST /v1/messages` — reads are cheap, and creating messages is what
  generates work.
- Responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`;
  a rejected request gets `429` with `Retry-After`.
- **Fails open:** if Redis is unreachable (client timeouts of 250 ms), the request is allowed
  and a warning is logged. Measured: 40 ms extra per request with Redis stopped.

## Alternatives considered

- **Sliding window / token bucket.** Smoother, and it avoids a burst of up to 2× the limit
  across a window boundary. It needs a Lua script or a sorted set per app. The fixed window is
  enough for abuse protection; this is documented as a known limit.
- **Fail closed.** A Redis outage would stop all customers from sending, turning a
  non-critical dependency into a critical one.
- **Limit in PostgreSQL.** Correct, but adds a write on the hottest path to the database we
  most want to protect.

## Consequences

- A client can send up to 2× the limit in a short burst around a minute boundary.
- During a Redis outage there is no limit at all.
- In the load test the limit is raised so it measures the API, not the limiter.
