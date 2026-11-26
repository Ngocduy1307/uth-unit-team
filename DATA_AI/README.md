## V9.2.1 Authorization Boundary Hardening

- Shared trusted actor/role/bank assertion validation in `app/security.py`.
- Consistent case tenant-scope enforcement and staff-context parsing.
- Added authorization boundary regression coverage.
- See `docs/V9_2_1_AUTHORIZATION_BOUNDARY_HARDENING.md` for deployment
  prerequisites and explicit remaining security limitations.

# UNIT DATA-AI Service

Python FastAPI service with PostgreSQL 16, Flyway SQL migrations, customer/application data mirror, document evidence processing, staff/RBAC metadata, configurable forms and staff-only Excel export.

## 1. Run the complete stack (recommended)

Requirements: Docker Desktop with Docker Compose v2.

```powershell
Copy-Item .env.example .env
# Edit .env and set local passwords / INTERNAL_SERVICE_TOKEN.
# For host-run uvicorn, change DATABASE_URL host from postgres to localhost.
# Configure CLAMAV_HOST for Workflow file safety; without it files remain untrusted.
docker compose up --build -d
```

Services:
- API + Swagger: http://localhost:8001/docs
- Health: http://localhost:8001/health
- PostgreSQL: localhost:5432, database `income_assistant`, schema `data_ai`

The published API/database/pgAdmin ports bind to 127.0.0.1 by default. The API container runs as UID 10001 with a read-only root filesystem. Compose intentionally has no fallback database/admin passwords or internal service token.

Flyway runs before the API container starts. To inspect migration history:

```powershell
docker compose run --rm flyway info
```

Optional pgAdmin:

```powershell
docker compose --profile tools up -d pgadmin
```

Open http://localhost:5050. In pgAdmin's server connection use host `postgres` (container network), port `5432`, database `income_assistant`, and credentials in `.env`.

## 2. Seed synthetic demo data

```powershell
docker compose exec api python -m scripts.seed_demo
docker compose exec api python -m scripts.check_database
```

The seed inserts a synthetic bank, customer, address, employment, loan request and staff user. It is only for local demonstration, not real customer data.

## 3. Run API on host instead of Docker

Install Python 3.12+, Tesseract OCR with Vietnamese and English language packs, and PostgreSQL 16. Then:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Start PostgreSQL first, then run Flyway in Docker or with local Flyway CLI.
# Set DATABASE_URL in .env to localhost.
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

## 4. Main database table groups

- Customer: `customer_profiles`, `customer_addresses`, `customer_employments`.
- Loan application: `cases`, `loan_applications`, `applicant_submissions`.
- Staff/admin: `staff_users`, `access_roles`, `staff_user_roles`, `management_audit_logs`.
- Organization: `bank_organizations`, `bank_branches`.
- Configurable forms: `form_definitions`, `form_field_definitions`.
- DATA-AI: `documents`, `extracted_fields`, `transactions`, `processing_results`, `data_quality_issues`, `payroll_evidence`, `earning_match_candidates`, `income_ledger_months`, `audit_events`.
- Export: `export_jobs`.

## 5. API and integration

Frontend -> Spring Boot -> DATA-AI. Do not call DATA-AI or PostgreSQL directly from browser code. Backend owns authentication, consent, authorization and bank/tenant scope. See:
- `docs/V9_2_2_SIGNED_SERVICE_ASSERTIONS.md`
- `docs/DATABASE_AND_CUSTOMER_DOMAIN.md`
- `docs/EXCEL_EXPORT_AND_BACKEND_INTEGRATION.md`
- `examples/backend-spring/`
- `examples/frontend/`

## 6. Excel export

Staff calls Spring Boot's staff export endpoint. Backend authenticates the session, derives trusted actor/roles/bank scope, then calls DATA-AI `GET /api/v1/admin/exports/excel`. The workbook includes customer/profile/address/employment/application data and DATA-AI evidence, extraction, transactions, quality and ledger sheets. Export history is stored in `export_jobs`; management action is audited. Never email or publicly share unredacted workbooks.

## 7. Migrations

Migrations are in `db/migration`. Never edit an already-applied migration; create the next version. Flyway is the only migration manager for the `data_ai` schema. Do not run SQLAlchemy `create_all()` or Alembic against these tables.

## 8. Tests and limitations

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests cover currently implemented unit rules and workbook safety. PostgreSQL/Flyway execution, full OCR quality, integration with your team's Spring Boot/React repositories, penetration tests and load benchmarks must be run in the target environment. This is a runnable development/integration baseline, not a production-certified lending platform. Official bank layouts, CSV schemas and the SRS-approved 20 extraction fields must be supplied before claiming acceptance. DATA-AI does not calculate DSR or decide credit outcomes.

## Applicant profile additions (SRS-aligned)

See `docs/APPLICANT_PROFILE_DATA_DICTIONARY.md` and Flyway migration `V5__complete_applicant_financial_profile.sql`. The migration adds household declarations, monthly expense declarations, customer-declared liabilities, up to three VND salary-account declarations, and append-only declaration revisions. These are declarations/evidence only, not verified facts or credit calculations. The MVP remains limited to adult Vietnam-resident salaried applicants with VND bank-paid income; excluded income/product types must not be added to the customer form.

Run migrations with the configured Flyway service after backing up the development database. Do not edit an already-applied migration; create the next sequential V migration for subsequent changes. Production migration ownership must be agreed with the Backend/database owner.


## Document intelligence pipeline (provisional)

The current implementation includes generic document-family suggestions, label-based field extraction with page/bounding-box anchors, CSV normalization, row-level quality findings, duplicate-transaction candidates, pipeline run tracking, observed salary-candidate monthly ledger aggregation and payroll-to-credit match suggestions. These are assistive DATA-AI outputs and require authorized review.

See [`docs/KAN_WORK_ITEM_IMPLEMENTATION.md`](docs/KAN_WORK_ITEM_IMPLEMENTATION.md) for the KAN-73 through KAN-157 traceability matrix, limitations and acceptance conditions. The generic document families/20 extraction labels are provisional; they do not replace the six bank-approved layouts or two bank-approved CSV schemas awaiting sign-off.

Never commit `.env`. Copy `.env.example` to `.env` and replace every local password/token. The repository archive intentionally excludes local secrets, virtual environments and generated storage.


## Customer intake and authorization updates

- Apply Flyway migrations V1 through V18 in order for a new environment. V10 adds the persistent replay-protection nonce registry for signed Backend assertions; V11 adds the durable API idempotency response ledger; V12 adds OCR governance metadata; V13 adds append-only evidence provenance/reconciliation ledgers; V14 adds immutable analysis-input versions, Maker/Checker governance events and database-level freeze protection; V15 adds the hash-chained case audit ledger and immutable Override/Policy Exception proposal plus Named Authority decision records. V16 adds Camunda correlation/outbox/inbox, Awaiting Evidence/resubmission/reopen, G3/G4 external references, hashed JSON/CSV/PDF package metadata and Business Engine application receipts; V17 adds byte-bound ClamAV attestations, append-only scan events and database-side scan-state guards; V18 adds DATA-AI intake declarations, Maker evidence reviews, six-month observed-income readiness, immutable Financial Engine input bundles, proposed-schedule references and hash-bound calculation receipts. Apply migrations through the single agreed Flyway owner.
- V6 publishes customer form version 1.1 and adds the NET/GROSS declaration basis. V7 adds a permission catalogue, role-permission reference matrix, BANK_POLICY_OWNER and staff role assignment history. Existing migrations and submitted snapshots are preserved.
- The initial form is intentionally minimal. Expense, liability and salary-account details are collected later when required; do not remove their evidence tables.
- Browser authentication and all customer/staff/admin authorization are owned by Spring Boot/SSO. DATA-AI is an internal service only.
- See `docs/CUSTOMER_INTAKE_V1_1_MAPPING.md`, `docs/FRONTEND_BACKEND_DATA_CONTRACT_V1_1.md` and `docs/RBAC_PERMISSION_CATALOG.md` before wiring the Frontend and Backend. JSON Schema is in `contracts/customer-intake-v1.1.schema.json`.
- The reviewed archive intentionally excludes `.env`, virtual environments, caches, local storage and generated exports. Create a fresh `.env` from `.env.example`; never commit secrets.

## V8 production-hardening package

V8 adds an additive PostgreSQL migration at `db/migration/V8__production_data_integrity_and_governance.sql` and an ERD package under `docs/ERD_V8.*`.

**Important release status:** the V8 migration and design documentation are prepared, but V8 is not yet a complete production application release. The existing SQLAlchemy models, Pydantic schemas, API routes, OpenAPI contract, export implementation and integration tests still require coordinated updates. Do not deploy V8 to production until the runbook in `docs/V8_DEPLOYMENT_AND_BACKFILL.md` is completed and staging verification passes.

Before applying V8 to an existing database:

1. Verify V1–V7 Flyway history and take a restorable backup/PITR checkpoint.
2. Run `db/preflight/V8_preflight_checks.sql` manually against staging (the file is not a Flyway migration).
3. Reconcile legacy `cases.bank_id` text codes with `bank_organizations.bank_code`; backfill `cases.bank_organization_id` only from an approved mapping.
4. Resolve case/customer and salary-account anomalies.
5. Apply V8 through the single agreed Flyway migration owner.
6. Validate the `NOT VALID` foreign keys only after reconciliation.
7. Deploy application code that supports V8 fields and endpoints before enabling new Frontend flows.

V8 deliberately does not enable PostgreSQL RLS. Tenant RLS must only be enabled after Backend sets a trusted transaction-local tenant/actor context for every pooled connection and the policies are tested. Authentication and authoritative authorization remain with Backend/SSO.

## V9.0 DATA-AI extraction improvements

See `docs/V9_DATA_AI_RELEASE.md`. V9.0 prefers native PDF text extraction and uses OCR for scanned/sparse pages, preserves source coordinate space and extraction method, and rejects encrypted/malformed/empty PDFs. Apply `V9__document_extraction_provenance.sql` after V8. This is not a malware scanner or sandbox; do not use real customer files until the security controls and staging gates listed in the release notes are completed.


## V9.1 database and ORM alignment

V9.1 aligns SQLAlchemy mappings with V8/V9 persistence additions: case bank-organization reference, document security/retention metadata, payroll extraction-field provenance, consent/security event tables, declaration idempotency metadata and revision provenance. Regression tests protect this mapping coverage.

Review `docs/V9_1_DATABASE_AUDIT.md` and `db/preflight/V9_1_integrity_checks.sql` before staging verification. The ERD package is `docs/ERD_V9_1.*`. The preflight SQL is read-only. This pass does not certify PostgreSQL migrations or production readiness; run the checks against a disposable/staging PostgreSQL database and validate all legacy `NOT VALID` constraints before release.

For ERD review, prefer the five domain-specific diagrams listed in `docs/ERD_V9_1.md` rather than the dense full-schema overview.


## V9.2.3 API reliability update

See `docs/V9_2_3_API_RELIABILITY_FOUNDATION.md`, `docs/V9_2_3_TRANSACTION_AUDIT.md` and `docs/V9_2_3_RELEASE_NOTES.md`. V9.2.3 adds optional durable idempotency for mutation APIs, Signed Assertion V2 binding, Backend retry/circuit-breaker examples and transaction-boundary fixes. Apply Flyway V11 after V10. This source-level release is not a production sign-off: PostgreSQL concurrency/load, migration rehearsal, backup/restore and Spring Boot target integration remain acceptance gates.

The V9.5.2 historical mapping is preserved at `docs/WORKFLOW_API_TRACEABILITY_V9_5_2.md`. The current user-supplied Workflow(4) diagram is preserved at `docs/Workflow.drawio`; see `docs/WORKFLOW_API_TRACEABILITY.md` and `docs/V10_0_WORKFLOW_TRACEABILITY.md` for the current DATA-AI-owned support and external owner boundaries. In particular, DATA-AI does not currently implement the full Camunda workflow or DSR/credit decisions.

## V9.3.1 OCR governance foundation

See `docs/V9_3_1_OCR_GOVERNANCE.md`, `docs/V9_3_1_RELEASE_NOTES.md` and `docs/V9_3_1_HANDOFF.md`. V9.3.1 versions the provisional 20-field catalogue and six generic document profile entries, adds conservative classification/field abstention, field format validation, confidence-basis metadata, and the read-only `GET /api/v1/admin/ocr/catalog` endpoint. Apply Flyway V12 after V11. The six generic profile entries are not the six bank-approved layouts; the exact bank templates, final SRS fields and thresholds still require PO/bank sign-off and independent labeled data. Maker review and Camunda routing remain Backend/Camunda responsibilities.

## V9.3.2 Evidence, Provenance & Reconciliation

See `docs/V9_3_2_EVIDENCE_RECONCILIATION.md`, `docs/V9_3_2_RELEASE_NOTES.md`, `docs/V9_3_2_HANDOFF.md`, `docs/ERD_V9_3_2_EVIDENCE.md` and the updated `docs/WORKFLOW_API_TRACEABILITY.md`. V9.3.2 adds V13 append-only case-scoped evidence manifests, stored-byte re-hash/provenance API, PDF–CSV statement balance candidates, linked transaction duplicate candidates and append-only Maker review records. It does **not** verify account ownership/authenticity, auto-delete duplicate transactions, decide income eligibility/DSR/credit, or complete Camunda tasks. Apply Flyway V13 after V12; backfill old documents using `scripts/backfill_evidence_manifest.py` in dry-run mode first. Live PostgreSQL trigger/FK execution, migration rehearsal, concurrency and target Camunda integration remain acceptance gates.


## V9.4.1 Governance, Versioning & Maker–Checker Freeze

See `docs/V9_4_1_GOVERNANCE_FREEZE.md`, `docs/V9_4_1_RELEASE_NOTES.md`, `docs/V9_4_1_HANDOFF.md`, `docs/ERD_V9_4_1_GOVERNANCE.md` and `docs/WORKFLOW_API_TRACEABILITY.md`. V14 adds immutable per-case evidence/input snapshots, SHA-256, sequential version lineage, append-only Maker/Checker events and database-level write protection while frozen. Maker and Checker must be distinct trusted staff identities. A Checker confirmation is only a DATA-AI evidence/input technical review; it is not credit approval or Camunda task completion. Apply V14 after V13 and rehearse on disposable PostgreSQL first. Malware scanning, full Camunda integration, Override/Named Authority, full analysis calculations, JSON/CSV/PDF export, G3/G4 and reopen remain open workflow work.


## V9.4.2 Audit, Override & Policy Exception Governance

See `docs/V9_4_2_AUDIT_OVERRIDE_AUTHORITY.md`, `docs/V9_4_2_RELEASE_NOTES.md`, `docs/V9_4_2_HANDOFF.md`, `docs/ERD_V9_4_2_AUDIT_OVERRIDE.md` and `docs/WORKFLOW_API_TRACEABILITY.md`. V15 adds a per-case sequential hash-chained audit ledger with verification API; immutable Maker Override/Policy Exception proposals bound to a V14 snapshot hash and same-case evidence references; and append-only independent Named Authority approval/rejection records with Backend/SSO grant/scope references and optional approval expiry. The approval record never changes the V14 snapshot, applies a policy change, executes an override or completes a Camunda task. Backend/SSO must validate the named authority grant, scope, limits, assignment and effective dates; the bank policy/Business Engine remains authoritative for applying any approved exception. Apply V15 after V14. Backfill legacy `audit_events` using `scripts/backfill_case_audit.py` in dry-run mode first. PostgreSQL trigger execution, migration, concurrency and authority integration remain staging acceptance gates.


## V9.5.1 Workflow Integration

V9.5.1 adds the DATA-AI integration boundary for Camunda 8: process binding, transactional outbox/inbox, Awaiting Evidence and resubmission impact records, governed reopen, external G3/G4 references, Business Engine override-application receipts and hashed ZIP export (`analysis.json`, `evidence.csv`, `summary.pdf`, `manifest.json`). See `docs/V9_5_1_HANDOFF.md`, `docs/V9_5_1_WORKFLOW_INTEGRATION.md`, `docs/WORKFLOW_API_TRACEABILITY.md` and `docs/ERD_V9_5_1_WORKFLOW.md`.

This is **not** a deployed Camunda or Business Engine integration. BPMN/User Tasks/Timers/DMN, Spring Boot/SSO service wiring, external workers, bank scanner/quarantine, real G3/G4 operational tests, KMS/object-store security and PostgreSQL staging acceptance are still required. DATA-AI does not calculate DSR or make credit decisions.


## V9.5.2 Production Security & Recovery Hardening

- Workflow(3) file safety now includes ClamAV INSTREAM integration through `POST /api/v1/cases/{case_id}/documents/{document_id}/security-scan`. The caller must be a dedicated `DOCUMENT_SCANNER` identity in the signed assertion and same bank scope; bank scope is rechecked after row lock. Unknown scanner reply/outage fails closed.
- The scanner hashes the exact bytes streamed to ClamAV; the route compares that stream digest with the database SHA-256 and a post-scan storage rehash. OCR copies bytes through a no-follow file descriptor, verifies the copy against the same scan digest and parses only that private read-only copy, closing the scan-to-OCR path replacement window.
- Uploaded PDF/JPEG/PNG/CSV bytes must match their file signatures/content; image dimensions are capped at 40 million pixels. A file cannot enter OCR until an append-only `V1_CLAMAV` event binds CLEAN verdict to the exact current SHA-256 and scanner version. INFECTED files are moved to private quarantine and marked BLOCKED.
- V17 adds `scanned_sha256` and `attestation_version`, immutable scan events and database triggers enforcing document scan state. Legacy CLEAN/EXEMPT status is not trusted for Checker readiness; legacy CLEAN files may be re-scanned.
- Production/staging configuration requires non-placeholder internal/database secrets, non-placeholder signed assertion keys, PostgreSQL `sslmode=verify-full` plus an absolute readable `sslrootcert`, a private ClamAV host and separate non-placeholder platform-KMS references for storage/export volumes. These KMS references are deployment assertions; DATA-AI does not implement application-level encryption in V9.5.2.
- API runs non-root with read-only root filesystem, dropped capabilities, bounded process/file descriptors, `no-new-privileges`, local-only published ports by default, security headers, request-size guard and `/ready` checks for Flyway V17 and scanner availability.
- Backup/restore and storage-integrity scripts are included. They do not replace a coordinated database + file-volume snapshot, proof of KMS encryption, or a tested DR drill.
- See `docs/V9_5_2_PRODUCTION_HARDENING.md`, `docs/V9_5_2_HANDOFF.md`, `docs/V9_5_2_RELEASE_NOTES.md`, `docs/ERD_V9_5_2_PRODUCTION.md` and `docs/WORKFLOW_API_TRACEABILITY.md`.


## V10.0 DATA-AI workflow completion — PostgreSQL/Flyway V18

V10.0 completes the DATA-AI-owned side of the supplied Workflow(4) while preserving the existing OCR and document-safety pipeline. It adds a Backend/SSO scope-consent attestation mirror, immutable applicant declaration revisions for household/employment/expenses/liabilities/salary accounts, Maker review records anchored to source documents, six-month observed-income-ledger review gates, a structured DATA-AI readiness response, and a canonical SHA-256-bound input bundle for the external Financial Engine. It also records external proposed-schedule references and receipts binding the completed calculation to the consumed bundle, product version/hash, policy version/hash and exactly three scenario references (BASELINE, STRESS_1, STRESS_2).

Apply `V18__data_ai_workflow_input_handoff.sql` after V17. V1–V17 are retained unchanged. Flyway remains the sole schema owner; application startup does not call SQLAlchemy `create_all()` and no Alembic migration was introduced. `REQUIRED_FLYWAY_VERSION=18` and production `REQUIRE_SCOPE_CONSENT=true` are required. See `docs/V10_0_DATA_AI_HANDOFF.md`, `docs/V10_0_DATA_DICTIONARY.md`, `docs/V10_0_WORKFLOW_TRACEABILITY.md`, `docs/ERD_V10_0_DATA_AI.md` and `docs/FLYWAY_POSTGRESQL.md`.

**Authority boundary:** DATA-AI stores source evidence, OCR candidates, Maker input-review decisions and exact input/output references. It does not calculate eligible income, expense floors, consolidated debt, installments, residual, DSR, stress values or policy outcomes; it does not approve/reject a loan. Backend/SSO owns authoritative identity and consent; Camunda 8 owns BPMN, DMN, User Tasks and Timer execution; the external Financial Engine owns all financial calculations and policy evaluation. Camunda variables must remain opaque IDs and routing state only.

The OCR source implementation is preserved: native PDF text extraction and existing scanned-document OCR paths remain in place, with the existing provisional generic layout/field catalog, bounding-box provenance and abstention behavior. The six generic profiles are not yet bank-approved templates. Do not represent OCR quality targets as achieved without the independent bank-labeled validation set described in the project report.

The V10.0 source tests and PostgreSQL-dialect DDL compilation do not substitute for a live Flyway V18 run. Before staging/production, execute V18 on a disposable PostgreSQL clone, test all append-only and same-case triggers/FKs, re-run OCR/scan integration, test duplicate callback/retry and concurrent version/bundle creation, and verify coordinated database + document-store backup/restore. Real Backend/SSO, Camunda BPMN/DMN, ClamAV, Business Engine, KMS and bank release gates remain external integrations unless separately deployed and tested.
