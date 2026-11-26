# V8 deployment, preflight and backfill runbook

## Release gate

Do not run V8 on production until: (1) full backup/PITR is verified; (2) V7 migration history is confirmed; (3) a staging restore has passed; (4) application compatibility is deployed or coordinated; (5) the data owner approves the backfill mapping.

## Preflight

```sql
-- Confirm V1-V7 history (adjust schema/table if Flyway is configured elsewhere).
SELECT installed_rank, version, description, success
FROM data_ai.flyway_schema_history
ORDER BY installed_rank;

-- Check whether case customer references exist.
SELECT count(*) AS cases_without_customer
FROM data_ai.cases WHERE customer_id IS NULL;

-- Legacy bank codes that need explicit mapping to bank_organizations.bank_code.
SELECT DISTINCT c.bank_id AS legacy_bank_code
FROM data_ai.cases c
LEFT JOIN data_ai.bank_organizations b ON b.bank_code = c.bank_id
WHERE c.bank_organization_id IS NULL AND b.id IS NULL
ORDER BY 1;

-- Customer/case bank mismatch candidates; investigate before backfill.
SELECT c.id AS case_id, c.bank_id AS legacy_bank_code,
       cp.id AS customer_id, cp.bank_id AS customer_bank_id,
       b.id AS mapped_bank_id
FROM data_ai.cases c
JOIN data_ai.customer_profiles cp ON cp.id = c.customer_id
LEFT JOIN data_ai.bank_organizations b ON b.bank_code = c.bank_id
WHERE b.id IS NOT NULL AND cp.bank_id IS NOT NULL AND cp.bank_id <> b.id;

-- Existing household customer/case mismatches.
SELECT h.id, h.case_id, h.customer_id, c.customer_id AS case_customer_id
FROM data_ai.customer_household_profiles h
JOIN data_ai.cases c ON c.id = h.case_id
WHERE h.customer_id <> c.customer_id;

-- Existing loan application/customer mismatches.
SELECT la.id, la.case_id, la.customer_id, c.customer_id AS case_customer_id
FROM data_ai.loan_applications la
JOIN data_ai.cases c ON c.id = la.case_id
WHERE la.customer_id <> c.customer_id;

-- Salary accounts over proposed cap.
SELECT case_id, count(*) AS account_count
FROM data_ai.customer_salary_accounts
GROUP BY case_id HAVING count(*) > 3;
```

## Bank identifier backfill

Only after a reviewed mapping confirms `cases.bank_id` equals `bank_organizations.bank_code`:

```sql
UPDATE data_ai.cases c
SET bank_organization_id = b.id
FROM data_ai.bank_organizations b
WHERE c.bank_organization_id IS NULL
  AND c.bank_id = b.bank_code;
```

Do not use this update if legacy bank_id values are not guaranteed to equal bank_code. Resolve unmatched codes manually through an approved mapping file.

## Constraint validation

V8 deliberately adds cross-record foreign keys as `NOT VALID` so legacy inconsistencies do not abort the migration. After the preflight queries return zero unresolved rows, validate individually:

```sql
ALTER TABLE data_ai.cases VALIDATE CONSTRAINT fk_cases_bank_organization;
ALTER TABLE data_ai.cases VALIDATE CONSTRAINT fk_cases_customer_bank_scope;
ALTER TABLE data_ai.loan_applications VALIDATE CONSTRAINT fk_loan_app_case_customer_consistency;
ALTER TABLE data_ai.customer_household_profiles VALIDATE CONSTRAINT fk_household_case_customer_consistency;
ALTER TABLE data_ai.consent_events VALIDATE CONSTRAINT fk_consent_case_customer;
ALTER TABLE data_ai.customer_declaration_revisions VALIDATE CONSTRAINT fk_declaration_revision_case_customer;
```

The five payroll source-field constraints and two document checks can also be validated after data checks. If validation fails, investigate and remediate; do not drop the constraint silently.

## Application changes required before production use

- Update SQLAlchemy models to include all V8 columns/tables/constraints.
- Add Pydantic schemas and authenticated API routes for consent event ingestion, declarations and review actions. Do not expose raw database writes to Frontend.
- Require UUID `client_request_id` for new declaration writes and handle unique conflicts as idempotent retries.
- Ensure `customer_declaration_revisions` is written as a complete section snapshot and never updated/deleted by application code.
- Enforce authorization in Backend/SSO; DATA-AI must derive bank/case scope from trusted server-side context, not client-supplied headers alone.
- Do not mark documents CLEAN or process them until private object storage, MIME/magic-byte validation, malware scanner and fail-closed policy are integrated.
- Store only opaque object keys; no public URLs. Define encryption, key rotation, retention, legal hold, deletion and restore procedures with security/legal owners.
- Update OpenAPI, JSON contracts, export sheets and integration tests. Existing V7 API contracts do not automatically expose V8 functionality.
- Configure connection pooling, TLS, secret rotation, least-privilege DB roles, backups/PITR, monitoring, alerting and incident response for PostgreSQL production.

## Rollback

V8 is additive, but triggers and constraints can affect writes. Prefer forward-fix. If rollback is approved, stop application writes first, inspect dependent rows and only then drop V8 objects using a reviewed rollback script. Do not drop new columns/tables if they contain production data. Do not roll back V1-V7.
