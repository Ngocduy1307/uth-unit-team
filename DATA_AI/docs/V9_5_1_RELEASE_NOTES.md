# DATA-AI V9.5.1 Release Notes

## Added

- V16 Camunda 8 workflow correlation and transactional outbox/inbox.
- Signed, bank-scoped service-worker contract for outbox claim/ack and Camunda callbacks.
- Awaiting Evidence request, expiry callback boundary, resubmission and deterministic impact list/hash.
- Controlled reopen that can release V14 input freeze only for an explicit OPEN reopen based on the latest confirmed snapshot.
- External G3/G4 release-gate reference records.
- Dedicated `BUSINESS_ENGINE` application receipt bound to approved proposal, snapshot and policy hashes.
- Hashed ZIP package with JSON, CSV, PDF summary and manifest.
- Atomic DB transaction boundary for document row/manifest/audit/outbox write; cleanup of newly written file on DB failure.
- OpenAPI contract refreshed to 56 paths.

## Security and invariants

- Camunda service identity cannot act as Maker/Checker; orchestration roles are not human task grants.
- Business Engine receipt write requires exactly the `BUSINESS_ENGINE` role, without combined roles.
- Camunda event ID replay is idempotent only when the content hash matches; process sequence must be contiguous.
- Outbox events use an allowlisted no-PII payload, unique idempotency key, lease, retry/backoff and DB-enforced max 8 attempts/status-lease consistency.
- Evidence request rows require a workflow binding; terminal states require `resolved_at`. Reopen rows must start from the latest Checker-confirmed version and consumed rows require a direct successor link and `consumed_at`.
- DB release-gate constraints restrict G3/G4 actor roles. The receipt trigger checks the referenced proposal, snapshot hashes, policy values and active approval before accepting the external application receipt.
- `EVIDENCE_EXPIRED` cannot be accepted before `due_at`.
- Resubmitted documents must match case scope, manifest, content hash and valid security event.
- G4 requires preceding G3 on the same version/product/policy and a RELEASE_AUTHORITY actor.
- Any approved Override must carry a matching Business Engine application receipt before G4/export.
- Frozen evidence/input rows remain locked except through Checker RETURN or explicit OPEN reopen.

## Not delivered

- Actual Camunda deployment/BPMN/DMN/Timers, Tasklist and worker runtime.
- Actual Spring Boot/SSO and Business Engine connectivity, service keys/certificates and mTLS.
- Bank scanner, quarantine, authoritative bank/customer verification.
- Business calculations (I/E/D authority, schedule, residual/DSR, stress, credit policy decision).
- Execution of G3/G4 tests; only external reference records are accepted.
- Production PostgreSQL/Flyway validation, backup/restore, KMS, WORM/SIEM, load and penetration testing.

## Validation

- Working source suite: 191 passed.
- Python compile and OpenAPI parity: 56 paths.
- PostgreSQL dialect ORM DDL compilation: passed; actual Flyway/PostgreSQL execution remains a required staging gate.

## Compatibility

- V16 is additive after V15, except it replaces the V14 version-sequence and frozen-input guard functions to recognize a controlled reopen. Review the migration and restore a backup before applying.
- Existing APIs keep their contracts; the OpenAPI JSON artifact was regenerated from runtime code.
