# Architecture Decision Records

Each record captures one decision: the context, what was chosen, what was rejected and why,
and the consequences we accept. Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

| #    | Decision                                                                 |
|------|--------------------------------------------------------------------------|
| [0001](0001-layered-architecture-sync-stack.md) | Layered architecture with ports and adapters on a synchronous stack |
| [0002](0002-postgres-source-of-truth.md)        | PostgreSQL is the source of truth; the queue only carries ids       |
| [0003](0003-standard-webhooks-signing.md)       | Sign payloads following the Standard Webhooks specification         |
| [0004](0004-two-transactions-around-http.md)    | Two short transactions with the HTTP call outside both              |
| [0005](0005-retry-scheduler-in-postgres.md)     | Retries are scheduled in PostgreSQL, not with Celery ETAs           |
| [0006](0006-reaper-and-fencing-token.md)        | A reaper rescues stuck deliveries; a fencing token stops zombies    |
| [0007](0007-retry-policy.md)                    | Exponential backoff with jitter, 10 attempts, honouring Retry-After |
| [0008](0008-secrets-at-rest-and-rotation.md)    | Encrypted endpoint secrets, hashed API keys, rotation with grace    |
| [0009](0009-cursor-pagination.md)               | Keyset (cursor) pagination on `(created_at, id)`                    |
| [0010](0010-ssrf-protection.md)                 | SSRF protection at registration and at every send                   |
| [0011](0011-idempotency-keys.md)                | `Idempotency-Key` on message creation, stored without expiry        |
| [0012](0012-rate-limiting.md)                   | Fixed-window rate limit in Redis that fails open                    |
| [0013](0013-testing-strategy.md)                | Fakes for unit tests, a real database for integration, sabotage     |
