# DATA_AI V9.2.3 – API Reliability Update

## Source changes

- Keeps request correlation with server-controlled `X-Request-ID` and bounded SQLAlchemy PostgreSQL pool settings.
- Adds durable, optional `Idempotency-Key` handling for `POST`, `PUT`, `PATCH`, `DELETE` under `/api/v1/`.
- Adds idempotency persistence model and Flyway migration `V11__api_idempotency_records.sql`.
- Adds signed assertion V2: the idempotency key is HMAC-bound; V1 remains supported for calls without a key.
- Verifies service authentication and nonce replay protection for every incoming attempt, including replay requests.
- Adds response replay, key/payload mismatch detection, concurrent in-progress protection, stale/unknown outcome handling, a maximum replay response size and a bounded TTL cleanup statement.
- Adds Spring integration examples for stable request bytes, deterministic multipart boundaries, bounded retry/backoff, process-local circuit breaker and connect/read timeout.
- Moves CSV import side effects into the parent `process_document()` transaction and adds per-attempt upload storage paths and cleanup on database commit failure, including the concurrent duplicate-upload race.
- Publishes optional idempotency request headers and 409 responses in the OpenAPI artifact.
- Adds workflow-to-API traceability and transaction-boundary audit documents. The supplied `Workflow.drawio` is retained under `docs/`.

## Database

Apply Flyway V11 after V10. New environments must apply V1 through V11 in order. Never edit an already-applied migration, and do not run SQLAlchemy `create_all()` or Alembic against the shared `data_ai` schema.

## Automated verification

The local automated test suite is expected to pass with `pytest -q`. Final local result for this update: **96 passed** (see `docs/V9_2_3_HANDOFF.md`). The suite is not a substitute for a live PostgreSQL migration, concurrency/load, pool saturation, backup/restore, or target Spring Boot integration test.

## Known limitations and release gates

- Idempotency reservation, business transaction and response completion do not share one atomic transaction. A failure in the gap creates `OUTCOME_UNKNOWN`; operators must reconcile before retrying. This is not an exactly-once guarantee.
- Large response bodies above the configured replay threshold are marked completed but not replayable.
- The example Spring circuit breaker is process-local; use the team's standard resilience implementation and configuration for a multi-replica production deployment.
- The Excel export endpoint is a side-effecting GET and must not be automatically retried. A follow-up should introduce a POST export command and separate download endpoint.
- Camunda workflow integration, OCR bank-layout acceptance, reconciliation, DSR/affordability calculation, Maker–Checker, override, policy exception, audit governance, recovery drills and production gates remain open roadmap work.
- Response payload is stored as BYTEA without application-level encryption; production requires database/storage encryption, least-privilege and the V11 TTL cleanup job.
- PostgreSQL V11/Flyway and Spring integration have not been run against the actual target environments in this handoff. Do not mark Production Acceptance solely from local unit tests.
