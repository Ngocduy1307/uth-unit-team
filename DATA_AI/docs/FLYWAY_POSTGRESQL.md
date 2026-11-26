# PostgreSQL + Flyway

Flyway owns schema evolution. Application startup does not call SQLAlchemy `create_all()`.

## Local startup
1. Copy `.env.example` to `.env` and use development-only credentials.
2. Run `docker compose up -d postgres`.
3. Run `docker compose run --rm flyway` (or `docker compose up flyway`).
4. Confirm `data_ai.flyway_schema_history` and tables exist.
5. Configure `DATABASE_URL` with `search_path=data_ai` as shown in `.env.example`.
6. Start FastAPI.

Migrations are immutable after shared use. Add the next sequential migration for later changes; do not edit a migration that has already run in another environment. Review SQL and back up the database before production migration.

For a shared database, agree with Backend on a single Flyway owner. Recommended: Backend/Platform owns Flyway execution; DATA-AI contributes reviewed SQL migrations for the `data_ai` schema. Do not run Alembic and Flyway against the same tables.

The included Docker Compose credentials are for local development only. Production must use secrets management, least-privilege DB roles, TLS, private networking, backup/restore and a controlled migration job.

## Migration history through V10.0 source release

V10 adds the PostgreSQL-backed signed-assertion nonce registry. V11 adds the idempotency request/response ledger. V12 adds OCR confidence basis, field validation and abstention metadata. Apply migrations sequentially through V14; confirm the target schema is at V11 before applying V12 and at V12 before applying V13. The bounded TTL cleanup statement for V11 is `db/maintenance/cleanup_api_idempotency_records.sql`; run it from a maintenance scheduler in batches rather than deleting expired rows on every API call.

## V9.3.2 notes

V13 adds case-scoped evidence manifest/hash-chain records, PDF–CSV reconciliation snapshots, transaction duplicate pair candidates and immutable Maker review events. It also adds same-case composite FKs and append-only triggers for the new evidence ledgers. Apply V13 only after V12 and after backup/Flyway history review. Existing documents are not automatically manifested; use `scripts/backfill_evidence_manifest.py` as a dry run, review any missing or hash-mismatched storage objects, then run with `--apply` under an approved maintenance window. The script records historical attribution as `LEGACY_BACKFILL` rather than inventing the original uploader.

Static DDL/model validation and local tests do not replace running V13 on a disposable PostgreSQL clone. Verify composite FK behavior, trigger rejection of UPDATE/DELETE, concurrent manifest sequence assignment, rollback cleanup, storage re-hash and backup/restore before shared deployment.


## V14 / V9.4.1 governance

V14 adds immutable per-case analysis-input snapshots, sequential version/parent constraints, a deferred requirement for a matching `FROZEN` event, append-only Maker–Checker events, role/actor separation checks, and a DB-level freeze guard across case-owned evidence/input tables, including `document_security_events`. `RETURNED_TO_MAKER` is the only state that re-enables input mutations; a later Maker freeze creates the next version and supersedes the returned version. Checker confirmation is blocked while the stored readiness assessment has unresolved blockers, including a missing matching scanner event or missing engine evidence for a `CLEAN` status. Snapshot detail reads and Checker decisions re-hash persisted snapshot data before use.

Apply `V14__case_analysis_version_governance_freeze.sql` only after V13, after confirming the single Flyway owner and a restorable backup. Execute on a disposable PostgreSQL clone first. Validate all triggers, same-case FKs, partial unique indexes, Maker/Checker role checks, frozen INSERT/UPDATE/DELETE rejection, return-to-Maker unlock and a concurrent source-write-vs-freeze test. Static Python tests and SQLAlchemy DDL compilation do not certify PL/pgSQL execution.

## V15 / V9.4.2 audit and override governance

V15 adds per-case hash-chained audit entries, immutable Maker Override/Policy Exception proposals, append-only Checker/Named Authority decisions, and reference roles/permissions. The `scripts/backfill_case_audit.py` default is dry-run; inspect the digest-only legacy mapping and restore a backup before `--apply`. Backend/SSO must provide the named authority's active grant/scope/limit evidence; a V15 approval does not execute the exception. Run V15 on a PostgreSQL clone and test sequence serialization, append-only triggers, partial unique terminal-decision index, proposal/version composite FKs and Maker/Checker/Authority actor separation.


## V16 / V9.5.1 workflow integration

V16 follows V15 and adds Camunda 8 process binding, transactional outbox/inbox, Awaiting Evidence/resubmission records, governed reopen, external G3/G4 gate references, JSON/CSV/PDF export-package metadata and Business Engine override-application receipts. It also seeds `WORKFLOW_ORCHESTRATOR`, `RELEASE_AUTHORITY`, `BUSINESS_ENGINE` and the integration permission catalogue. V16 replaces the V14 case-analysis version-sequence/frozen-input guard functions so a new version after Checker confirmation is allowed only when a matching `case_workflow_reopens` row is `OPEN`; the next Maker Freeze consumes the reopen.

Before V16, take a restorable backup and inspect V1–V15 Flyway history. Apply V16 only after V15. Run it first against a disposable PostgreSQL clone and test append-only triggers, V14 freeze/reopen trigger behavior, same-case FKs, partial unique indexes, event sequence uniqueness, outbox lease/retry/dead-letter state transitions, concurrent claim and callback replay, G3/G4 constraints, receipt matching and rollback. The source test suite compiles SQLAlchemy models with PostgreSQL dialect but does not execute V16 PL/pgSQL or Flyway. This release has not been applied to a real PostgreSQL instance; staging verification is mandatory.

The Camunda worker, BPMN, Timer, DMN, Tasklist and actual Spring Boot/SSO/Business Engine connections are external deployment responsibilities. Never treat `workflow_outbox_events` or `workflow_inbox_events` as proof that those external systems are deployed.

## V9.5.2 / V17 production security scan gate

Apply `V17__production_security_scan_and_integrity.sql` after V16. It introduces exact-byte scan hash and attestation metadata on `document_security_events`, makes those events append-only, and requires a matching `V1_CLAMAV` event before a document can transition to `CLEAN` or `INFECTED`. It also makes `EXEMPT` unavailable for new/updated documents while preserving legacy rows as historical data.

Before applying V17 to an existing environment:

1. Take and verify a restorable PostgreSQL backup and paired storage snapshot.
2. Audit all existing `documents.malware_scan_status` and `document_security_events` rows. Historical CLEAN/EXEMPT flags remain `LEGACY_UNVERIFIED`; they are not promoted to trusted scan evidence.
3. Deploy the V9.5.2 application and configure a private ClamAV daemon, PostgreSQL TLS using `sslmode=verify-full` plus an absolute CA certificate path, and separate platform-KMS encrypted storage/export volumes.
4. Apply V17 using the single Flyway owner.
5. Re-scan legacy CLEAN documents using the dedicated `DOCUMENT_SCANNER` service identity. Files without stored bytes must be re-intaken; EXEMPT documents do not pass Checker readiness.
6. Test DB triggers for CLEAN/INFECTED transitions, append-only scan events, freeze interaction, quarantine path permissions and failed scan timeout.
7. Run the storage integrity audit and verify the latest Flyway version is V17 before readiness is enabled.

V17 is source-reviewed and covered by migration contract tests, but a live PostgreSQL/Flyway run is still required in staging. The KMS variables in `.env` are key references/configuration assertions only; verify the actual storage encryption policy with the infrastructure provider.


## V10.0 / V18 DATA-AI workflow input handoff

Apply `V18__data_ai_workflow_input_handoff.sql` only after V17 and after the shared Flyway owner has reviewed the complete V1–V18 history. V18 is additive and introduces seven PostgreSQL tables:

- `case_scope_consent_attestations` — immutable mirror of a Backend/SSO scope and consent decision reference; DATA-AI does not create or legally validate consent.
- `case_input_declaration_revisions` and `case_input_declaration_evidence_links` — append-only versioned household, employment, expense, liability and salary-account declarations, linked to same-case evidence documents and SHA-256 values.
- `case_input_review_decisions` — Maker-only review decisions, with same-case declaration references and mandatory evidence anchors for OCR/payroll/transaction/ledger targets at the API boundary.
- `case_financial_input_bundles` — canonical JSONB, readiness facts and immutable SHA-256-bound evidence packet for the external Financial Engine.
- `case_proposed_schedule_references` — external Business Engine schedule reference, product version, term, VND currency and SHA-256; DATA-AI does not create installment rows or compute a schedule.
- `case_business_engine_receipts` — external calculation/policy/product version and hashes, consumed input bundle hash, output hash, scenario references and same-case schedule FK. A COMPLETED receipt requires exactly BASELINE, STRESS_1 and STRESS_2.

V18 installs bank-scope validation and append-only UPDATE/DELETE guards for all seven ledgers, plus composite same-case foreign keys and role/permission seeds. It preserves V1–V17 as immutable history. Production readiness pins `REQUIRED_FLYWAY_VERSION=18` and requires `REQUIRE_SCOPE_CONSENT=true`.

Before applying V18:

1. Take a restorable PostgreSQL backup and a coordinated document-storage snapshot; verify both.
2. Confirm V17 in `flyway_schema_history`, inspect checksum drift, and confirm one Flyway owner for the shared `data_ai` schema.
3. Apply V18 to a disposable PostgreSQL clone with the same major PostgreSQL version and extensions as staging.
4. Validate all seven table definitions, JSONB checks, composite FKs, unique indexes, case/bank scope trigger and append-only trigger behavior. Attempt UPDATE/DELETE on each V18 ledger and confirm the transaction is rejected.
5. Test Backend scope-attestation replay with same/different payload, declaration `client_request_id` replay, Maker review source-document linkage, bundle replay, schedule-reference replay and calculation-reference replay.
6. Verify a newer HOLD/FAILED Business Engine receipt blocks export even if an older COMPLETED receipt exists. Verify completed receipt points to the exact proposed-schedule row and only a snapshot frozen after the matching bundle/schedule/receipt can be exported.
7. Test case-row locking with concurrent declaration revision/bundle creation, rollback of outbox writes, snapshot freeze/reopen interaction and restoration of both DB and document bytes.
8. Verify readiness blocks if any month of the six-month observed-income ledger is missing or not Maker-confirmed; accepted income remains NULL unless an external authority supplies it.

The release source has static PostgreSQL-dialect ORM DDL compilation and automated contract tests. No live PostgreSQL, psql, Docker or Flyway CLI is available in the authoring environment; V18 has **not** been executed against a real PostgreSQL server. Treat live migration, trigger execution, concurrency and backup/restore as mandatory staging gates. Never run Alembic or SQLAlchemy `create_all()` alongside Flyway.
