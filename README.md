# UNIT DATA-AI Service

Python FastAPI service with PostgreSQL 16, Flyway SQL migrations, customer/application data mirror, document evidence processing, staff/RBAC metadata, configurable forms and staff-only Excel export.

## 1. Run the complete stack (recommended)

Requirements: Docker Desktop with Docker Compose v2.

```powershell
Copy-Item .env.example .env
# Edit .env and set strong local passwords / INTERNAL_SERVICE_TOKEN
docker compose up --build -d
```

Services:
- API + Swagger: http://localhost:8001/docs
- Health: http://localhost:8001/health
- PostgreSQL: localhost:5432, database `income_assistant`, schema `data_ai`

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

Run migrations with the configured Flyway service after backing up the development database. Do not edit an already-applied migration; create V6 for subsequent changes. Production migration ownership must be agreed with the Backend/database owner.
