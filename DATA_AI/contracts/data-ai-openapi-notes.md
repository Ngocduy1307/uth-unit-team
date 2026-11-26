# DATA-AI API contract notes (V9.5.2 alignment pass)

- OpenAPI source of truth: `app.main:app`.
- Checked-in artifact: `contracts/data-ai-openapi.json`.
- API base path: `/api/v1`.
- JSON encoding: UTF-8. Resource identifiers are UUID strings unless a schema says otherwise.
- All `/api/v1/**` operations are internal service APIs and declare `X-Internal-Service-Token`.
- The token is mandatory outside `APP_ENV=development` and `APP_ENV=test`. Tokenless development must never be exposed to an untrusted network.
- `X-Internal-Service-Token` is service-to-service protection, not end-user authentication or bank-level authorization.
- Where actor context is required, Spring Boot must overwrite `X-Actor-Id`, `X-Actor-Roles`, and `X-Bank-Id` from its authenticated server-side principal. Never forward browser-supplied values.
- Frontend calls Spring Boot only. It must never call DATA-AI or PostgreSQL directly.


## V9.3.1 OCR governance

- `GET /api/v1/admin/ocr/catalog` returns the six provisional generic document profiles and 20 provisional field labels for trusted service/admin roles.
- The catalogue is read-only. It does not approve a bank layout, publish bank-specific configuration or decide which fields are required.
- Document-processing results now expose field-level validation, confidence basis, extraction decision and abstention reasons through the existing fields API and pipeline summary.
- `SUGGEST` is not `ACCEPTED`; `ABSTAIN` routes the candidate for human review. Native PDF text-layer extraction is explicitly uncalibrated and remains review-required.
- Apply Flyway V12 after V11. The six actual bank layouts, exact SRS 20 fields and calibration thresholds remain pending Bank/PO sign-off.

## V9.2.3 mutation reliability

- All `POST`, `PUT`, `PATCH`, and `DELETE` operations under `/api/v1/` publish an optional `Idempotency-Key` header and a `409` response in OpenAPI. The middleware only reserves requests when a key is supplied; clients that omit it retain legacy behavior.
- Key format: 8–128 safe ASCII characters. Backend persists one key per logical command and reuses the exact key and exact request bytes on retry.
- Requests with an idempotency key require Signed Assertion V2, which signs the key together with the method/path/query/body/actor context. Signed Assertion V1 remains valid only when no idempotency key is supplied.
- `409` codes include `IDEMPOTENCY_KEY_REUSED`, `IDEMPOTENCY_IN_PROGRESS`, `IDEMPOTENCY_OUTCOME_UNKNOWN`, and `IDEMPOTENCY_RESPONSE_NOT_REPLAYABLE`. An `OUTCOME_UNKNOWN` result requires business-record reconciliation; do not generate a fresh key and blindly re-submit.
- Retention is 72 hours by default. Responses over the replay size limit are not cached for replay. The response cache can contain PII and requires database/storage encryption, least-privilege and periodic TTL cleanup.
- Do not automatically retry `GET /api/v1/admin/exports/excel`: it creates an export job and audit rows before streaming the workbook. Several customer-read GET endpoints also append access audit events.

## Implemented operations

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Database and Flyway readiness |
| POST | `/api/v1/cases` | Create case |
| GET | `/api/v1/cases/{case_id}` | Read case |
| POST | `/api/v1/cases/{case_id}/documents` | Upload evidence document |
| GET | `/api/v1/cases/{case_id}/documents` | List case documents |
| POST | `/api/v1/cases/{case_id}/documents/{document_id}/process` | Run document processing pipeline (requires current byte-bound ClamAV CLEAN attestation) |
| POST | `/api/v1/cases/{case_id}/documents/{document_id}/security-scan` | Dedicated DOCUMENT_SCANNER service task; ClamAV INSTREAM and exact byte SHA-256 attestation |
| GET | `/api/v1/cases/{case_id}/transactions` | Read normalized transactions |
| GET | `/api/v1/cases/{case_id}/fields` | Read extracted fields |
| POST | `/api/v1/cases/{case_id}/applicant-submissions` | Persist immutable applicant form snapshot |
| GET | `/api/v1/admin/exports/excel` | Staff-authorized Excel export |
| GET | `/api/v1/admin/exports/history` | Read export history |
| POST | `/api/v1/customers` | Create customer data record |
| GET | `/api/v1/customers` | List customers within caller bank scope |
| GET | `/api/v1/customers/{customer_id}` | Read customer within caller bank scope |
| PATCH | `/api/v1/customers/{customer_id}` | Update customer data |
| POST | `/api/v1/customers/{customer_id}/applications` | Create application and linked case/snapshot |
| POST | `/api/v1/internal/staff-sync` | Synchronize staff reference data |
| GET | `/api/v1/admin/access-control/catalog` | Read permission catalogue metadata |
| GET | `/api/v1/admin/staff/{staff_id}/role-history` | Read staff role history |
| GET | `/api/v1/admin/forms/{form_code}` | Read active form definition |
| PUT | `/api/v1/admin/forms/{form_code}` | Publish form definition |
| GET | `/api/v1/admin/staff` | List staff |
| GET | `/api/v1/admin/audit-logs` | Read management audit log |
| POST | `/api/v1/admin/banks` | Create bank organization |
| POST | `/api/v1/admin/banks/{bank_id}/branches` | Create bank branch |
| GET | `/api/v1/cases/{case_id}/quality-issues` | Read case data-quality issues |
| GET | `/api/v1/cases/{case_id}/pipeline-runs` | Read processing lineage |
| GET | `/api/v1/admin/source-inventory` | Read configured source inventory |
| GET | `/api/v1/admin/field-mappings` | Read configured source-field mappings |
| GET | `/api/v1/admin/ocr/catalog` | Read provisional OCR profile and field catalogue (trusted service/admin roles) |
| POST | `/api/v1/cases/{case_id}/governance/freeze` | Maker creates/freeze immutable DATA-AI input snapshot |
| GET | `/api/v1/cases/{case_id}/governance/versions` | List version metadata, readiness and governance events |
| GET | `/api/v1/cases/{case_id}/governance/versions/{version_id}` | Read a version snapshot and event history |
| POST | `/api/v1/cases/{case_id}/governance/versions/{version_id}/checker-review` | Independent Checker confirms technical readiness or returns to Maker |

## V9.4.1 Governance & Maker–Checker

- `POST /api/v1/cases/{case_id}/governance/freeze` requires a trusted human MAKER actor and records the immutable version/hash snapshot.
- `GET /api/v1/cases/{case_id}/governance/versions` and `GET /api/v1/cases/{case_id}/governance/versions/{version_id}` expose version metadata/events and (for detail) the frozen snapshot to a bank-scoped MAKER or CHECKER.
- `POST /api/v1/cases/{case_id}/governance/versions/{version_id}/checker-review` accepts `CONFIRM` or `RETURN` from a trusted CHECKER actor. Maker and Checker actor IDs must differ; dual MAKER+CHECKER role contexts and service identities are rejected.
- Checker `CONFIRM` requires the stored version readiness to have no blockers and verifies the stored snapshot SHA-256/readiness projection. A `CLEAN` malware status requires matching append-only V1_CLAMAV evidence for the exact current file hash; legacy EXEMPT is not technical evidence. `RETURN` unlocks case-owned inputs (including later security-event inserts) for Maker edits; the next freeze creates the next version and supersedes the returned version.
- Database triggers enforce frozen-input immutability, require every version to commit with a FROZEN event, and block later document-security-event inserts until return-to-Maker. Snapshot detail reads and Checker decisions re-check SHA-256 and the readiness projection. Backend/SSO still owns role assignment and task assignment; Camunda owns task/process state. A DATA-AI Checker confirmation is not credit approval and does not complete a Camunda task.

## V9.5.1 workflow integration boundary

- V9.5.1 published 56 paths. V9.5.2 adds the dedicated document security-scan route; the current runtime-generated contract publishes 57 paths. `contracts/data-ai-openapi.json` is the checked-in artifact.
- V16 routes cover process binding, outbox claim/ACK, signed inbox callbacks, workflow event trace, Awaiting Evidence/resubmission, governed reopen, release-gate references, hashed evidence packages and Business Engine override-application receipts.
- `WORKFLOW_ORCHESTRATOR` is a dedicated service identity. It cannot stand in for Maker/Checker. `BUSINESS_ENGINE` receipt write requires a `BUSINESS_ENGINE`-only assertion. `RELEASE_AUTHORITY` records G4 external references; Backend/SSO validates actual grant.
- Outbox payloads are allowlisted and intentionally omit PII/raw document content. At-least-once delivery requires the target worker/system to deduplicate by event/idempotency key. Inbox callbacks require a bound process instance, contiguous sequence, exact event ID replay and signed service assertion.
- Camunda owns BPMN/User Tasks/Timers/DMN/notifications; Backend/SSO owns identity, assignment, consent and delegation; Business Engine owns authoritative I/E/D, schedule, DSR, stress, policy and override execution. DATA-AI only records evidence/correlation/receipts and never makes credit decisions.
- V9.5.1 JSON/CSV/PDF export is an evidence summary package. It includes metadata/hash rows but not original document binaries; every archive entry and the ZIP are SHA-256 addressed. Approved overrides require a matching Business Engine application receipt before G4/export.
- Inbox callback JSON Schema: `contracts/camunda-workflow-inbox-event-v1.schema.json`; sample envelopes: `contracts/examples/`.
- See `docs/V9_5_1_HANDOFF.md`, `docs/V9_5_1_WORKFLOW_INTEGRATION.md` and `docs/WORKFLOW_API_TRACEABILITY.md`.

## V9.5.2 production security boundary

- `POST /api/v1/cases/{case_id}/documents/{document_id}/security-scan` is a dedicated `DOCUMENT_SCANNER` service operation. The signed assertion must carry only that role and the matching bank scope; scope is revalidated after the Case row lock.
- The ClamAV adapter hashes the exact byte stream sent to the daemon and requires an explicit CLEAN/FOUND verdict plus an engine version. The route compares scanner-stream SHA-256, the document ledger hash and a post-scan storage hash. Unknown replies, daemon outage, hash drift or unsafe paths fail closed.
- OCR/processing requires an exact V1_CLAMAV CLEAN event and parses only a private read-only temporary copy whose bytes are rehashed against the same document digest. The mutable evidence path is never handed directly to the parser.
- V17 makes scan events append-only and enforces byte-bound scan status in PostgreSQL. New EXEMPT scan states are rejected; legacy values remain untrusted.
- Production preflight rejects placeholder secrets, requires PostgreSQL `sslmode=verify-full` and an absolute readable `sslrootcert`, ClamAV, protected storage/export volume references and Flyway V17.
- The runtime uses a non-root read-only container, dropped capabilities, no-new-privileges, request/security headers, bounded process/file descriptors and backup/restore scripts. None of these source-level checks prove live infrastructure configuration.

## Workflow boundary and status

The API currently supports case intake, document intake/processing, OCR-derived fields,
normalized transactions, customer/application snapshots, quality and pipeline metadata,
and selected staff/admin reference operations.

The API inventory does **not** establish that the complete Camunda workflow is implemented.
In particular, the workflow's maker verification of account ownership and statement period,
consent-scope DMN gate, six-month evidence sufficiency, debt/payment-schedule validation,
residual and monthly debt-ratio calculations, stress scenarios, policy routing, named-authority override, shadow/operational release gates, expiry and reopen behavior
must not be represented as implemented merely because related tables or metadata endpoints exist. V9.5.1 now implements the DATA-AI workflow adapters and persistent state for process correlation, outbox/inbox, evidence request/resubmission, governed reopen, externally recorded release gates and hashed evidence packages. Actual Camunda BPMN/User Tasks/Timers/DMN, Backend/SSO connection and Business Engine execution remain external.
Those remain explicit integration/implementation gates unless a corresponding executable
service, API contract, Camunda task/DMN integration and tests are delivered.

## Error and compatibility rules

- Request/response schemas and status codes are defined by the generated OpenAPI document.
- Validation errors currently use FastAPI's standard `422` response shape unless an endpoint
  explicitly documents another status.
- Existing endpoint behavior must be treated as the compatibility baseline; changes to field
  names, nullability, status codes, or response envelopes require a reviewed contract change.
- Regenerate the OpenAPI artifact after route/schema changes and run `pytest` before release.

## Regenerate OpenAPI

From the `DATA_AI` directory:

```bash
python -c "import json; from app.main import app; json.dump(app.openapi(), open('contracts/data-ai-openapi.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)"
```

The trailing newline may be added by the editor. The V9.2 regression test compares parsed JSON,
so whitespace formatting does not affect the contract check.
