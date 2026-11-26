# DATA-AI V9.3.1 – OCR Layout & Field Governance Foundation

**Release status:** source-level foundation implemented; bank/SRS sign-off and target-environment validation remain open.

## Workflow nodes addressed

This increment advances the DATA-AI-owned portion of the workflow:

- `[Service] Phân loại & trích xuất dữ liệu (M AI 01-02; Abstain khi mờ/không rõ)`.
- `[Degradation - ARC 07] Lỗi trích xuất: Giữ Intake an toàn & chuyển Maker review/nhập thủ công` (machine-side abstention signals only; the Maker task UI and workflow routing remain Backend/Camunda-owned).
- It supplies field-level validation and provenance for Maker reconciliation downstream.

## What changed in source

1. `app/document_intelligence.py` now publishes a versioned provisional layout catalogue and a 20-field candidate catalogue.
2. Six **generic integration profiles** are enumerated: bank statement PDF, bank statement CSV, payslip, employment certificate, identity document and loan document. These are not the six bank-approved layouts. Every profile remains `PENDING_BANK_PO_SIGNOFF`.
3. Classification now abstains on no signal, ambiguous family scores and low heuristic confidence instead of selecting the first family by dictionary order.
4. Field candidates carry `confidence_basis`, `validation_status`, `extraction_decision`, `abstain_reason` and `extraction_rule_version`.
5. Dates and money are normalized only when format parsing succeeds. Invalid date/amount/identifier candidates are retained as review evidence with `ABSTAIN`, not normalized as if valid.
6. Native PDF text-layer extraction is explicitly marked `NATIVE_TEXT_LAYER_UNCALIBRATED`. A value of 1.0 for native text presence is not a calibrated correctness probability; these values are routed to Maker review.
7. OCR token rows remain raw evidence and are marked `ABSTAIN` until a field-level interpretation/review exists.
8. Processing summaries record classification status, layout/field catalogue versions, suggested/abstained counts and a machine decision (`SUGGEST_ONLY` or `ABSTAIN`).
9. `GET /api/v1/admin/ocr/catalog` exposes the read-only catalogue to trusted service/admin roles. It does not provide a bank-layout approval or activation operation.
10. Flyway migration V12 adds persistent extraction-decision and confidence provenance fields.

## Important interpretation rules

- `SUGGEST` is not `ACCEPTED`, `VERIFIED`, income-eligible or authentic.
- `validation_status=VALID` means a value passed a syntactic normalization rule only. It does not prove the value is true or belongs to the applicant.
- Confidence values are not calibrated against a labeled dataset. OCR engine confidence must not be read as a probability that the field is correct.
- The generic profile slots are only scaffolding. Exact bank-specific layouts, required fields per layout, the final SRS 20-field dictionary, and the two approved CSV schemas still require PO/bank sign-off and labeled sample files.
- No missing field is imputed. No salary, expense, debt, residual, DSR or policy decision is derived by this increment.

## Workflow gaps still open after V9.3.1

| Workflow node / requirement | Owner | Status after this increment |
|---|---|---|
| Intake manifest, hash and append-only file provenance | DATA-AI + Backend | SHA-256 and upload audit exist; a complete immutable manifest/version chain remains open |
| Scope, purpose and consent DMN (SEC 02) | Backend/Camunda/Bank | Consent reference is stored; policy gate remains external |
| File safety, malware scan, quarantine and zero-silent-loss (INC 02) | Platform/Security + DATA-AI | MIME/signature and malware scanner controls are not claimed complete; quarantine/scanner integration remains open |
| Maker ownership verification (INC 03) | Backend/Camunda/Bank | User task, evidence checklist, approval event and PDF–CSV totals comparison remain open |
| OCR classify/extract/abstain (M AI 01-02) | DATA-AI | Provisional foundation implemented; six official layouts and accuracy acceptance remain open |
| Income I, Expense E, Debt D and reconciliation (AFF 01/02/04) | Business Engine/Bank Policy + Backend | Candidate evidence exists; authoritative reconciliation, dedupe resolution and approval remain open |
| Proposed schedule P (AFF 05) | Business Engine/Backend | Not implemented |
| Awaiting Evidence, timer, expiry and resubmit with new version/impact list | Backend/Camunda | Not implemented |
| Residual R, monthly Q/DSR, stress and policy DMN (AFF 06-08) | Business Engine/Bank Policy | Not implemented here by design |
| Maker review, freeze, Checker separation and override escalation (CAM 05/CAT 01) | Backend/Camunda/Bank | Not implemented here |
| Export package JSON/CSV/PDF with linked hashes (ARC 06) | Backend/DATA-AI | XLSX export exists; workflow package remains open |
| Shadow/Operational G3/G4 and reopen/expiry snapshots | Backend/Camunda/Bank | Not implemented |

## Migration and verification

Apply `db/migration/V12__ocr_layout_field_governance.sql` only after confirming the database is at V11 and backing up the target schema. Use Flyway as the single migration owner. Run the OCR tests and the full suite after migration. This package's local tests do not replace PostgreSQL migration rehearsal, labeled-dataset evaluation, malware scanning, security testing or Camunda integration tests.

## Acceptance gates still needed

- Supply the six signed-off bank layouts and two signed-off bank CSV schemas.
- Supply the approved 20-field definition, requiredness by layout, aliases, normalization rules and masking rules.
- Evaluate classifier macro-F1, field precision/recall, normalized value accuracy, abstention rate and anchor accuracy on an independent labeled test set. Set thresholds with the Bank PO; do not reuse the demo 0.65/0.85 cutoffs as production SLA without calibration.
- Integrate Maker review UI and Camunda task/routing events in Backend.
- Run PostgreSQL migration rehearsal, security scan, retention/storage controls and end-to-end workflow testing.
