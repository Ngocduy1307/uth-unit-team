# V9.2.2 — Signed Backend-to-DATA-AI assertions

## What this increment changes

- Adds `X-Service-Assertion` to every protected `/api/*` operation.
- Uses HMAC-SHA256 with key IDs so old and new keys can overlap during rotation.
- Binds the signature to HTTP method, raw path, raw query, SHA-256 of the exact request body, timestamp, nonce, actor ID, roles and bank ID.
- Enforces a configurable clock-skew window (default 120 seconds).
- Stores consumed nonces in PostgreSQL with a primary key, so concurrent replay attempts cannot both pass across API workers.
- Keeps `X-Internal-Service-Token` as a second service-level gate during this rollout.
- In production (`APP_ENV` other than `development`/`test`), signed assertions and the internal service token are mandatory. Missing key configuration fails closed with 503.
- Local development/test retains the prior compatibility path when no assertion keys are configured. Do not use that mode for a pilot or production.

## Required migration

Apply Flyway migration `V10__signed_service_assertion_replay_protection.sql` before deploying the application with assertion keys enabled. The application intentionally does not create database tables at startup.

## Configuration

Set the following on the DATA-AI service only:

```dotenv
APP_ENV=production
INTERNAL_SERVICE_TOKEN=<separate-long-random-service-token>
SERVICE_ASSERTION_KEYS={"backend-2026-01":"<at-least-32-random-bytes>"}
SERVICE_ASSERTION_MAX_SKEW_SECONDS=120
SERVICE_ASSERTION_ISSUER=spring-boot-backend
SERVICE_ASSERTION_AUDIENCE=data-ai
MAX_SIGNED_REQUEST_MB=24
```

Use a secret manager, not a committed `.env`, for real deployments. Key values are UTF-8 strings of at least 32 bytes. Key IDs match `[A-Za-z0-9_-]{1,80}`. The signing key must be different from `INTERNAL_SERVICE_TOKEN`.

## Exact signing contract

The canonical UTF-8 payload is the following fields joined with a single LF (`\\n`), without a trailing LF:

1. `DATA-AI-SERVICE-ASSERTION-V1`
2. configured issuer (`SERVICE_ASSERTION_ISSUER`)
3. configured audience (`SERVICE_ASSERTION_AUDIENCE`)
4. HTTP method uppercased
5. raw URL path
6. raw query string, or empty string
7. lowercase hex SHA-256 of the exact raw HTTP body (empty body hashes as SHA-256 of zero bytes)
8. Unix timestamp in whole seconds
9. one-time nonce (24 random bytes, Base64URL without padding recommended)
10. exact `X-Actor-Id` header value
11. exact `X-Actor-Roles` header value, or empty string
12. exact `X-Bank-Id` header value

`signature = lowercase_hex(HMAC_SHA256(UTF8(secret), canonical_payload))`

Header format: `v1.<key-id>.<timestamp>.<nonce>.<signature>`. Issuer and audience are cryptographically bound into the canonical payload and checked against DATA-AI configuration.
The body must be signed after JSON or multipart serialization. DATA-AI caps the body read for signature verification at `MAX_SIGNED_REQUEST_MB` (default 24 MiB); set this above the upload limit plus multipart overhead when changing `MAX_FILE_MB`. Do not sign a DTO and then let an HTTP client serialize it differently. The Spring examples include a `ClientHttpRequestInterceptor` that signs the final request bytes. The path and query are signed in their raw URI form, so Backend must use the same raw path/query bytes sent on the wire.

## Replay handling

The nonce is globally unique for the assertion lifetime. DATA-AI inserts it into `service_assertion_nonces` in a separate committed transaction before the business handler runs. A duplicate nonce is rejected with 401. Expired rows are pruned on authenticated requests. The database must be available; if the replay store is unavailable, requests fail closed with 503.

Operationally, monitor table growth and request rate. For very high volume, replace per-request cleanup with a scheduled retention job/partition strategy after measuring production traffic. Do not switch to process-local memory for a multi-worker deployment.

## Key rotation

1. Add a new key ID and secret to DATA-AI while retaining the old key.
2. Deploy Backend signing with the new key ID.
3. Confirm successful traffic and monitor 401 signature failures.
4. Wait longer than the maximum assertion lifetime and deployment propagation window.
5. Remove the old key from DATA-AI configuration.

Never reuse a key ID for different key material. Synchronize clocks on Backend and DATA-AI hosts (NTP).

## Backend responsibilities remain mandatory

Spring Boot must authenticate the caller, derive actor/roles/bank from its server-side principal, perform customer ownership, staff assignment, permission and Maker/Checker checks, and overwrite all identity headers. The signature proves that the trusted Backend sent these exact claims for this exact request; it does not make incorrect Backend authorization correct.

Keep DATA-AI on private networking with TLS. The shared internal token remains required in this release. Never expose either secret or the assertion signing capability to browser clients.

## Verification and limitations

- Unit tests cover valid signatures, method/path/query/body/identity tampering, expiry, malformed assertions, unknown key IDs, and weak key configuration.
- OpenAPI is regenerated from the running FastAPI app and includes both authentication headers.
- The automated suite does not prove a live PostgreSQL migration, concurrent replay behavior under load, Spring Boot interceptor compilation in the target repository, TLS, secret-manager integration, or NTP health. Those remain deployment acceptance checks.
