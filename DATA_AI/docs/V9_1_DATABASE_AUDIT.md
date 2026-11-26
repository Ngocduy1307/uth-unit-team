# V9.1 Database and ORM Alignment Audit

## Release intent

V9.1 is a database-integrity and persistence-mapping hardening pass. It does not change credit policy, affordability calculations, Camunda routing, customer authentication, or authoritative Backend authorization.

## Reviewed baseline

- Input package: DATA_AI V9.0 ZIP and Workflow.drawio supplied with this task.
- Flyway migration chain at the V9.1 audit baseline: V1 through V9. The current V9.2.2 package adds V10 for signed-assertion replay protection.
- ORM: SQLAlchemy 2.x declarative models in `app/models.py`.
- Database: PostgreSQL 16, schema `data_ai`, Flyway is the only migration owner.
- Existing automated test baseline before this pass: 32 tests passed.
- PostgreSQL execution could not be performed in this environment because Docker is unavailable and no target PostgreSQL connection was supplied.

## Workflow-to-data coverage

| Workflow stage | Existing persistence support | V9.1 review |
|---|---|---|
| Intake, manifest/hash, file checks | `cases`, `documents`, `audit_events`, document hash uniqueness | Core metadata exists. Malware scan is only a status model, not a functioning scanner. |
| Consent and scope | `consent_events` in V8 | Event table exists in SQL; backend remains responsible for identity, notice and lawful-basis checks. |
| Document security | V8 document security columns and `document_security_events` | SQL existed but several fields/tables were absent from ORM mapping before V9.1. ORM coverage added. |
| OCR and extraction | `extracted_fields`, `processing_results`, `pipeline_runs` | V9 coordinate/method provenance is mapped. Human review and approved layouts remain incomplete. |
| Income/payroll evidence | `payroll_evidence`, `earning_match_candidates`, `income_ledger_months` | V8 source-field references and review metadata are now mapped. This is evidence aggregation, not accepted income calculation. |
| Expenses and liabilities | customer declaration tables | V8 idempotency/update columns now mapped. Business consolidation remains outside DATA-AI. |
| Versioned declarations | `customer_declaration_revisions` | V8 revision provenance fields now mapped. Append-only enforcement remains database-trigger based. |
| Maker/Checker, Freeze, Override | RBAC catalog/history and audit tables | Supporting catalog exists; full workflow state machine and authorization remain Backend/Camunda responsibilities. |
| Export | `export_jobs` and Excel export | Exists; export safety and access controls still require integration/security verification. |
| Reopen, supersede, impact list | Partial version/history foundations | Not implemented as a complete workflow in this service. |

## Findings fixed in this pass

1. `Case` ORM did not expose V8 `bank_organization_id`.
2. `Document` ORM did not expose V8 security, object-storage, retention and legal-hold columns.
3. `PayrollEvidence` ORM did not expose V8 links to exact extracted fields or review metadata.
4. V8 `consent_events` and `document_security_events` had no SQLAlchemy model classes.
5. Four V8 declaration tables did not expose `client_request_id` and `updated_at` in ORM metadata.
6. `customer_declaration_revisions` did not expose V8 customer/idempotency/hash/source provenance columns.
7. Added ORM representations for the V8 composite tenant/customer consistency references and their supporting unique indexes.
8. Added regression tests to prevent these ORM coverage gaps from silently returning.

## Important unresolved database risks

- V8 constraints were intentionally added `NOT VALID`; the target database must validate them after data reconciliation. A successful Flyway migration alone does not prove legacy rows satisfy them.
- V8 uses composite tenant/customer/case foreign keys. Existing ORM mappings are not yet a complete representation of every database constraint and index.
- No PostgreSQL integration run, Flyway validate run, backup/restore drill, or migration rehearsal was possible in this environment.
- PostgreSQL RLS is not enabled. Backend remains the authoritative security boundary; RLS must be designed only after trusted transaction-local tenant context is implemented and tested with pooled connections.
- Local-disk document storage is not encrypted immutable object storage. Malware scanning and parser sandboxing are not implemented.
- Existing API code commits at several route/service boundaries. A complete transaction-boundary and concurrent-idempotency review remains required before production.

## Safe execution sequence for a real database

1. Take and verify a restorable backup/PITR checkpoint.
2. Run `db/preflight/V8_preflight_checks.sql` and retain its output.
3. Apply V1-V9 only through the agreed Flyway owner.
4. Run `db/preflight/V9_1_integrity_checks.sql` and resolve every non-zero issue count.
5. Validate each V8 `NOT VALID` constraint by its exact name after confirming legacy data is clean.
6. Run the API integration suite against a disposable PostgreSQL database, not production.
7. Run backup/restore and rollback/recovery rehearsal before a production release.

## Test result in this workspace

The V9.0 baseline had 32 passing tests. After the ORM alignment changes, 40 tests pass in this workspace. These tests validate Python/model contracts only; they do not replace PostgreSQL/Flyway integration testing.

## ERD artifacts

- `ERD_V9_1.mmd`: Mermaid ER diagram generated from SQLAlchemy metadata.
- `ERD_V9_1.svg` and `ERD_V9_1.png`: rendered views of the same 37 ORM-mapped tables and their mapped FK relationships.
- This is an ORM-mapping ERD, not a claim that every database-side trigger, partial index, `NOT VALID` constraint, or RLS policy is represented. The SQL migrations remain authoritative for those objects.

For readable review, use the five domain-specific ERDs documented in `docs/ERD_V9_1.md`; the single full-schema image is intentionally dense.
