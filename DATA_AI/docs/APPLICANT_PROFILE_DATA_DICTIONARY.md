# Applicant profile and financial declaration data dictionary

## Scope and intake strategy

This schema supports only the RFP MVP: an adult individual resident in Vietnam, salaried employment with salary paid into a bank account, one unsecured VND consumer-loan product, monthly installments for 6–36 months, and six complete calendar months of evidence. It excludes self-employment, cash salary, rental income, foreign currency, co-borrowers, guarantors, mortgage, refinancing and revolving-credit products.

The customer form is intentionally staged. The initial form opens the application; it is not the full credit file. Later evidence upload and guided declarations collect what is still needed. This reduces typing without deleting the evidence required by the RFP.

## Initial customer form (version 1.1)

Required:
- Full legal name, date of birth, phone number.
- Declaration of residence in Vietnam.
- Current province/city and ward/commune.
- Current employer legal name.
- Declared monthly salary amount and whether the amount is NET or GROSS.
- Confirmation that salary is received by bank transfer.
- Requested amount (VND), requested term (6–36 months), loan purpose.
- Explicit consent, with consent reference and timestamp generated/recorded by Backend.

Optional:
- Email, job title, street address.

Do not ask at initial intake for gender, marital status, dependents, preferred contact channel, identity-document suffix, employer tax code, employer phone/address, exact employment dates, household size, housing status, itemized expenses, creditor-by-creditor liabilities, full bank account number or full national ID number.

The customer's declared salary is not accepted/eligible income. It must be corroborated against payslips and six months of bank statements and reviewed by authorized staff. NET/GROSS is only the basis of the customer's declaration, not a normalization or eligibility decision.

## Later-stage declarations and evidence

- **Salary accounts:** bank name, account holder name and masked last four digits only where available; statement period and evidence document reference. Maximum three accounts. Customer declaration is not ownership verification. Only authorized bank staff can set verification status, reviewer and verification time.
- **Expenses:** collect a simple monthly total or category-level declarations in a separate step when required. Preserve NULL/UNKNOWN when not supplied. Bank policy's minimum expense floor is applied by Business Logic, not DATA-AI.
- **Liabilities:** ask whether the customer has existing obligations. If yes, collect details through a separate guided step or derive candidates from permitted evidence. A customer-declared total is not the consolidated debt register. Bank staff/Business Logic reconcile declarations, CIC and bank records, deduplicate and classify.
- **Evidence:** upload payslips and bank statements through the controlled document intake. The bank-approved checklist determines completeness for the six-month analysis. A submitted form is not a complete analysis case.

## Data ownership and provenance

- `customer_profiles`: minimum profile/contact details; no credentials.
- `customer_addresses`: current address; additional address types only if a documented use case requires them.
- `customer_employments`: current salaried employment and declared monthly income; `income_basis` is NET/GROSS and remains a customer declaration.
- `loan_applications`: requested product/amount/term/purpose only; not an offer or decision.
- `applicant_submissions`: immutable, versioned snapshot of each submitted form.
- `customer_expense_declarations`, `customer_liability_declarations`, `customer_salary_accounts`: later-stage customer declarations and verification metadata.
- `documents`, `extracted_fields`, `transactions`, `payroll_evidence`, `earning_match_candidates`, `income_ledger_months`, `data_quality_issues`, `pipeline_runs`, `audit_events`: evidence and processing lineage. OCR values are suggestions with source anchors, not verified facts.

## System-managed fields (not customer editable)

Internal customer/case/document IDs, bank/tenant ID, timestamps, form/schema version, file hash, OCR confidence, source anchors, processing/review status, reviewer identity/time, audit history and export history. Browser clients must never set bank_id, staff roles, review status, ownership verification, OCR result, accepted/excluded income, policy status or analysis-complete state.

## Validation and data quality

- Preserve Vietnamese Unicode and leading zeros. Store dates as DATE/TIMESTAMPTZ and display in Asia/Ho_Chi_Minh.
- Store VND with PostgreSQL NUMERIC/Decimal, never binary float for financial amounts.
- Do not store full bank account numbers or full national ID numbers in DATA-AI reporting tables. Use masked values and references to bank-controlled KYC systems.
- Keep declaration revisions. Corrections create a new revision; do not overwrite a prior submitted declaration.
- Distinguish customer-entered, OCR-suggested, staff-verified and policy-approved values.
- Missing values remain NULL/UNKNOWN, never zero. “No debt” is a separate explicit declaration and must not be inferred from an unanswered question.
- Limits: 10 files/case, 60 pages, 20 MiB/file, 3,000 transaction rows, six complete calendar months, maximum three salary accounts and two approved CSV schemas. Over-limit cases are held, never silently truncated.

## Login and authorization boundary

Customer login, staff/admin login, password hashes, MFA, sessions, refresh tokens and authoritative permission checks belong to Spring Boot Backend/SSO. Do not add password columns to `customer_profiles` or `staff_users`. DATA-AI stores only the customer/staff reference IDs and authorized business metadata needed for processing/audit.

## Safe schema evolution

The initial V1–V5 migrations are historical. Do not rewrite or delete columns/tables in migrations that may already have been applied. V6 adds the `income_basis` declaration and publishes customer form version 1.1 while retaining version 1.0 and all historical submissions. A column that is no longer shown on the customer form may still be needed for OCR, staff review, audit or future evidence enrichment.
