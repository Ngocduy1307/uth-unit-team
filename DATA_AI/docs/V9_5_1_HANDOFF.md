# DATA-AI V9.5.1 – Workflow Integration Handoff

## Release scope

V9.5.1 implements the DATA-AI side of the integration boundary described by `docs/Workflow.drawio`: Camunda process correlation, transactional outbox/inbox, Awaiting Evidence/resubmission, governed reopen, externally recorded G3/G4 gates, Business Engine override-application receipts and hash-addressed JSON/CSV/PDF evidence packages.

It does **not** deploy Camunda 8, create BPMN/User Tasks/DMN/Timers, connect the actual Spring Boot/SSO or Bank Business Engine, run credit calculations, decide a loan, apply an override or certify an operational release.

## Delivered source changes

- Flyway `V16__camunda_workflow_integration_and_evidence_lifecycle.sql` adds nine workflow tables, reference roles/permissions, append-only guards and controlled state transitions.
- Camunda 8 correlation binding: one active process binding per case, unique process instance ID, process definition key and business key.
- Transactional outbox: no-PII allowlisted payload, payload hash, idempotency key, lease/worker ownership, `FOR UPDATE SKIP LOCKED`, exponential backoff, retry ceiling 8 and dead-letter state.
- Callback inbox: signed service boundary, event ID exact-replay protection, process sequence continuity, process binding and bank-scope validation.
- Awaiting Evidence requests with `due_at`; Camunda remains the timer owner. Expiry callback is rejected before its due time.
- Resubmission validates document same-case ownership, manifest-chain entry, byte SHA-256 and CLEAN/EXEMPT security-event proof; stores a deterministic impact list/hash. It does not create an analysis version itself.
- Reopen record for evidence/policy/product changes. PostgreSQL's V14 guards are extended so only Checker RETURN or a matching OPEN reopen allows protected input changes. Next Maker Freeze consumes the reopen and creates the successor version.
- G3/G4 release-gate reference records with same snapshot/product/policy constraint; G4 requires G3 and `RELEASE_AUTHORITY`.
- `BUSINESS_ENGINE`-only application receipt bound to an approved proposal hash, frozen version hash and exact policy ref/version. G4/export cannot proceed while an approved override lacks a matching receipt.
- ZIP evidence package: `analysis.json`, `evidence.csv`, `summary.pdf`, `manifest.json`; hashes for each entry and package; applicant/product/policy/calculation metadata and audit/evidence chain heads. Original document binaries are not embedded.
- Upload now saves the file and writes manifest/audit/outbox database records in one DB transaction when a workflow binding is active. On failure, the DB transaction rolls back and the newly written local file is removed.
- Updated generated OpenAPI contract: 56 paths.
- Published `contracts/camunda-workflow-inbox-event-v1.schema.json` and sample callback envelopes under `contracts/examples/`.

## V16 tables

| Table | Purpose |
|---|---|
| `case_workflow_bindings` | Case ↔ Camunda process correlation |
| `workflow_outbox_events` | Transactional events pending external delivery |
| `workflow_inbox_events` | Idempotent append-only callback ledger |
| `case_evidence_requests` | Awaiting Evidence request and due time |
| `case_resubmissions` | Immutable document receipt + impact list/hash |
| `case_workflow_reopens` | Governed reopen and successor-version link |
| `case_workflow_release_gates` | External G3/G4 references |
| `case_workflow_export_packages` | Hashed evidence package metadata/path |
| `case_override_application_receipts` | External Business Engine application proof |

## Service roles / permissions

- `WORKFLOW_ORCHESTRATOR`: process binding, callback receipt and outbox delivery only. It is a signed service identity, not a human task identity.
- `BUSINESS_ENGINE`: exact single-role assertion for override-application receipt writes only.
- `RELEASE_AUTHORITY`: records externally authorized G4 Operational reference; actual grant must be supplied/validated by Backend/SSO.
- `MAKER`, `CHECKER`, `BANK_POLICY_OWNER`: case-scoped user actions as defined in the route and signed assertion checks. DATA-AI's role/permission mirror is not the authoritative grant system.

## Key API paths

- `POST/GET /api/v1/workflow/cases/{case_id}/binding`
- `POST /api/v1/workflow/outbox/claim`
- `POST /api/v1/workflow/outbox/{event_id}/ack`
- `POST /api/v1/workflow/events`
- `GET /api/v1/workflow/cases/{case_id}/events`
- `POST/GET /api/v1/cases/{case_id}/workflow/evidence-requests`
- `POST /api/v1/cases/{case_id}/workflow/evidence-requests/{request_id}/resubmit`
- `GET /api/v1/cases/{case_id}/workflow/resubmissions`
- `POST/GET /api/v1/cases/{case_id}/workflow/reopen`
- `POST /api/v1/cases/{case_id}/workflow/release-gates`
- `POST/GET /api/v1/cases/{case_id}/workflow/export-packages`
- `GET /api/v1/cases/{case_id}/workflow/export-packages/{package_id}/download`
- `POST /api/v1/cases/{case_id}/governance/override-requests/{request_id}/application-receipt`

All these paths require the internal-service boundary and trusted actor/service assertion as documented by OpenAPI. Never accept actor/role/bank headers from browser-controlled inputs; Spring Boot must overwrite them from its authenticated principal.

## Test/validation status

- `pytest -q`: 191 passed (working source; rerun on extracted release archive before handoff).
- `python -m compileall -q app tests`: passed.
- OpenAPI generated from `app.main:app`: 56 paths; checked-in JSON refreshed.
- SQLAlchemy PostgreSQL dialect DDL compilation for the nine V16 ORM tables/indexes: passed in the test suite.
- Workflow diagram in `docs/Workflow.drawio` matches the user-provided `Workflow(2).drawio` SHA-256.

The test suite does not run a PostgreSQL server. V16 has **not** been applied through Flyway to a live/disposable PostgreSQL instance in this environment. PL/pgSQL trigger behavior, row-lock serialization, outbox concurrency, rollback and restore need staging verification.

## Required staging acceptance

1. Take and restore a PostgreSQL backup; run Flyway V1–V16 in order and inspect `flyway_schema_history`.
2. Exercise every V16 append-only trigger and all valid/invalid transition branches.
3. Concurrently claim outbox records from multiple workers; prove no double lease, verify lease expiry, retry/backoff, max-attempt dead-letter and same-key/same-payload idempotency.
4. Send duplicate Camunda callback IDs (identical then different content), sequence gap, wrong process instance and wrong bank scope; expect exact replay success and conflict/404 otherwise.
5. Verify evidence expiry before/after `due_at`, resubmission with wrong-case/missing-manifest/hash-mismatch/missing-security-event documents, and a valid resubmission + Maker Freeze successor version.
6. Verify frozen rows reject writes without an OPEN reopen; verify a reopen can only reference the latest Checker-confirmed version and is consumed by its successor Freeze.
7. Verify G4 fails without G3, when product/policy/snapshot differs, with no RELEASE_AUTHORITY, and with approved override but no/mismatched Business Engine receipt.
8. Verify export is blocked for missing/changed evidence, invalid audit/manifest chain, pending reopen or invalid override; test package entry hashes, package hash and access controls.
9. Integrate real Spring Boot/SSO signed identities, Camunda 8 BPMN/DMN/Timer, Bank Business Engine and private object storage using staging secrets/mTLS.
10. Run PII controls, KMS encryption, retention/legal hold, malware/quarantine, backup/restore, load, penetration and disaster-recovery tests.

## Known limitations / deployment warnings

- No actual Camunda/BPMN deployment, SSO connector, bank engine endpoint, keys, certificates, service account or worker runtime is bundled.
- Timer, DMN, Task assignment/completion, notifications/escalations remain external.
- `CASE_EXPIRED` callback is stored as immutable inbox/audit evidence; it does not mutate a frozen Case row.
- Resubmission records an impact list. It deliberately does not recompute business calculations or create a version; Maker must review and run Freeze.
- G3/G4 are external gate references, not tests executed by DATA-AI.
- Business Engine receipt is attestation only; DATA-AI never applies the override itself.
- Export package is sensitive; production needs KMS/envelope encryption, private export storage, strict retention and access auditing. Package includes evidence metadata, not raw source file bytes.
- Local filesystem atomicity is not the same as a distributed transaction with object storage. Production should replace local file storage with a private object store and use an object-store staging/commit protocol.
