# DATA-AI V10.0 — Release Notes

## Scope

Completes the DATA-AI-owned portion of Workflow(4) while preserving the existing OCR and document-safety implementation. PostgreSQL remains the data store and Flyway remains the sole migration authority. V18 is additive; V1–V17 are not edited.

## Changes

1. Added V18 PostgreSQL schema with seven append-only workflow input/handoff tables.
2. Added Backend/SSO scope-consent attestation mirror with bank-scope validation and idempotent replay.
3. Added immutable versioned declaration intake for HOUSEHOLD, EMPLOYMENT, EXPENSES, LIABILITIES and SALARY_ACCOUNTS.
4. Added Maker input-review records with source-document anchoring for OCR, payroll, payroll-to-bank matches, statement transactions and observed income ledger.
5. Added six-month DATA-AI readiness assessment and advisory Camunda route hint. Each month requires trusted statement coverage, payslip evidence, Maker review, confirmed payroll-to-bank match, observed income-ledger row and Maker confirmation.
6. Added canonical SHA-256-bound Financial Engine input bundle. Sensitive free-text review comments and reviewer identifiers are excluded; direct identifiers are minimized and missing values remain null.
7. Added external proposed schedule references and Business Engine receipts bound to exact bundle, schedule, product/policy/calculation references and hashes.
8. Export now checks the latest Business Engine receipt (not merely the latest COMPLETED row), binds the exact schedule ID and requires the receipt/bundle/schedule to exist in the Checker-confirmed snapshot.
9. Added idempotent replay checks for Backend decision references, declaration client request IDs, schedule references, calculation references and identical input bundles.
10. Added V10.0 Data Dictionary, ERD, Workflow(4) traceability and Flyway staging instructions.
11. Financial Engine payload now excludes free-text Maker review reasons and staff identifiers; it retains decision codes and opaque evidence references. Monthly ledger review uses payment date or pay-period end only to locate source documents, and readiness never fabricates a missing analysis window.

## Preserved

- Existing PyMuPDF/native PDF text extraction and scanned-document OCR paths.
- Existing 6 generic provisional layout profiles and 20 provisional field labels.
- Bounding-box/page/CSV row provenance, confidence basis and abstention.
- ClamAV exact-byte scan gate, quarantine behavior, manifest/provenance, reconciliation, Maker–Checker, audit/override, Camunda outbox/inbox and export package code.

## Verification

- Regression suite: **230 passed on the final release ZIP**.
- Python compile: passed.
- SQLAlchemy PostgreSQL dialect DDL compile across 64 mapped tables (724 columns) and 85 ORM indexes: passed.
- OpenAPI runtime artifact: **66 paths**, API version 10.0.0; JSON Schema contracts for readiness and Financial Engine handoff included.
- Workflow(4).drawio copied byte-for-byte; SHA-256 matches user upload.
- Docker Compose YAML, shell syntax, archive integrity and SHA-256 packaging checks: run in release preparation.

## Not a production sign-off

V18 has not been executed by Flyway against a live PostgreSQL server in this authoring environment. No live Camunda 8, Backend/SSO, Business Engine, ClamAV, KMS or bank storage infrastructure was available. No 400-case independent OCR validation, 1,000-scenario math validation, 10,000-concurrent Camunda test, performance target or G3/G4 pilot was executed. The generic OCR catalog remains provisional and the external Financial Engine remains the owner of all financial calculations and policy outcomes.
