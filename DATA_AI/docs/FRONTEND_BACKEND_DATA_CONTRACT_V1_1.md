# Frontend / Backend / DATA-AI data contract (customer intake v1.1)

## Ownership and connection boundary

- React browser calls Spring Boot only. It must never connect directly to PostgreSQL or call DATA-AI directly.
- Spring Boot owns customer/staff authentication, SSO, MFA, consent capture, identity derivation, authorization and public API DTO validation.
- DATA-AI is a private service behind the Backend gateway. Production calls require the internal service token, a signed request assertion, and trusted service identity headers.
- PostgreSQL is the shared persistence layer. Sharing one database does not mean sharing credentials or granting Frontend direct SQL access.
- DATA-AI stores declarations, evidence, OCR suggestions, source anchors, quality findings and lineage. It does not decide eligible income, DSR, policy outcome or credit approval.

## Minimal customer intake v1.1

The customer-facing form contains 18 fields. Required fields are marked `required=true`.

| JSON key (camelCase) | DATA-AI column / destination | Required |
|---|---|---:|
| fullName | customer_profiles.full_name | Yes |
| dateOfBirth | customer_profiles.date_of_birth | Yes |
| phone | customer_profiles.phone | Yes |
| email | customer_profiles.email | No |
| residencyDeclaration | applicant_submissions.form_data.residency_declaration | Yes |
| province | customer_addresses.province_name | Yes |
| ward | customer_addresses.ward_name | Yes |
| address | customer_addresses.street_address | No |
| employmentType | customer_employments.employment_type (`SALARIED` for this MVP) | Yes |
| employerName | customer_employments.employer_name | Yes |
| jobTitle | customer_employments.job_title | No |
| monthlyIncome | customer_employments.monthly_income_declared | Yes, > 0 |
| incomeBasis | customer_employments.income_basis (`NET` or `GROSS`) | Yes |
| salaryPaidToBank | applicant_submissions.form_data.salary_paid_to_bank | Yes |
| requestedAmount | loan_applications.requested_amount | Yes, > 0 VND |
| requestedTermMonths | loan_applications.requested_term_months | Yes, integer 6–36 |
| loanPurpose | loan_applications.loan_purpose | Yes |
| consent | Backend consent record; snapshot boolean only | Yes |

Email, job title and street-level address are optional. Do not ask for gender, marital status, dependents, full identity number, full bank account number, employer tax code/contact details, household questionnaire, itemized expenses or creditor-level debts at initial intake.

## Deferred secure collection

After initial application, collect only what the bank checklist requires through secure upload/declaration steps:

- Payslips and bank statements covering six complete calendar months.
- Up to three salary accounts; ownership and statement period must be verified by staff.
- Living expenses and liabilities, with unknown values remaining NULL/unknown, never silently converted to zero.
- KYC identity evidence through the bank-controlled KYC flow.

Keep the V5 financial declaration tables. They are not initial form questions and support later evidence-based review.

## Spring Boot responsibilities before DATA-AI call

1. Authenticate the customer and derive `customer_id`, `bank_id`, `applicant_ref` and `external_case_id` server-side. Never trust browser-supplied bank/customer ownership identifiers.
2. Validate adult/residency/product eligibility under bank-approved rules.
3. Capture consent against the correct notice/purpose/version. Generate a durable `consent_reference`; a `consent=true` checkbox alone is not legal evidence.
4. Map camelCase DTO fields to DATA-AI snake_case fields. Set `form_version="1.1"` explicitly.
5. Create/reuse customer profile and current employment; persist income as customer-declared only, not accepted income.
6. Create case/application and immutable applicant submission snapshot. Never overwrite the previous submitted snapshot; use a new form/submission version for corrections.
7. Call DATA-AI only over private service networking with `X-Internal-Service-Token` and `X-Service-Assertion` in production. For every protected operation, overwrite `X-Actor-Id`, `X-Actor-Roles`, and `X-Bank-Id` from the authenticated server-side identity (or a dedicated service principal for service-only calls). Do not forward browser values for these headers. Sign the final serialized HTTP body as specified in `V9_2_2_SIGNED_SERVICE_ASSERTIONS.md`.

## Example internal DATA-AI application payload

```json
{
  "external_case_id": "CASE-2026-000123",
  "bank_id": "BANK_CODE_FROM_BACKEND",
  "requested_amount": "50000000",
  "requested_term_months": 24,
  "loan_purpose": "Chi tiêu cá nhân",
  "form_version": "1.1",
  "consent_reference": "CONSENT-REFERENCE-FROM-BACKEND",
  "form_data": {
    "residency_declaration": true,
    "salary_paid_to_bank": true,
    "consent": true
  }
}
```

The current DATA-AI customer application endpoint expects the customer profile and current employment to have been created/linked first. It creates the case, loan application and immutable form snapshot.

## Trusted internal headers

| Header | Source | Rule |
|---|---|---|
| X-Internal-Service-Token | Backend secret store | Required outside local development; never exposed to browser |
| X-Service-Assertion | Backend signing key | Required in production; request-bound HMAC assertion; never generated in browser |
| X-Actor-Id | Authenticated Backend principal | Backend-generated stable subject ID |
| X-Actor-Roles | Backend/SSO authorization result | Backend-generated; never accepted from browser |
| X-Bank-Id | Authenticated staff tenant | Bank code; never accepted from browser |

The current role/permission catalogue endpoint is read-only metadata. It is not a replacement for Backend authorization. Customer read/list/update endpoints apply an additional bank-scope check based on trusted headers.

## Form and application API behavior

- Active form code: `CUSTOMER_LOAN_APPLICATION`.
- Active form version: `1.1`.
- `LoanApplicationCreate` and `ApplicantSubmissionIn` default to `1.1`; Backend should still send it explicitly.
- Missing active form is a service configuration error (503), not permission to bypass validation.
- Version mismatch returns 409.
- Missing current salaried employment, employer name, positive declared income or NET/GROSS basis returns 422.
- A consent reference is mandatory for application creation.

## Data ownership boundaries

| Domain | Owner | DATA-AI role |
|---|---|---|
| Customer login, password, MFA, sessions | Backend/SSO | No credentials stored |
| Customer profile and intake snapshot | Backend owns identity; DATA-AI persists data copy/snapshot | Persist and validate structure |
| Staff identity and authoritative role grants | Backend/SSO | Mirror staff and role references for audit |
| Permission catalogue | Shared contract, Backend enforcement | Store/read reference catalogue |
| Evidence/OCR/anchors/quality/lineage | DATA-AI | Own implementation |
| Accepted income, expenses floor, debt consolidation, DSR, stress | Business Logic / Calculation Service | Supply source-linked observations only |
| Maker/Checker workflow state and task authority | Camunda / Backend application services | Supply evidence and audit references |
| Credit decision, approval, rejection, disbursement | Bank's existing credit system | Out of scope |

## Customer response minimization

`GET /api/v1/customers` and `GET /api/v1/customers/{customer_id}` return only the fields needed by the current customer/staff intake view: customer code, name, date of birth, phone, optional email, status, primary address and current employment (including declared income and NET/GROSS basis). They do not return legacy gender, marital status, dependents, identity suffix/type, preferred contact method, employer tax/contact/address or industry fields. Staff-only workflows that lawfully need additional data must use a separate, purpose-scoped contract rather than widening this response.
