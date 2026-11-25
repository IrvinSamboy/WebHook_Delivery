# 0008 — Encrypted endpoint secrets, hashed API keys, rotation with grace

**Status:** accepted

## Context

There are two kinds of secrets with different needs:

- **API keys** authenticate our customers. We only need to *check* them.
- **Endpoint signing secrets** are used to *compute* HMACs on every send, so we need the
  plaintext back.

Customers also need to replace a signing secret (leaked, or routine rotation) without
dropping webhooks while they update their receiver.

## Decision

- **API keys:** `whr_<12 hex>.<random>`. The prefix is stored in clear and indexed to find
  the row; the full key is stored as SHA-256 and compared with `hmac.compare_digest`. Shown
  once at creation.
- **Endpoint secrets:** encrypted with Fernet (AES-128-CBC + HMAC) using `ENCRYPTION_KEY`.
  They are returned only on creation and rotation; reads never select the column.
- **Rotation:** `POST /v1/endpoints/{id}/rotate-secret` generates a new secret and keeps the
  previous one for **24 hours**. During that window every request carries two signatures
  (new first), so receivers still holding the old secret keep verifying. With
  `?expire_previous=true` the old secret is dropped immediately (for leaks).
- A database `CHECK` ensures the previous secret and its expiry are both set or both null.

## Alternatives considered

- **bcrypt/argon2 for API keys.** Designed for low-entropy passwords; our keys have 256 bits
  of randomness, so a fast hash is safe and keeps authentication cheap on every request.
- **Plaintext signing secrets.** A database dump would let anyone forge webhooks.
- **A KMS/Vault.** Right for a larger deployment; out of scope for a single-node project. The
  cipher sits behind one class, so swapping it is contained.
- **Rotation without overlap.** Every receiver would fail verification until it deploys the
  new secret.

## Consequences

- Losing `ENCRYPTION_KEY` makes every endpoint secret unrecoverable; endpoints would need
  new secrets. Rotating the key itself (re-encrypting) is not implemented.
- During a grace period receivers see two signatures; standard libraries accept a request if
  any of them matches.
