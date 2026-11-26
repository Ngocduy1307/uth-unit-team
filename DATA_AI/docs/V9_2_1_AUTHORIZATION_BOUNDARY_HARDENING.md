# V9.2.1 Authorization Boundary Hardening

## Scope

This increment hardens the trusted-Backend assertion boundary used by DATA-AI.
It does not replace Spring Boot authentication, authoritative permission checks,
staff assignment checks, or network-level service authentication.

## Changes

- Added `app/security.py` as the shared normalization and validation layer for
  trusted actor, role, and bank assertions.
- Case-level authorization now uses the shared parser and tenant-scope guard.
- Staff-context parsing now rejects blank, oversized, or control-character
  identity assertions rather than silently truncating them.
- Role claims are normalized consistently across comma and semicolon separators.
- Cross-bank resource access remains a non-disclosing 404 for non-platform roles.
- Added regression tests for missing identity/bank context, oversized values,
  control characters, absent/irrelevant roles, same-bank access, cross-bank
  access, and explicit SYSTEM_ADMIN behavior.

## Security boundary and deployment requirements

`X-Actor-Id`, `X-Actor-Roles`, and `X-Bank-Id` are assertions, not credentials.
They are trustworthy only when all of the following are true:

1. DATA-AI is not reachable from browser clients or the public Internet.
2. Network policy/security groups allow only the trusted Backend workload.
3. The internal service token is stored server-side, rotated, and never sent
   to browser code.
4. Backend derives actor, roles, and bank scope from its authenticated
   server-side principal and overwrites inbound values; it must not forward
   browser-supplied identity headers.
5. Production runs with `APP_ENV` outside `development`/`test` and a configured
   `INTERNAL_SERVICE_TOKEN`.

A shared service token alone does not cryptographically bind the actor headers
to an individual request. V9.2.2 supplements the token with request-bound
HMAC assertions, issuer/audience binding, timestamp validation and a
PostgreSQL-backed one-time nonce registry. See
`V9_2_2_SIGNED_SERVICE_ASSERTIONS.md`.

## Deliberate non-changes

- Spring Boot remains the public authentication and authorization authority.
- Customer ownership, staff assignment, Maker/Checker separation, and
  fine-grained permission checks must be enforced by Backend.
- V9.2.1 itself introduced no database migration. V9.2.2 adds migration V10
  for durable assertion replay protection.
- SYSTEM_ADMIN cross-bank access remains possible only when that explicit
  trusted role is present; privileged data access must be audited by Backend
  and DATA-AI before production pilot.

## Verification

Run:

```bash
python -m pytest -q
```

Expected result for the V9.2.1 source snapshot: **57 passed**. The current V9.2.2 package adds signed-assertion coverage; see its release note for the current total.

The test suite validates application-level regression behavior. It does not
prove production network isolation, secret rotation, TLS configuration,
PostgreSQL row-level security, load behavior, or Backend identity-header
integrity. Those require deployment integration tests.
