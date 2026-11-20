# PostgreSQL `data_ai` schema catalog

| Domain | Table | Purpose | Main owner |
|---|---|---|---|
| Organization | `bank_organizations` | Bank/tenant master reference | System admin / Backend sync |
| Organization | `bank_branches` | Bank branch directory | Bank admin |
| Customer | `customer_profiles` | Customer profile and contact details | Backend customer workflow |
| Customer | `customer_addresses` | Permanent/residential/contact addresses | Backend customer workflow |
| Customer | `customer_employments` | Employment and customer-declared income | Backend customer workflow |
| Application | `cases` | DATA-AI processing case | Backend creates, DATA-AI processes |
| Application | `loan_applications` | Requested product, amount, term and purpose | Backend customer workflow |
| Application | `applicant_submissions` | Immutable versioned form snapshot | Backend forwards, DATA-AI retains |
| Staff / Admin | `staff_users` | Staff identity mirror, no credentials | Backend/SSO sync |
| Staff / Admin | `access_roles` | Role catalogue | System admin |
| Staff / Admin | `staff_user_roles` | Staff-to-role assignments | Backend/SSO sync |
| Staff / Admin | `management_audit_logs` | Admin/staff changes and export actions | DATA-AI audit |
| Form config | `form_definitions` | Versioned form configuration | Bank/system admin |
| Form config | `form_field_definitions` | Configurable fields, validation and display order | Bank/system admin |
| Document AI | `documents` | Original document metadata and hash | DATA-AI |
| Document AI | `extracted_fields` | OCR/extraction values and source anchors | DATA-AI |
| Document AI | `processing_results` | Processing run summaries | DATA-AI |
| Transaction AI | `transactions` | Parsed bank statement rows | DATA-AI |
| Transaction AI | `payroll_evidence` | Salary evidence candidates | DATA-AI |
| Transaction AI | `earning_match_candidates` | Suggested payroll-to-transaction links | DATA-AI |
| Transaction AI | `income_ledger_months` | Month-by-month observed/accepted/excluded evidence | DATA-AI + Maker review |
| Quality | `data_quality_issues` | Missing, duplicate, invalid or low-confidence flags | DATA-AI |
| Audit | `audit_events` | Case-level processing audit | DATA-AI |
| Export | `export_jobs` | Excel export metadata and row counts | DATA-AI |

## Important data rules

- Government identity number is not stored in full in this baseline. Only `identity_type` and `identity_last4` are modeled. Any need to retain the full identifier requires explicit legal/security approval and field-level encryption/tokenization.
- `customer_profiles` stores customer-entered profile data; `applicant_submissions` stores immutable, versioned form snapshots; `extracted_fields` stores AI-derived evidence. Do not overwrite one source with another.
- Customer-entered income is declared information, not verified income. It must remain distinguishable from OCR evidence and staff-accepted amounts.
- `loan_applications.application_status` is an application workflow status, not a credit decision. DATA-AI does not approve/reject loans.
- Form changes create a new `form_definitions.version`; old submission snapshots remain unchanged.
- `staff_users` has no password/hash/session columns. Authentication belongs to Backend/SSO.
| DATA governance | `source_inventory` | Approved/pending source document and statement schema registry | DATA–AI + PO approval |
| DATA governance | `field_mapping_registry` | Versioned source-to-target field mapping registry | DATA–AI + PO approval |
| Pipeline | `pipeline_runs` | Idempotent processing run status and metrics | DATA–AI |
