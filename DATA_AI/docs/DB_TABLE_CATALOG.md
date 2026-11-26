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


## Customer-form simplification (V6 / form 1.1)

The customer-facing initial form is intentionally limited to identity/contact, current address, salaried employment and declared salary, loan request and consent. Household expense, detailed liability and salary-account declarations are deferred to later evidence/declaration steps. Their tables remain in the schema because they are required by the RFP analysis workflow.

`customer_employments.income_basis` stores the customer's declared NET/GROSS basis only. `customer_profiles.dependents_count` is nullable so an uncollected value is not silently represented as zero. Form version 1.0 and old submissions remain available for audit; version 1.1 is additive.

Authentication credentials and customer login accounts are not stored in this catalog. Backend/SSO owns them.

## Admin permission reference (V7)

| Domain | Table | Purpose | Authority |
|---|---|---|---|
| Staff / Admin | `permissions` | Stable permission-code catalogue | Shared contract; Backend enforces |
| Staff / Admin | `role_permissions` | Starter role-to-permission reference matrix | Reference only; Backend/SSO authoritative |
| Staff / Admin | `staff_role_assignment_history` | Append-only mirror history for role assignment/revocation events | Backend/SSO event mirrored by DATA-AI |

V7 adds `BANK_POLICY_OWNER` and the permission reference catalogue. It does not implement the bank policy approval engine or the complete authorization engine. The `ADMIN` alias is intentionally not a valid broad role.

## V8 additions

| Table/object | Purpose | Notes |
|---|---|---|
| `consent_events` | Append-only consent/withdrawal event history by case, customer, purpose and notice version | Backend validates identity and lawful purpose |
| `document_security_events` | Append-only file security/malware scan event history | Must be integrated with a real scanner and private object storage |
| `cases.bank_organization_id` | Normalized nullable FK to `bank_organizations.id` | Legacy `cases.bank_id` text remains; approved backfill required |
| `documents` security/retention columns | Detected MIME, malware scan state, private object key, encryption key reference, retention/legal hold | Metadata only; file bytes remain in approved object storage |
| `payroll_evidence` source-field FKs | Link gross/net/date/period evidence to OCR `extracted_fields` | Nullable for historical records |
| Financial declaration `client_request_id` | Database idempotency for new declaration API writes | API must require UUID and handle conflicts |
| `customer_salary_accounts` trigger | Enforces at most three salary accounts per case | Existing over-limit rows must be reconciled |
| Append-only triggers | Protect consent, declaration revisions, security events and case audit events | Corrections are compensating events/new revisions |

See `ERD_V8.md` and `V8_DEPLOYMENT_AND_BACKFILL.md` before integration or deployment.

## V13 / V9.3.2 evidence provenance and reconciliation

| Table | Purpose | Integrity / authority |
|---|---|---|
| `evidence_manifest_entries` | Per-case append-only sequence of uploaded evidence metadata and hash chain | Same-case document FK; UPDATE/DELETE blocked; receipt metadata/hash only, not authenticity |
| `transaction_duplicate_candidates` | Exact fingerprint pair linking two transaction rows | Same-case transaction FKs; append-only; no automatic deletion or exclusion |
| `evidence_reconciliation_runs` | Immutable PDF–CSV arithmetic comparison snapshot and source hashes | Same-case document FKs; Maker review required; not ownership or credit approval |
| `evidence_review_decisions` | Append-only review event with actor, role, reason and source document references | Same-case target FK; Camunda task completion remains external |

Use `scripts/backfill_duplicate_candidates.py` to scan historical imported transaction rows (dry-run by default) and `scripts/backfill_evidence_manifest.py` to manifest historical documents after storage integrity checks. The V13 tables are append-only via PostgreSQL triggers. Retention/purge must be governed by DBA procedure and retention/legal-hold policy; do not issue ordinary UPDATE/DELETE. Existing documents uploaded before V13 are `UNMANIFESTED` until a reviewed `LEGACY_BACKFILL` operation is applied.


## V14 / V9.4.1 governance tables

| Table | Purpose | Integrity / authority |
|---|---|---|
| `case_analysis_versions` | Immutable, hash-addressed snapshot of DATA-AI case evidence/input records with sequential version lineage and technical readiness | Same-case parent FK; sequential version trigger; UPDATE/DELETE blocked; does not store physical file paths or calculate credit decisions |
| `case_governance_events` | Append-only `FROZEN`, `CHECKER_CONFIRMED`, `RETURNED_TO_MAKER` and `VERSION_SUPERSEDED` events | Same-case version FK; Maker/Checker actor separation; one Checker decision per version; Camunda tasks remain external |

The V14 freeze guard locks case-owned input/evidence tables, including `document_security_events`, while the latest version is frozen or Checker-confirmed. Only a Checker return re-enables edits. Each version must have a `FROZEN` event before commit; snapshot reads and Checker decisions verify the stored SHA-256/readiness projection. The Checker confirmation is limited to DATA-AI evidence/input technical review; it is not credit approval, task completion or evidence authenticity verification.


## V15 / V9.4.2 audit and override governance

| Table | Purpose | Integrity / authority |
|---|---|---|
| `case_audit_entries` | Sequential, case-scoped hash-chained audit of V14 freeze/Checker and V9.4.2 proposal/authority mutations | DB row lock + sequence/previous-head checks; UPDATE/DELETE blocked; verification endpoint recomputes entry hashes; not an external signature/WORM anchor |
| `case_override_requests` | Immutable Maker proposal for an Override or Policy Exception bound to one V14 snapshot hash, policy reference/version and same-case evidence references | Same-case composite version FK; Maker must be the version creator; evidence refs validated against case-owned source records; UPDATE/DELETE blocked |
| `case_override_events` | Append-only `REQUESTED`, `APPROVED`, `REJECTED` and `WITHDRAWN` history | One terminal decision; Named Authority differs from Maker and Checker; approval binds proposal SHA-256 and expiry; UPDATE/DELETE blocked |

V15 seeds `NAMED_AUTHORITY` and three reference permissions. Backend/SSO remains the only authority for validating the actual named-authority grant, scope, limits and effective dates. The approval event is not applied to a policy engine, is not a credit decision and does not complete Camunda. Run `scripts/backfill_case_audit.py` without `--apply` first to count legacy `audit_events`; use `--apply` only after V15 migration and a restorable backup.


## V16 / V9.5.1 workflow integration

| Table | Purpose | Integrity / authority |
|---|---|---|
| `case_workflow_bindings` | Correlates a bank-scoped DATA-AI case with a Camunda 8 process definition/instance/business key | One active binding per case; unique process instance; binding details guarded against mutation |
| `workflow_outbox_events` | Transactional, no-PII event queue for DATA-AI-to-Camunda/Backend delivery | Case/binding composite FK; event idempotency key; payload SHA-256; lease/worker state; DB-enforced attempt ceiling 8, status/lease consistency, bounded retries and dead-letter; guarded transitions |
| `workflow_inbox_events` | Records inbound Camunda/Backend lifecycle callbacks | Append-only; unique external event ID; contiguous process sequence per binding; payload hash and same-case binding FK |
| `case_evidence_requests` | `AWAITING_EVIDENCE` request, required item codes, reason and due time | Same-case binding/version FKs; state guard and DB rule requiring `resolved_at` for terminal states; Camunda remains timer/notification owner |
| `case_resubmissions` | Immutable received-document IDs and deterministic impact list/hash | Append-only; same-case request relationship; does not itself create an analysis version or recalculate business values |
| `case_workflow_reopens` | Explicit reopen based on latest Checker-confirmed version | State guard `OPEN -> CONSUMED/CANCELLED`; immutable reason/scope; V14 freeze guard recognizes only matching OPEN reopen; successor link and `consumed_at` required on consume |
| `case_workflow_release_gates` | External G3 Shadow / G4 Operational reference receipts | Append-only; same-case version FK; G4 actor must be RELEASE_AUTHORITY; G4 needs matching G3 context |
| `case_workflow_export_packages` | Hash-addressed JSON/CSV/PDF evidence package metadata | Append-only; same-case version FK; SHA-256, private path metadata and audit event; download re-hashes package |
| `case_override_application_receipts` | Immutable Business Engine proof that an approved proposal was applied externally | One receipt per request; proposal/version hash + exact policy ref/version; append-only; DATA-AI records but never applies override |

V16 also seeds reference roles `WORKFLOW_ORCHESTRATOR`, `RELEASE_AUTHORITY`, `BUSINESS_ENGINE` and matching permission codes. The reference catalogue is not the authoritative grant/assignment system. Backend/SSO must validate actual service identity, bank scope and delegated authority. V16 extends V14's version sequencing and frozen-input guard so a successor version after Checker confirmation requires an explicit OPEN workflow reopen tied to the latest version.
