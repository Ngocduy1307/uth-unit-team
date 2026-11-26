# DATA-AI V10.0 — Final DATA-AI Scope Handoff

## Release intent

This release completes the DATA-AI-owned portion of Workflow(4) using PostgreSQL and Flyway. It is built on the supplied V9.5.2 source; the existing OCR, ClamAV file-safety, V13 provenance, V14 Maker–Checker, V15 Audit/Override, V16 workflow integration and V17 scanner controls are preserved. V18 is additive; V1–V17 migration files remain unchanged.

## What DATA-AI owns in this workflow

1. Store immutable original evidence, SHA-256 manifest, byte-bound malware scan attestation and extraction provenance.
2. Run existing native-PDF text extraction, scanned-PDF/image OCR and CSV ingestion; preserve page/row anchors, bbox, confidence basis and abstain.
3. Store versioned applicant declarations for HOUSEHOLD, EMPLOYMENT, EXPENSES, LIABILITIES and SALARY_ACCOUNTS.
4. Store Maker's evidence review for declarations, OCR fields, payroll candidates, earning matches, transactions and six-month observed income ledger.
5. Evaluate DATA-AI technical/input readiness and publish an advisory route hint for Camunda.
6. Build immutable, canonical, SHA-256-bound Financial Engine input bundle.
7. Store external proposed schedule and Business Engine receipt references tied to the exact input bundle/product/policy/calculation versions and hashes.
8. Include V18 handoff records in immutable Maker Freeze/Checker snapshots and produce export package only after the correct engine receipt is reflected in a Checker-confirmed successor version.

## Not owned by DATA-AI

- Applicant/staff authentication, authoritative consent, scope DMN, bank assignment and Maker/Checker task allocation: Backend/SSO.
- BPMN, User Tasks, Timer, incident orchestration, DMN routing and retry worker lifecycle: Camunda 8.
- Eligible income, expense floor, consolidated debt, proposed installment schedule, residual, DSR/Q, stress scenarios and policy decisions: external Financial/Business Engine.
- Final approval/rejection, legal authenticity of documents, interest rate pricing and bank release authorization: Bank systems and delegated authorities.

DATA-AI does not auto-fill missing months with zero, calculate averages for missing evidence, treat OCR candidates as accepted income, or make a lending decision.

## V18 schema

Seven append-only PostgreSQL tables are added:

| Table | Responsibility |
|---|---|
| `case_scope_consent_attestations` | Backend/SSO scope/consent decision mirror and digest |
| `case_input_declaration_revisions` | Immutable applicant declaration section revisions |
| `case_input_declaration_evidence_links` | Same-case document/hash links for each declaration revision |
| `case_input_review_decisions` | Maker decision linked to target and evidence anchors |
| `case_financial_input_bundles` | Readiness and canonical Financial Engine input JSON/hash |
| `case_proposed_schedule_references` | External schedule reference/product version/hash/term |
| `case_business_engine_receipts` | External input/output/product/policy/calculation hashes and scenario refs |

Migration: `db/migration/V18__data_ai_workflow_input_handoff.sql`. Flyway owns schema evolution. The runtime readiness pin is version 18. No Alembic or `Base.metadata.create_all()` is used.

## API surface added in V10.0

| Method | Route | Service role | Purpose |
|---|---|---|---|
| POST | `/api/v1/cases/{case_id}/scope-consent-attestations` | `BACKEND_SCOPE_ATTESTOR` | Persist signed Backend consent/scope decision mirror |
| POST | `/api/v1/cases/{case_id}/declarations/{section_code}/revisions` | `BACKEND_DATA_INGESTOR` | Versioned declaration ingestion |
| GET | `/api/v1/cases/{case_id}/declarations` | Backend/Maker/Checker/Data-AI | Read revisions metadata |
| POST | `/api/v1/cases/{case_id}/input-reviews` | `MAKER` | Maker decision with required source anchors |
| GET | `/api/v1/cases/{case_id}/data-readiness` | Authorized case roles | Technical and six-month readiness |
| POST | `/api/v1/cases/{case_id}/financial-input-bundles` | `DATA_AI_SERVICE` | Create immutable input packet only when READY |
| GET | `/api/v1/cases/{case_id}/financial-input-bundles/{bundle_id}` | `BUSINESS_ENGINE` | Read verified packet |
| POST | `/api/v1/cases/{case_id}/proposed-schedule-references` | `BUSINESS_ENGINE` | Register external schedule ref |
| POST | `/api/v1/cases/{case_id}/business-engine-receipts` | `BUSINESS_ENGINE` | Record calculation result/receipt |
| GET | `/api/v1/cases/{case_id}/business-engine-receipts` | Maker/Checker/Engine/Data-AI | List receipts |

All internal routes require the internal service token and signed assertion, plus case bank-scope checks. Dedicated service routes enforce exact singleton service roles. Maker input review is Maker-only and separate from Checker.

## Readiness rules

- Current latest Backend attestation must say IN_SCOPE and GRANTED.
- The loan application and supported VND product/6–36 month term must exist.
- Maker must confirm latest revision for all five declaration sections. Expense and liability sections explicitly state HAS_ITEMS or NONE.
- Every salary account must cite a trusted statement; Maker confirmation must cite all declared account statements.
- All six statement months must be covered by trusted scanned/manifested evidence.
- Every month needs a payroll evidence candidate, Maker review and confirmed earning match to a bank-credit transaction.
- Every month needs an observed income-ledger row and a separate Maker confirmation. Accepted income remains NULL; DATA-AI does not declare eligibility.
- If PDF and CSV statement documents are both present, all source documents must be in reconciliation runs; current hashes/trust must match; Maker must confirm MATCH; variances/incomplete/abstained runs block.
- All transaction duplicate candidates require Maker disposition. DATA-AI never deletes or nets transaction rows.
- Technical evidence governance and scan attestation must be clear.

`workflow_route_hint` is informational and never authoritative; Camunda/Bank DMN chooses Awaiting Evidence, terminal insufficient evidence, Maker review, Hold or Business Engine handoff.

## External Financial Engine contract

Bundle `DATA_AI_FINANCIAL_INPUT_V1` includes only minimal required inputs, observed payroll/transaction/income-ledger values, evidence document refs/hashes, OCR anchors, Maker reviews, reconciliation outcomes and missing-value policy. Sensitive free-text notes, Maker/evidence review comments, reviewer staff identifiers, employer tax IDs, account holder name, bank names and transaction descriptions are excluded from the engine payload; decision codes and opaque evidence references remain.

The packet explicitly says missing remains null and missing months are not zero. DATA-AI does not compute any affordability metrics. Financial Engine must return references and hashes for product, policy, calculation, output and the BASELINE/STRESS_1/STRESS_2 scenario set. DATA-AI verifies that these references bind to the exact bundle and requested VND product/term.

## Run locally / PostgreSQL

1. Copy `.env.example` to `.env`; configure development-only secrets.
2. Start PostgreSQL via Compose.
3. Start only PostgreSQL first: `docker compose up -d postgres`.
4. Run the migration job: `docker compose run --rm flyway`; review output and confirm `flyway_schema_history` reports V18. Do not run app startup before Flyway succeeds.
5. Verify the Postgres `data_ai` search path and execute the V18 trigger/FK checks on a disposable clone before staging.
6. Enable scanner and consent enforcement, then start the API: `docker compose up -d api`. The Compose API healthcheck uses `/ready`, which verifies the live Flyway version.
7. Configure Backend/SSO, Camunda workers and external Business Engine through separate integration credentials; do not pass PII/amounts in Camunda variables.

See `docs/FLYWAY_POSTGRESQL.md` for clone/staging test list and backup requirements.

## Verification status and limitations

- Source-level unit/regression suite: 230 tests passed in the release verification build.
- Python compile and PostgreSQL dialect SQLAlchemy DDL compilation: passed.
- OpenAPI artifact is regenerated from `app.main:app`; API path count is 66.
- V18 SQL is source-reviewed and contract-tested; it has **not** been executed against a live PostgreSQL server in this authoring environment.
- No live Flyway CLI, Docker, Camunda, SSO, Business Engine, KMS or ClamAV service was available for end-to-end testing.
- No bank-labeled 400-case OCR validation or G3/G4 pilot trial was executed. Existing 6 generic profiles/20 labels remain provisional pending bank PO/SRS approval.
- This is a source-complete DATA-AI candidate, not a production sign-off or credit decision engine.
