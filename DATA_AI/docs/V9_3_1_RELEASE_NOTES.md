# DATA-AI V9.3.1 – OCR Governance Foundation

- Adds six provisional generic document profile entries; none is bank-approved.
- Versions the current provisional 20-field candidate catalogue.
- Adds conservative classification abstention for no signal, ambiguous family and low heuristic score.
- Adds format validation and explicit field-level `SUGGEST`/`ABSTAIN` decisions.
- Makes native PDF text confidence basis explicit and requires Maker review because native-text presence is not a calibrated accuracy score.
- Adds extraction decision/provenance persistence through Flyway V12.
- Adds read-only trusted API `GET /api/v1/admin/ocr/catalog`.
- Adds processing summary counts and quality issues for classification/field abstentions.

This is not acceptance of the six bank layouts or production OCR accuracy. The exact layouts, final SRS field catalogue and thresholds require Bank/PO sign-off and independent labeled data. It does not implement the Backend/Camunda Maker task, full evidence reconciliation, expense/debt/DSR calculation, policy or credit decisions.

## Local verification

- Automated suite: **114 passed**.
- Python compileall: passed.
- OpenAPI artifact: valid JSON and matches runtime schema.
- Docker Compose file: valid YAML.
- Live PostgreSQL/Flyway V12 execution, bank-layout labeled-data evaluation and Camunda integration were not run.
