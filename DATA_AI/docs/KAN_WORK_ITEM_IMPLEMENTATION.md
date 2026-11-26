# KAN DATA-AI work items: implementation and acceptance status

This document describes the implementation in this repository after the DATA-AI pipeline enhancement. Status is based on code in this repository, not Jira workflow status.

## Implemented in this repository

- Generic document-family suggestions for bank statements, payslips, employment certificates, identity documents and loan documents. Results are suggestions, not authenticity checks. V9.3.1 adds six generic profile entries; none is represented as bank-approved.
- Provisional label-based field extraction for a configurable set of 20 fields. V9.3.1 adds confidence basis, syntactic validation, explicit `SUGGEST`/`ABSTAIN`, abstain reasons and extraction-rule version. Values retain page number and source bounding boxes where available.
- Generic CSV intake with header aliases, date/amount normalization, row-level source anchors, missing/invalid value findings and duplicate-transaction candidates.
- Source Inventory records for generic OCR and generic CSV adapters. These are created with `PENDING_APPROVAL`, not falsely marked bank-approved.
- Data Quality Issue records for unknown document family, empty OCR, low OCR confidence, no extracted labeled fields, missing CSV columns, invalid transaction date/amount and duplicate candidates.
- Idempotent document pipeline run tracking using document ID, SHA-256 and pipeline version.
- Observed monthly salary-candidate ledger aggregation. `accepted_amount` is never populated by the pipeline.
- Exact-amount payroll-to-credit match suggestions within a five-day payment-date window. Suggestions remain `SUGGESTED` and are never accepted automatically.
- Read APIs for case quality issues, pipeline runs, Source Inventory and field mapping registry.

## Work-item traceability

| Jira | Implemented | Remaining acceptance conditions |
|---|---|---|
| KAN-157 | API visibility for quality and pipeline workbench data | Actual staff-facing UI and end-to-end user acceptance must be delivered by the frontend/Backend workstream |
| KAN-156 | Provisional field extraction, source anchors, validation and abstention decision | Confirm final extraction schema, calibrate against labeled documents and integrate human review workflow |
| KAN-155 | Generic classification, six provisional generic profile entries and a versioned 20-field candidate catalogue | Six official bank layouts, exact final SRS field definitions and requiredness require PO/bank sign-off and labeled samples |
| KAN-154 | Generic document-family classification and Source Inventory bootstrap | Approved source inventory and production classifier thresholds require bank samples/sign-off |
| KAN-120 | OCR token storage, field suggestions and source anchors | Final mapping to approved field dictionary remains pending |
| KAN-109 | Row/document-level quality findings and duplicate transaction candidates | Fuzzy duplicate review policy, resolution workflow and calibrated quality thresholds remain |
| KAN-95 | Observed monthly salary-candidate totals and match suggestions | No accepted income, expense/debt consolidation, DSR or policy calculation is implemented by design |
| KAN-94 | Versioned, idempotent processing run and evidence/source metadata | Immutable object storage, full evidence review workflow and operational monitoring remain |
| KAN-93 | Existing dictionary/catalog plus source/mapping registry read APIs | Final approved data dictionary, populated mappings and full lineage UI remain |
| KAN-92 | Generic source types and transaction field extraction | Two official bank CSV schemas and source-specific mappings require bank sign-off |
| KAN-73 | Same shared pipeline foundation as KAN-94 | Confirm with project owner whether this is a duplicate/parent task or a distinct deliverable |

## Explicit non-goals and production blockers

- This pipeline does not authenticate a document, verify account ownership, approve a loan, decide eligible income, calculate DSR, consolidate debt or produce policy labels.
- The 20 extraction fields and generic document families are provisional heuristics. They are not represented as the six approved bank layouts.
- Generic CSV aliases are a demo adapter, not either of the two approved bank CSV schemas.
- Malware scanning, process sandboxing, encrypted object storage, retention/deletion policy, backup, tenant isolation and production RBAC are not implemented here. Do not process real customer evidence in production until these controls are provided and tested by the owning platform/security workstreams.
- OCR/extraction accuracy and classifier performance have not been measured against an independent labeled dataset.
- All extracted values and transaction categories require authorized review. `is_income_eligible` remains false.

## API additions

- `GET /api/v1/cases/{case_id}/quality-issues`
- `GET /api/v1/cases/{case_id}/pipeline-runs`
- `GET /api/v1/admin/source-inventory`
- `GET /api/v1/admin/field-mappings`

All routes use the existing internal service-token dependency. Production deployment must additionally enforce network isolation, authentication, authorization and tenant scoping in the Backend/platform layer.
