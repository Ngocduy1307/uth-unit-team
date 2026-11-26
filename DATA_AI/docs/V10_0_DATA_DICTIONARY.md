# DATA-AI V10.0 Data Dictionary — PostgreSQL

This dictionary covers the additive V18 entities and the key pre-existing domain entities used by the Workflow(4) handoff. `UUID` identifies internal rows; all monetary fields are stored as exact numeric/decimal or canonical decimal strings in JSON and are never floated for calculations by DATA-AI.

## V18 additions

| Table | Key columns | Meaning / invariant |
|---|---|---|
| `case_scope_consent_attestations` | `case_id`, `bank_id`, `scope_code`, `scope_status`, `consent_status`, `backend_decision_reference`, `attestation_sha256`, `attested_at` | Immutable mirror of a Backend/SSO decision. Only `VN_UNSECURED_SALARIED_VND`; scope IN_SCOPE/OUT_OF_SCOPE; consent GRANTED/REVOKED/NOT_GRANTED. `case_id + backend_decision_reference` unique. Does not replace the authoritative consent service. |
| `case_input_declaration_revisions` | `case_id`, `customer_id`, `section_code`, `revision_no`, `payload JSONB`, `payload_sha256`, `client_request_id`, `supersedes_revision_id` | Immutable applicant declaration revisions. Sections: HOUSEHOLD, EMPLOYMENT, EXPENSES, LIABILITIES, SALARY_ACCOUNTS. Revisions are sequential per case/section; same case/customer composite FK; optional client idempotency key unique per case. |
| `case_input_declaration_evidence_links` | `case_id`, `declaration_revision_id`, `document_id`, `document_sha256`, `link_purpose` | Provenance links from declaration to trusted same-case document and digest. |
| `case_input_review_decisions` | `case_id`, `declaration_revision_id`, `target_type`, `target_id`, `decision_code`, `evidence_refs JSONB`, `reviewed_by`, `reviewer_role` | Append-only Maker review. Decision CONFIRMED/RETURNED/UNABLE_TO_VERIFY/REJECTED. Target types include declaration revision, OCR field, payroll evidence, earning match, transaction and income ledger. DB requires reviewer role MAKER; API validates same-case target and source anchors. |
| `case_financial_input_bundles` | `case_id`, `bundle_no`, `readiness_status`, `readiness JSONB`, `bundle_data JSONB`, `bundle_sha256`, `created_by` | Immutable canonical packet to Financial Engine. READY_FOR_BUSINESS_ENGINE is the only state that may be read by Business Engine. Duplicate content retries return the same bundle while case row is locked. |
| `case_proposed_schedule_references` | `case_id`, `bundle_id`, `schedule_reference`, `schedule_sha256`, `product_code`, `product_version`, `term_months`, `currency` | External schedule reference only. Currency VND; term 6–36. Same-case FK to bundle. DATA-AI does not store or calculate installments. |
| `case_business_engine_receipts` | `case_id`, `bundle_id`, `schedule_reference_id`, `input_bundle_sha256`, `calculation_reference`, `calculation_version`, `policy_reference`, `policy_version`, `product_code`, `product_version`, `product_sha256`, `policy_sha256`, `result_status`, `scenario_references JSONB`, `output_sha256` | Immutable result receipt from external Business Engine. COMPLETED requires a matching same-case schedule and exactly three scenario refs BASELINE/STRESS_1/STRESS_2. Input/output/product/policy hashes must be SHA-256. `calculation_reference` unique. |

All V18 rows are append-only (UPDATE/DELETE rejected by DB trigger). V18 includes bank scope validation; composite FKs prevent cross-case declaration/evidence/schedule/receipt linkage.

## Existing entities participating in workflow

| Entity | Relevant columns | DATA-AI role |
|---|---|---|
| `cases` | `id`, `customer_id`, `bank_id`, `analysis_date`, `external_case_id` | Tenant/case anchor and six-month analysis window. |
| `loan_applications` | `product_code`, `requested_amount`, `requested_term_months`, `currency` | Customer request metadata; does not determine affordability or product eligibility. |
| `documents` | `sha256`, `mime_type`, `document_type`, `processing_status`, `malware_scan_status`, `stored_path`, `page_count` | Immutable source evidence, scan-gated and manifest-linked. |
| `document_security_events` | `event_type`, `scan_status`, `scanned_sha256`, `engine_name`, `engine_version`, `attestation_version` | Append-only ClamAV exact-byte security attestation. |
| `extracted_fields` | `field_name`, `raw_value`, `normalized_value`, `confidence`, `confidence_basis`, `page_number`, `bbox`, `coordinate_space`, `validation_status`, `extraction_decision` | OCR candidate with source anchor; never accepted automatically. |
| `payroll_evidence` | `payment_date`, `gross_amount`, `net_amount`, `currency`, `source_anchor`, `document_id` | OCR-derived payslip candidate. |
| `transactions` | `transaction_date`, `source_row`, `amount_vnd`, `direction`, `category`, `classification_confidence`, `review_status`, `document_id` | Observed statement rows; no automatic eligible-income flag. |
| `earning_match_candidates` | `payroll_evidence_id`, `transaction_id`, `similarity_score`, `match_reasons`, `review_status` | Suggested payslip ↔ bank-credit pair requiring Maker confirmation. |
| `income_ledger_months` | `period_month`, `observed_amount`, `accepted_amount`, `excluded_amount`, `month_status` | Observed candidate monthly ledger. `accepted_amount` remains NULL absent an authoritative decision. |
| `evidence_reconciliation_runs` | PDF/CSV document IDs and SHA, `result_status`, summary | Candidate cross-document balance reconciliation. |
| `transaction_duplicate_candidates` | left/right transaction IDs, fingerprint hash, match reasons | Potential duplicate pairs; rows are never deleted/nets computed automatically. |
| `case_analysis_versions` | version number, parent, snapshot JSON, `snapshot_sha256` | Immutable Freeze snapshot includes all V18 records. |
| `workflow_outbox_events` / `workflow_inbox_events` | opaque reference IDs, event type, sequence, idempotency and delivery status | Safe event bridge to Camunda; no PII, statement content or monetary amounts in workflow payload. |
| `case_audit_entries` | sequence, actor, action, entity refs, prev/current hash | Hash-chained audit history. |

## Sensitive-data rules

- Full bank account number and personal identity numbers remain in restricted evidence/OCR storage; external Finance bundle includes only opaque `account_ref_id`, bank code, last four account digits, statement dates and evidence refs.
- Employer tax ID, employer name, account-holder name, bank names, free-text household notes and transaction descriptions are not exported to the Financial Engine bundle.
- Camunda variables carry opaque IDs and routing state only.
- All missing amounts and missing months remain explicit/null; DATA-AI does not impute zero or average.
