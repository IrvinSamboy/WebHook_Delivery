# 0010 — SSRF protection at registration and at every send

**Status:** accepted

## Context

Customers choose the URLs we POST to. Without checks, `http://169.254.169.254/` (cloud
metadata), `http://localhost:5432/` or `http://10.0.0.5/admin` turn the service into a proxy
into our own network. A hostname that resolves to a public IP today can resolve to a private
one tomorrow (DNS rebinding).

## Decision

- `is_public_ip` uses an **allowlist**: `ipaddress.is_global` and not multicast. IPv4-mapped
  IPv6 addresses (`::ffff:10.0.0.1`) are judged by the IPv4 inside; IPv6 zone ids are stripped.
- `DnsDestinationGuard` resolves the host and requires **every** resolved address to be
  public — an attacker controlling DNS could otherwise mix one public and one private record.
- The check runs **twice**: when an endpoint is registered or its URL changes (`422` with a
  reason, without revealing the resolved IP), and again **before every send**. A blocked
  send is recorded as an attempt with error `destination_not_allowed`.
- Redirects are never followed, and proxy environment variables are ignored.
- `ALLOW_PRIVATE_URLS=true` disables the check; it exists only so the development receiver
  (`http://receiver:9000`) works. Default is `false`.

## Alternatives considered

- **Denylist of private ranges.** Easy to get wrong (IPv6, `0.0.0.0`, CGNAT, new ranges);
  an allowlist fails closed.
- **Check at registration only.** Defeated by DNS rebinding.
- **Pin the resolved IP into the connection.** Closes the remaining gap (see below) but
  requires a custom transport that connects to an IP while keeping SNI and the `Host` header.
- **An egress proxy (e.g. Smokescreen).** The strongest option in production; it is
  infrastructure outside this repository.

## Consequences

- Known gap: between our DNS check and httpx's own resolution there is a window of
  milliseconds (TOCTOU). Closing it needs IP pinning or an egress proxy, listed as future work.
- Every send pays one DNS lookup; the OS resolver cache keeps it cheap.
