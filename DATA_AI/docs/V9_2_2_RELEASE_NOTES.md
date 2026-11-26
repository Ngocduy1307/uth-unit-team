# DATA-AI V9.2.2 release notes

## Scope

Request-bound Backend-to-DATA-AI service authentication hardening. This increment does not replace Spring Boot authentication/authorization, does not implement Maker/Checker workflow, and does not change lending/business calculations or Camunda orchestration.

## Implemented

- `X-Service-Assertion` added to all protected `/api/*` operations and published in the generated OpenAPI artifact.
- HMAC-SHA256 request signatures bind issuer, audience, method, raw path, raw query, exact body SHA-256, timestamp, nonce, actor, roles and bank.
- Key IDs support overlap during rotation; secrets require at least 32 UTF-8 bytes.
- Default validity skew is 120 seconds, configurable within 1–600 seconds.
- PostgreSQL-backed unique nonce storage prevents replay across API workers. Nonce consumption commits independently from business transactions.
- Production fails closed unless both the internal service token and signed assertion keys are configured.
- Local development/test compatibility remains available only when assertion keys are not configured; it is not acceptable for pilot/production.
- Request body size is capped during signature verification by `MAX_SIGNED_REQUEST_MB` (default 24 MiB).
- Spring Boot examples include a signer and a `ClientHttpRequestInterceptor` that signs the final serialized request body.

## Files changed

- `app/security.py`, `app/main.py`, `app/config.py`, `app/models.py`
- `db/migration/V10__signed_service_assertion_replay_protection.sql`
- `contracts/data-ai-openapi.json`
- `examples/backend-spring/DataAiAssertionSigner.java`
- `examples/backend-spring/DataAiSignedAssertionInterceptor.java`
- `examples/backend-spring/DataAiClient.java`
- `.env.example`, `docker-compose.yml`, README and security documentation

## Verification

- Automated tests: **76 passed**.
- Python compile check: passed.
- Java signer compile check: passed with JDK 21.
- Docker Compose validation and PostgreSQL/Flyway execution: not run because Docker is unavailable in this environment.
- Spring interceptor compilation against the actual Spring Boot dependency set: not run; the example must be integrated and compiled in the team's Backend repository.

## Deployment gates still open

1. Apply Flyway V10 to a staging PostgreSQL database.
2. Configure distinct internal-token and HMAC signing secrets through a secret manager.
3. Integrate the Spring interceptor and verify body/path/query canonicalization with real requests, including multipart uploads.
4. Test duplicate nonce replay concurrently across multiple DATA-AI workers.
5. Verify NTP clock synchronization, TLS/private networking, key rotation and monitoring.
6. Confirm Backend still enforces customer ownership, staff assignment, permissions and Maker/Checker separation.

Until these gates pass, V9.2.2 is a code-complete integration increment, not a production security certification.
