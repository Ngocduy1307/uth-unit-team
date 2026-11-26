# Customer intake v1.1: Frontend to Backend to DATA-AI mapping

## Public boundary

React/Frontend calls Spring Boot only: `POST /api/customer-applications`. Spring Boot authenticates the customer, derives customer/bank identity, validates consent and ownership, then calls DATA-AI over the private service network. The browser must never receive `INTERNAL_SERVICE_TOKEN`.

## v1.1 fields

| Frontend key | DATA-AI target | Required | Notes |
|---|---|---:|---|
| `fullName` | `customer_profiles.full_name` | Yes | Legal name |
| `dateOfBirth` | `customer_profiles.date_of_birth` | Yes | Backend validates adult eligibility |
| `phone` | `customer_profiles.phone` | Yes | Normalize and verify by Backend |
| `email` | `customer_profiles.email` | No | |
| `residencyDeclaration` | `applicant_submissions.form_data.residency_declaration` | Yes | Declaration, not legal identity proof |
| `province` | `customer_addresses.province_name` | Yes | |
| `ward` | `customer_addresses.ward_name` | Yes | |
| `address` | `customer_addresses.street_address` | No | |
| `employmentType` | `customer_employments.employment_type` | Yes | Backend sets `SALARIED` for this MVP |
| `employerName` | `customer_employments.employer_name` | Yes | |
| `jobTitle` | `customer_employments.job_title` | No | |
| `monthlyIncome` | `customer_employments.monthly_income_declared` | Yes | Customer-declared only |
| `incomeBasis` | `customer_employments.income_basis` | Yes | NET or GROSS |
| `salaryPaidToBank` | `applicant_submissions.form_data.salary_paid_to_bank` | Yes | Required scope declaration |
| `requestedAmount` | `loan_applications.requested_amount` | Yes | VND |
| `requestedTermMonths` | `loan_applications.requested_term_months` | Yes | 6–36 |
| `loanPurpose` | `loan_applications.loan_purpose` | Yes | |
| `consent` | Backend consent record + form snapshot | Yes | Backend creates consent reference/time |

## Fields intentionally deferred

Do not require itemized household expenses, detailed liabilities, account numbers, CCCD numbers, salary account ownership proof, payroll breakdown or six months of transaction rows on the initial form. Collect later through secure evidence upload and guided declaration steps. Keep the V5 expense, liability and salary-account tables because they support the later analysis workflow and staff verification.

## Important implementation note

The React sample currently uses camelCase and calls a Spring Boot route. The DATA-AI API models use snake_case and are internal. Spring Boot must map the DTO explicitly, create/reuse the customer profile, create the application/case, create the immutable submission snapshot, and pass only the required internal references. Do not post the browser JSON directly to DATA-AI.
