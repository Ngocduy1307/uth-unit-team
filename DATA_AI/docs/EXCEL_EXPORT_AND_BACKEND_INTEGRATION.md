# Customer form, PostgreSQL, Flyway and Excel export

## Request flow

1. Customer browser submits the application form to the Spring Boot public API.
2. Backend authenticates the customer, verifies consent, validates the approved form and creates its canonical customer/application records.
3. Backend calls DATA-AI `POST /api/v1/customers` to mirror the approved customer profile, address and employment fields into the `data_ai` schema.
4. Backend calls `POST /api/v1/customers/{customer_id}/applications` with bank code, case reference, requested amount/term/purpose, active form version and consent reference. DATA-AI creates `cases`, `loan_applications` and an immutable `applicant_submissions` snapshot in one transaction.
5. DATA-AI processes uploaded documents and stores OCR fields, source anchors, transactions, matching suggestions and data-quality findings.
6. Staff browser calls Spring Boot's staff export route. Backend checks staff role and bank scope, then calls DATA-AI `GET /api/v1/admin/exports/excel` using its internal service token, signed service assertion, and trusted actor headers.
7. DATA-AI generates the XLSX from PostgreSQL, records `export_jobs` and a management audit event, then streams the workbook to Backend. This legacy GET has a write side effect and must not be automatically retried; a future export command should be POST + idempotency key with a separate download resource.

For retryable mutation calls, Backend must persist one logical command key and send the same `Idempotency-Key` on every retry. The Spring example signs this key with Signed Assertion V2 and serializes the request bytes once. See `docs/V9_2_3_API_RELIABILITY_FOUNDATION.md` for state handling and reconciliation rules. Do not automatically retry side-effecting GET routes (including Excel export).

The browser must never connect directly to PostgreSQL or DATA-AI. Never expose `INTERNAL_SERVICE_TOKEN` to JavaScript. Backend must overwrite `X-Actor-Id`, `X-Actor-Roles`, and `X-Bank-Id`; do not forward same-named browser-supplied headers. Keep DATA-AI on a private network and allow calls only from Backend.

## Flyway migrations

- V1: core cases, documents, OCR fields, transactions, processing results and audit events.
- V2: source inventory, field mapping registry, payroll evidence, matching candidates, monthly ledger, data quality and pipeline runs.
- V3: immutable applicant form snapshots and export audit metadata.
- V4: bank organizations/branches, customer profiles/addresses/employment, loan applications, staff/RBAC, configurable form definitions and management audit logs.
- V10: one-time nonce registry for Signed Assertion replay protection.
- V11: durable API idempotency request/response ledger.

Apply all pending migrations with `docker compose run --rm flyway`. Never edit an already-applied migration; create the next version. Flyway is the only schema migration owner for `data_ai`. Do not use SQLAlchemy `create_all()` or Alembic against the same tables.

## Main DATA-AI endpoints

### Create customer mirror

`POST /api/v1/customers` (internal token required)

Example body:

```json
{
  "customer_code": "CUS-000001",
  "full_name": "Nguyen Van A",
  "phone": "0901234567",
  "email": "customer@example.com",
  "date_of_birth": "1995-05-20",
  "gender": "OTHER",
  "identity_type": "CCCD",
  "identity_last4": "1234",
  "marital_status": "SINGLE",
  "dependents_count": 0,
  "address": {
    "address_type": "RESIDENTIAL",
    "country_code": "VN",
    "province_name": "Ho Chi Minh City",
    "street_address": "Example address",
    "is_primary": true
  },
  "employment": {
    "employment_type": "SALARIED",
    "employer_name": "Example Company",
    "job_title": "Staff",
    "monthly_income_declared": 18000000,
    "income_currency": "VND",
    "is_current": true
  }
}
```

The sample is illustrative. Backend generates `customer_code`, checks the customer's identity/consent and sends only fields approved for the current purpose. Full national ID is intentionally not stored by this starter.

### Create loan application and case

`POST /api/v1/customers/{customer_id}/applications` (internal token required)

Example body:

```json
{
  "external_case_id": "CASE-000001",
  "bank_id": "DEMO-BANK",
  "requested_amount": 80000000,
  "requested_term_months": 24,
  "loan_purpose": "Household expenses",
  "product_code": "PERSONAL_UNSECURED",
  "form_version": "1.0",
  "consent_reference": "CONSENT-REFERENCE-FROM-BACKEND",
  "form_data": {"additional_customer_field": "example"}
}
```

`bank_id` must match an active `bank_organizations.bank_code`. The customer is linked to that bank; a different bank cannot be selected for an already bank-scoped customer. The current active form version is checked and required fields/types/rules are validated. DATA-AI records a request only; no credit decision is made.

### Customer updates

- `GET /api/v1/customers/{customer_id}` reads the mirror.
- `GET /api/v1/customers` lists records for internal Backend use.
- `PATCH /api/v1/customers/{customer_id}` updates profile fields and optionally primary address/current employment. Changes are audited.

### Staff and administration

- `POST /api/v1/internal/staff-sync`: mirror staff identity/roles from Backend/SSO. No password or credential is stored.
- `POST /api/v1/admin/banks`: System Admin creates a bank organization.
- `POST /api/v1/admin/banks/{bank_id}/branches`: Bank Admin manages branches only within its bank; System Admin can manage platform-wide.
- `GET /api/v1/admin/staff`: admin-only staff directory view.
- `GET /api/v1/admin/forms/{form_code}`: read active form version and field definitions.
- `PUT /api/v1/admin/forms/{form_code}`: publish a new version; trusted BANK_ADMIN/SYSTEM_ADMIN only. Existing snapshots remain unchanged.
- `GET /api/v1/admin/audit-logs`: bank-scoped admin audit history (System Admin can inspect across banks).

Roles seeded by V4: `BANK_STAFF`, `DATA_AI_STAFF`, `BANK_ADMIN`, `SYSTEM_ADMIN`. `staff_users` stores staff identities; role assignments live in `staff_user_roles`. Customer identities live separately in `customer_profiles`. Authentication remains Backend/SSO-owned.

## Staff Excel export

`GET /api/v1/admin/exports/excel[?case_id=<uuid>]`

Headers supplied only by trusted Backend:
- `X-Internal-Service-Token`
- `X-Service-Assertion` (production; signed over the final request bytes)
- `X-Actor-Id`
- `X-Actor-Roles`: `STAFF`, `BANK_STAFF`, `DATA_AI_STAFF`, `BANK_ADMIN`, `SYSTEM_ADMIN` or `ADMIN`
- `X-Bank-Id`: bank code

The query is constrained to the caller's bank. An optional case outside that bank returns 404. Export history is available from `GET /api/v1/admin/exports/history`. Workbook bytes are not stored in PostgreSQL; only export metadata and per-sheet row counts are retained.

## Workbook sheets

- `Cases`
- `Customers`
- `Customer Addresses`
- `Customer Employment`
- `Loan Applications`
- `Applicant Submissions`
- `Applicant Form Data`
- `Documents`
- `Extracted Fields`
- `Transactions`
- `Processing Summary`
- `Pipeline Runs`
- `Source Inventory`
- `Field Mapping`
- `Data Quality`
- `Payroll Evidence`
- `Earning Match Candidates`
- `Income Ledger`

`Export Notices` is added if any sheet reaches `EXPORT_MAX_ROWS_PER_SHEET`; a warning is written in the affected sheet. Narrow the export filter to retrieve remaining data in additional workbooks. Strings beginning with spreadsheet formula characters are escaped.

## Frontend integration

- `examples/frontend/CustomerApplicationForm.tsx` demonstrates the customer form posting to Spring Boot `/api/customer-applications`.
- `examples/frontend/StaffExcelExportButton.tsx` demonstrates the staff download from Spring Boot `/api/staff/data-exports/excel`.
- `examples/frontend/dataAiClient.ts` includes generic upload/read/export helpers.

The example Spring Boot adapter is `examples/backend-spring/DataAiClient.java`. Backend must implement the public routes, map the customer form to the DATA-AI payloads, generate opaque customer/case identifiers, verify consent, derive bank and staff context from authenticated server-side state, and stream the XLSX response. Exact DTO names/routes must be adapted to the team's actual Backend repository.
