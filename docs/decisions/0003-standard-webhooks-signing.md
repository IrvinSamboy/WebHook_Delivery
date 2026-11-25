# 0003 — Sign payloads following the Standard Webhooks specification

**Status:** accepted

## Context

Receivers need to verify that a request really comes from us and was not replayed. Every
provider invents its own header names and signing string, which forces each receiver to
write custom verification code.

## Decision

Follow [Standard Webhooks](https://www.standardwebhooks.com/):

- Headers `webhook-id` (the message id), `webhook-timestamp` (Unix seconds of **this
  attempt**, not of creation) and `webhook-signature`.
- Signed content: `"{webhook-id}.{webhook-timestamp}.{body}"`, HMAC-SHA256, base64, prefixed
  with `v1,`.
- Secrets have the form `whsec_<base64 of 32 random bytes>`, one per endpoint.
- `webhook-signature` may carry several space-separated signatures; this is what makes
  secret rotation possible without downtime (ADR 0008).
- The body is serialised once and the exact bytes signed are the bytes sent.

## Alternatives considered

- **A custom scheme (`X-Signature: sha256=…`).** Works, but receivers cannot reuse the
  official libraries that exist for many languages.
- **Asymmetric signatures (Ed25519).** Lets receivers verify without holding a secret, but
  key distribution is more work for them and the spec's symmetric mode is what most
  consumers expect.

## Consequences

- Receivers can verify with the official `standardwebhooks` libraries, and reject requests
  whose timestamp is more than 5 minutes off to stop replays.
- The timestamp changes on each retry, so the signature changes too; `webhook-id` does not,
  which is what receivers deduplicate on.
- We must keep the secret in a recoverable form to sign with it (ADR 0008).
