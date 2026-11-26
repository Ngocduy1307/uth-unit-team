# V9.3.1 Handoff

**Baseline:** user-supplied `DATA_AI_V9_2_3_API_RELIABILITY_UPDATE(1).zip` + `Workflow(1).drawio`.

## Implemented in source

- Versioned OCR field catalogue and six provisional generic profiles.
- Abstention on weak/ambiguous classification.
- Field-level normalization validation and `SUGGEST`/`ABSTAIN` decision.
- Explicit confidence basis and source-anchor requirement.
- Native PDF text layer marked uncalibrated; not treated as an accepted value.
- Pipeline summary and quality findings for abstentions.
- Read-only OCR governance catalogue API.
- Flyway V12 to persist extraction governance metadata.
- Workflow/API traceability refreshed.

## Verification

- Starting baseline: 96 tests passed before changes.
- Final local suite: **114 passed**.
- `python -m compileall -q app tests`: passed.
- OpenAPI JSON parse and checked-in-vs-runtime contract test: passed.
- Docker Compose YAML parse: passed.
- New test coverage includes profile/field counts, sign-off status, classifier tie/low-signal abstention, native PDF confidence basis, low OCR confidence, date normalization/invalid dates, missing anchors, API role enforcement and V12 schema contract.

## Migration

- Added `db/migration/V12__ocr_layout_field_governance.sql`; apply after V11 only after backup and Flyway history review.
- V12 was validated statically and through schema-contract tests, but was not run against a live PostgreSQL server in this environment.

## Not completed / not claimed

- Six actual bank-approved layouts and two official CSV schemas are not present in the uploaded source; they cannot be fabricated.
- Exact SRS 20 fields and requiredness need approval; current 20 labels are provisional.
- No independent labeled corpus is supplied; accuracy/calibration figures are not claimed.
- Maker verification/review, Camunda timers/events, reconciliation, financial engine, Maker–Checker/Override, G3/G4 and reopen remain assigned to Backend/Camunda/Business Engine/Bank.
- Malware scanner and production quarantine remain separate Security/Platform gates.
- PostgreSQL V12 has not been run against a real target database in this local code package.

## Next workflow increment

The next roadmap item remains V9.3.2 – Evidence & Reconciliation: source provenance, PDF–CSV cross-check, transaction duplicate resolution, evidence coverage and Maker-facing review records. Do not add final income/debt/DSR decisions to DATA-AI; the Business Engine/Bank Policy remains authoritative.
