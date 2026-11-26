# DATA-AI ZIP review and change log

## Executive decision

Simplify the **customer form**, not the evidence database. The project has separate data layers for customer declarations, OCR evidence, transaction rows, monthly salary ledger, source lineage and audit. Deleting those tables to make the form shorter would break the RFP workflow.

This reviewed copy:
- Publishes customer intake form version 1.1 through a new additive Flyway migration.
- Adds `customer_employments.income_basis` to persist NET/GROSS declaration basis.
- Makes `customer_profiles.dependents_count` nullable so an uncollected value is not silently treated as zero.
- Adds a new 6–36 month constraint for new/changed applications without forcing legacy rows to pass validation.
- Adds Maker and Checker to the role catalogue.
- Updates the React example to remove detailed expense/debt questions from initial intake and defer them to a later step.
- Adds Backend mapping and authorization contracts.
- Retains existing tables, old form version 1.0, and historical submissions.

## Minimal customer-facing form

### Required at initial submission
1. Full legal name.
2. Date of birth.
3. Phone number.
4. Vietnam residency declaration.
5. Province/city and ward/commune.
6. Current employer.
7. Declared monthly salary and NET/GROSS basis.
8. Confirmation salary is received by bank transfer.
9. Requested amount in VND.
10. Requested term from 6 to 36 months.
11. Loan purpose.
12. Consent.

### Optional
- Email.
- Job title.
- Street address details.

### Deferred to later secure steps
- Upload payslips and bank statements covering six complete calendar months.
- Declare salary account(s), maximum three; bank staff verifies ownership.
- Declare expenses and liabilities when required by the bank checklist.
- Capture creditor-level liability details and supporting evidence only when relevant.
- Additional KYC details through the bank-controlled KYC service, not this DATA-AI intake.

The initial form does not ask gender, marital status, dependents, full CCCD, full bank account number, employer tax code/contact/address, employment start/end dates, household profile, itemized expenses or creditor-by-creditor debt.

## Table disposition

### Keep: core and evidence tables
- `cases`, `loan_applications`, `customer_profiles`, `customer_addresses`, `customer_employments`, `applicant_submissions`.
- `documents`, `extracted_fields`, `transactions`, `payroll_evidence`, `earning_match_candidates`, `income_ledger_months`.
- `processing_results`, `pipeline_runs`, `data_quality_issues`, `source_inventory`, `field_mapping_registry`.
- `audit_events`, `management_audit_logs`, `export_jobs`.
- `customer_expense_declarations`, `customer_liability_declarations`, `customer_salary_accounts`, `customer_declaration_revisions`.

Reason: these tables preserve immutable evidence, source anchors, monthly coverage, reconciliation candidates, human review, provenance and auditability. They are not all customer form fields.

### Keep but do not expose as customer inputs
- `customer_profiles.gender`, `marital_status`, `identity_type`, `identity_last4`, `preferred_contact_method`: not required on the initial form. Keep nullable for historical records or a later bank-approved lawful purpose.
- `customer_employments.employer_tax_code`, `work_phone`, `work_address`, `industry`, `start_date`, `end_date`: do not ask initially. OCR/staff enrichment may be useful later.
- `customer_household_profiles`: do not collect or populate unless the bank signs off a documented necessity. It can be disabled in the initial MVP UI; do not delete without checking references and existing data.
- `bank_branches`: optional for a single-bank pilot but useful for staff scoping. Keep until Backend confirms no branch-level authorization/reporting requirement.
- `form_definitions`, `form_field_definitions`: keep only if Bank Admin needs runtime form configuration. If the team decides forms are code-versioned only, this configurable-form feature can be removed in a separate coordinated refactor, not by deleting tables in this migration.
- `staff_users`, `access_roles`, `staff_user_roles`: these are mirrors/catalogue support, not the authoritative login system. Long-term, move authoritative role assignments and permission checks to Backend/SSO. Keep a minimal staff reference mirror only if DATA-AI needs actor display/audit metadata.

## Work-item alignment from the Jira screenshot and sprint workbook

The visible DATA-AI issues are KAN-92, KAN-93, KAN-94, KAN-95, KAN-109, KAN-120, KAN-154, KAN-155, KAN-156 and KAN-157, plus KAN-73.

Repository implementation notes already state:
- KAN-92: generic source types and transaction extraction exist; two bank-approved CSV schemas remain pending.
- KAN-93: dictionary/catalog and source/mapping read APIs exist; final approved dictionary and full lineage UI remain.
- KAN-94 / KAN-73: idempotent processing and evidence metadata exist; immutable object storage and full review/monitoring remain.
- KAN-95: observed salary-candidate ledger and match suggestions exist; accepted income, expense/debt consolidation and DSR are intentionally not implemented in DATA-AI.
- KAN-109: quality findings and duplicate candidates exist; duplicate resolution policy/workflow and calibrated thresholds remain.
- KAN-120: OCR token storage, field suggestions and anchors exist; final mapping awaits approved field dictionary.
- KAN-154 / KAN-155: generic classifier and provisional document families exist; six bank-approved layouts and Source Inventory approval remain.
- KAN-156: provisional extraction and bounding boxes exist; labeled sample tuning and human review remain.
- KAN-157: quality/pipeline APIs exist; staff-facing workbench UI and end-to-end acceptance remain.

The sprint workbook assigns this role to Data / Document AI Engineer: schema, OCR, six layouts, 20 anchored fields, six-month Income Ledger, data validation, shadow data QA and data-contract handover. Business calculation, DSR, policy decision, Camunda orchestration, customer login and authoritative RBAC belong to other roles/services.

## Important blockers before real customer data

1. The project currently stores uploads on local disk and does not implement malware scanning or sandboxed parsing. Do not upload real customer financial documents until these controls and approved encrypted immutable object storage exist.
2. The service does not independently enforce complete bank/tenant scoping on all customer and case reads. Add service-side scope checks as defense in depth before multi-bank pilot.
3. The shared internal service token is not customer/staff authentication. Keep DATA-AI private behind Spring Boot and never expose the token to React.
4. The OCR layout families and field catalogue are provisional heuristics. The six official layouts and final 20 critical fields require bank/PO sign-off and labeled samples.
5. No evidence in this ZIP proves the required Macro F1, extraction accuracy/coverage or payroll match precision. These must be measured on independent labeled data.
6. Business Logic must own accepted eligible income, expense floor, debt consolidation, DSR, residual cash, stress scenarios and policy labels. DATA-AI must not implement those decisions.

## Secrets hygiene

The uploaded original ZIP contains a `.env` file with populated secret-valued settings. This reviewed archive excludes `.env`, local databases, virtual environments, caches, storage and exports. If the original values have been used outside a local disposable environment, rotate the database password, pgAdmin password and internal service token. Use `.env.example` to create a fresh local `.env`; never commit it.

## Reviewed implementation update (V7)

The next working copy adds:
- V7 permission catalogue (`permissions`, `role_permissions`) and append-only role assignment mirror history (`staff_role_assignment_history`).
- `BANK_POLICY_OWNER` role reference and starter permission mapping.
- Read-only access-control catalogue and scoped staff role-history endpoints.
- `1.1` as the default form version in application/submission schemas.
- Customer and case/document/transaction/quality/lineage service-side bank scoping using trusted Backend headers. A `SYSTEM_ADMIN` can perform platform-scoped lookup where explicitly supported; bank staff/service identities are restricted to their active bank.
- Fail-closed internal token behavior outside `APP_ENV=development` or `test`.
- Current employment and positive declared income plus NET/GROSS basis are required before creating a new loan application.

Remaining release blockers: PostgreSQL row-level security and a complete route-by-route security penetration test; encrypted immutable object storage, malware scanning and sandboxed parsing; database role/credential separation and PostgreSQL migration execution; full Backend RBAC enforcement; consent evidence lifecycle; bank-approved source layouts/field dictionary and independently labeled evaluation. V7 is additive and does not delete or rewrite legacy customer data.

## Additional v1.1 hardening

- Customer response payloads are minimized; legacy demographic/identity fields are not returned by the generic customer detail/list endpoints.
- New loan application creation requires a trusted Backend actor/bank context, checks caller bank code against the application bank, and requires a current `SALARIED` employment declaration with positive income and NET/GROSS basis.
- Applicant form snapshots contain only the approved 18 v1.1 fields. Legacy optional profile attributes are not copied into the form snapshot.
