# Customer, staff, admin and PostgreSQL/Flyway design

## Runtime topology

- Customer browser -> Spring Boot public API -> DATA-AI internal API.
- Staff browser -> Spring Boot staff API -> DATA-AI internal API.
- PostgreSQL is the persistent store; Flyway is the only schema migration owner for `data_ai`.
- DATA-AI does not own passwords, login sessions, MFA or customer authentication. Spring Security/SSO remains authoritative.

## Table groups

### Customer and application
- `customer_profiles`: customer identity/profile fields. Full government ID is deliberately not stored; only document type and last four characters are present in this starter. Use a separately reviewed encryption/tokenization design if full ID is legally required.
- `customer_addresses`: multiple residential/permanent/contact addresses.
- `customer_employments`: employment history and self-declared income.
- `loan_applications`: requested product, amount, term and purpose. This records a request only; it does not approve/reject or calculate affordability.
- `cases`: DATA-AI processing case, linked to a customer and bank code.
- `applicant_submissions`: immutable versioned JSON snapshot of the customer form submitted for the case.

### Staff, admin and management
- `bank_organizations`, `bank_branches`: organization and branch reference data.
- `staff_users`: staff directory mirror from Backend/SSO; no password or credential is stored.
- `access_roles`, `staff_user_roles`: RBAC role definitions and assignments. Seed roles: BANK_STAFF, DATA_AI_STAFF, BANK_ADMIN, SYSTEM_ADMIN. Customer identity is held in `customer_profiles`; customer login/role is owned by Backend/SSO.
- `management_audit_logs`: staff/admin changes, actor, target and before/after metadata.
- `form_definitions`, `form_field_definitions`: versioned, customizable form configuration. Publish a new version instead of editing historical submitted snapshots.

### DATA-AI evidence
- `documents`, `extracted_fields`, `transactions`, `processing_results`, `data_quality_issues`, `payroll_evidence`, `earning_match_candidates`, `income_ledger_months`, `audit_events`.
- `export_jobs`: export metadata only; workbook content is not stored in the database.

## Flyway migrations

`V1` and `V2` create the original evidence model. `V3` adds form snapshots and export audit. `V4` adds customer, application, bank, staff/RBAC, configurable forms and management audit tables. Never edit an already-applied migration. Add `V5__...sql` for future changes.

## API endpoints

All DATA-AI routes are internal service endpoints. Browser clients must never receive `INTERNAL_SERVICE_TOKEN`.

- `POST /api/v1/customers`: create customer profile and optional address/employment.
- `GET /api/v1/customers`, `GET /api/v1/customers/{id}`: internal customer reads.
- `PATCH /api/v1/customers/{id}`: update profile; changes are audited.
- `POST /api/v1/customers/{id}/applications`: create case + loan application + immutable submission snapshot. Requires an active `bank_organizations.bank_code` matching `bank_id`.
- `POST /api/v1/internal/staff-sync`: mirror a staff member and role assignments from Backend/SSO.
- `GET /api/v1/admin/staff`: admin-only staff directory view.
- `GET /api/v1/admin/forms/{form_code}`: read active form version and field definitions.
- `PUT /api/v1/admin/forms/{form_code}`: publish a new version; trusted BANK_ADMIN/SYSTEM_ADMIN only.
- `GET /api/v1/admin/audit-logs`: admin-only management audit history.
- `GET /api/v1/admin/exports/excel`: BOTH scope workbook, bank-scoped and staff-only.
- `GET /api/v1/admin/exports/history`: export audit history.

## Trust boundary

`X-Actor-Id`, `X-Actor-Roles`, and `X-Bank-Id` are trusted internal headers only when populated by Spring Boot from its authenticated security context. Production requests must carry both `X-Internal-Service-Token` and the request-bound `X-Service-Assertion` described in `V9_2_2_SIGNED_SERVICE_ASSERTIONS.md`; DATA-AI must remain reachable only from the Backend network. Never forward identity headers supplied by the browser. Keep TLS, secret rotation, rate limiting, encrypted backups and security review as deployment requirements. Do not expose DATA-AI directly to the public internet.

## Local database viewer

Run `docker compose --profile tools up -d`. Open pgAdmin at `http://localhost:5050` using credentials from `.env`. Register a server:
- Host: `postgres` when connecting from pgAdmin container, or `localhost` from desktop DBeaver/pgAdmin.
- Port: `5432`
- Database: `income_assistant`
- Username/password: `POSTGRES_USER` / `POSTGRES_PASSWORD`
- Schema: `data_ai`

Use `python -m scripts.seed_demo` after migrations to insert synthetic demo records. These are not real people or bank data.


## Customer intake v1.1 and login boundary

- V6 adds `customer_employments.income_basis` (NET/GROSS), makes uncollected `dependents_count` nullable, adds the 6–36 month check for new/changed loan records, and publishes form version 1.1.
- V1.0 form definitions and prior `applicant_submissions` are retained. Do not delete existing fields/tables merely because the initial form no longer displays them.
- Initial intake does not ask for gender, marital status, dependents, full CCCD, full bank account number, detailed expenses or creditor-by-creditor debts.
- Expense, liability and salary-account declarations are deferred and remain available in V5 tables.
- Customer/staff/admin authentication, passwords, MFA and sessions belong to Spring Boot/SSO. See `BACKEND_AUTHORIZATION_CONTRACT.md`.
- The current DATA-AI service must remain private. Before multi-bank use, add tenant scoping inside its customer/case/document/export queries as defense in depth; Backend authorization alone is not a substitute for service-side scope checks.
