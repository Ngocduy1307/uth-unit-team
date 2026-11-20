# Applicant profile and financial declaration data dictionary

## Scope guardrails
This form is for the SRS MVP only: adult individual resident in Vietnam, VND unsecured monthly-installment consumer loan, salaried income paid into bank account, six complete calendar months, maximum three salary accounts and two bank-statement CSV layouts. Do not add self-employment, cash salary, rental income, foreign currency, co-borrowers, guarantors, mortgage, refinancing, revolving credit-card products or balloon-payment products to this MVP. The platform collects evidence and declarations; it does not authenticate documents, approve/decline credit, calculate policy outcomes or disburse.

## Customer-entered sections

### A. Identity and contact (collect minimum necessary)
- Full legal name (required); date of birth (required to establish adult eligibility); nationality/residency declaration; phone (required); email (optional); preferred contact channel (optional).
- Identity document type and masked reference only in this DATA-AI store. Full identity number, full document image and KYC verification belong in the bank's controlled KYC/Backend service. Store only a reference to the verified KYC result if the bank contract requires it.
- Marital status and dependent count only where the bank has approved a legitimate affordability use. Do not infer either from name, image or other attributes.

### B. Address and household
- Residential address and address type (current/permanent), province, ward, street details; duration at current address (optional).
- Household size, dependents count, housing status and residence contribution only if required by bank policy. These are customer declarations, not verified facts.

### C. Employment and salary
- Employment type limited to salaried employment for MVP; employer legal name, employer tax code (optional), job title, industry, work address/contact (optional), start date, current-employment flag.
- Monthly salary amount and whether gross/net, currency VND, pay frequency and typical pay day. Declared income is not eligible income until corroborated and reviewed.
- No cash salary, self-employment, rental or foreign-currency income path in MVP.

### D. Salary accounts (maximum 3)
- Bank name/code, account holder name, masked account number (last four digits only), currency VND, statement start/end dates, evidence file reference.
- Customer can declare account ownership. Only authorized bank staff can set ownership verification status and reviewer/time. Same-name match or masked account number alone is not proof of ownership.

### E. Loan request
- Requested amount VND, requested term 6–36 months, purpose, product code if supplied by Backend. This is a request, not approval or offer. Rate, repayment quote and decision are owned by Backend/Business Logic, not DATA-AI.

### F. Household expense declarations
- Category: housing, utilities, food, education, healthcare, transport, other; amount VND; frequency; notes. Keep each declaration separately. Missing expense is UNKNOWN, never silently zero. Staff review is required before downstream calculations.

### G. Existing liability declarations
- Type: installment loan, credit card, overdraft, informal debt, guarantee, other; creditor; masked reference; outstanding balance; monthly payment; due day; start/end dates; overdue indicator/amount.
- These are self-declared leads, not verified liabilities. Bank staff must reconcile against permitted sources, deduplicate and classify. DATA-AI must not compute DSR or consolidate debt itself.

### H. Evidence and consent
- Consent reference and timestamp captured by Backend; document original stored immutably by controlled document service. DATA-AI records file hash, type, pages/rows, source anchors and processing status.
- Required evidence for the six-month salary analysis is defined by the bank-approved checklist. Do not mark a case complete just because a form is submitted.

## System-managed fields (not customer editable)
- Internal customer/case/document IDs, bank/tenant ID, created/updated timestamps, form/schema version, processing status, hash, OCR confidence, source anchors, review status, reviewer identity/time, audit history, export history.
- Customer-facing clients must never be allowed to set bank_id, staff roles, review status, ownership verification, OCR result, eligible income, accepted/excluded amount, policy status or analysis-complete state.

## Validation and data quality
- Preserve Vietnamese Unicode and leading zeros; dates use ISO 8601 and display in Asia/Ho_Chi_Minh; money uses NUMERIC/Decimal VND, not floating point.
- Do not store full bank account numbers or full national ID numbers in the DATA-AI reporting tables. Use masked values and references to controlled systems.
- Keep declaration revisions; corrections create a new revision rather than overwriting the prior customer statement.
- Missing values remain NULL/UNKNOWN, not zero. Customer-entered, OCR-suggested, staff-verified and policy-approved values must remain distinguishable.
- Enforce the SRS limits: 10 files/case, 60 pages, 20 MiB/file, 3,000 transaction rows, 6 complete calendar months, max 3 salary accounts and max 2 approved CSV schemas. Over-limit cases are HOLD, never silently truncated.

## Ownership / integration
Backend owns authentication, consent, canonical customer identity, tenant isolation and authoritative case lifecycle. DATA-AI owns document intelligence, field extraction, classification suggestions, source lineage and data-quality findings. Business Logic owns expense/debt consolidation, eligible income decisions, DSR, residual cash and policy outcomes. Flyway migrations for shared production schema must be owned and applied by the agreed database owner; do not run SQLAlchemy create_all in production.
