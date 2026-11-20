# Implementation report: PostgreSQL, Flyway, customer/staff domain and Excel export

## Scope in this source version

- Added Flyway V4 for bank organizations/branches, customer profiles, addresses, employment, loan applications, staff directory, role assignments, configurable forms and management audit logs.
- Added SQLAlchemy ORM mappings for all 27 tables created across Flyway V1-V4.
- Added internal APIs for customer creation/read/update, loan application creation, staff synchronization, bank/branch management, configurable form versions and management audit history.
- Added server-side dynamic form validation for required fields, supported data types, basic length/range/pattern/option rules.
- Added customer/profile/application sheets to the Excel export, alongside DATA-AI evidence, OCR, transaction, source mapping, pipeline and quality sheets.
- Added React examples for customer form and staff export; browser talks only to Spring Boot.
- Added Docker Compose API, PostgreSQL, Flyway and optional pgAdmin services, plus synthetic demo seed and database verification scripts.

## Database domains

Customer: `customer_profiles`, `customer_addresses`, `customer_employments`.
Application: `cases`, `loan_applications`, `applicant_submissions`.
Staff/Admin: `staff_users`, `access_roles`, `staff_user_roles`, `management_audit_logs`.
Bank management: `bank_organizations`, `bank_branches`.
Configurable forms: `form_definitions`, `form_field_definitions`.
DATA-AI: `documents`, `extracted_fields`, `transactions`, `processing_results`, `pipeline_runs`, `source_inventory`, `field_mapping_registry`, `data_quality_issues`, `payroll_evidence`, `earning_match_candidates`, `income_ledger_months`, `audit_events`.
Export: `export_jobs`.

## Workbook contents

`Cases`, `Customers`, `Customer Addresses`, `Customer Employment`, `Loan Applications`, `Applicant Submissions`, `Applicant Form Data`, `Documents`, `Extracted Fields`, `Transactions`, `Processing Summary`, `Pipeline Runs`, `Source Inventory`, `Field Mapping`, `Data Quality`, `Payroll Evidence`, `Earning Match Candidates`, `Income Ledger`. `Export Notices` is added if a per-sheet row limit is reached.

## Verification performed in this environment

- Python `compileall`: passed.
- Unit/contract tests: 12 passed.
- FastAPI OpenAPI generation: 20 paths generated.
- SQL migration vs ORM metadata comparison: all 27 mapped tables have corresponding Flyway `CREATE TABLE` statements.
- Docker Compose YAML parsed successfully.
- Workbook generation tested with a mock empty database session; formula-injection escaping and required worksheets verified.

## Not verified here

Docker/Podman, PostgreSQL server, `psql` and Flyway CLI were unavailable in the execution environment. Therefore actual PostgreSQL startup, Flyway execution against PostgreSQL, seeded database query and live XLSX download have not been executed here. Run the included Compose stack and `scripts/check_database.py` in your machine before relying on it. Real Spring Boot/React repository integration also remains to be aligned with your team's actual code.

## Security and scope boundaries

- Backend/SSO owns authentication, customer identity proofing, consent verification and staff authorization. DATA-AI stores a mirror/snapshot, not passwords or sessions.
- Full national identity numbers are not stored. This starter keeps identity type and last four digits only.
- Staff/admin identities share `staff_users`; access is separated by `access_roles` and `staff_user_roles`, avoiding duplicate admin credential tables.
- Export is bank-scoped and internal-token protected. Backend must derive actor/role/bank headers from the authenticated server-side context and never trust browser headers.
- DATA-AI records requested loan amount/term/purpose only. It does not calculate DSR, approve/reject loans or disburse funds.
- This is a runnable development/integration baseline, not a production-certified banking system. Production security, privacy, retention, malware scanning, OCR benchmarks and approved bank schemas remain release gates.
