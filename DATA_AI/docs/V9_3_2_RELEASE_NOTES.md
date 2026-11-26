# DATA-AI V9.3.2 – Evidence, Provenance & Reconciliation

## Release scope

V9.3.2 is the fourth source-level cycle in the nine-cycle roadmap. It continues from the supplied V9.3.1 OCR governance package and the latest supplied `Workflow(2).drawio` diagram.

## Delivered

- Flyway V13 adds append-only per-case evidence manifest entries with a deterministic SHA-256 hash chain.
- New document uploads append manifest metadata in the same database transaction as the document and audit row.
- Provenance endpoint re-hashes stored bytes and compares all duplicated receipt metadata: filename, SHA-256, MIME type and byte length. It reports manifest completeness separately from metadata equality.
- PDF–CSV bank statement comparison produces an immutable arithmetic candidate containing period, opening/closing balance, credits, debits, tolerance and variance.
- Extracted PDF fields must be unique, syntactically valid and have positive page numbers and finite positive-size bounding boxes.
- The production reconciliation calibration allowlist is intentionally empty. A `CALIBRATED_*` label alone is not trusted; no independent bank-approved calibration corpus was supplied, so ordinary native PDF/OCR and generic/manual bases abstain.
- Exact-fingerprint transaction duplicates are stored as pair candidates tied to source transaction IDs and their original document/row lineage. Candidate generation is bounded and deterministic; no transaction is deleted or excluded.
- Append-only Maker review events require an authorized role, meaningful reason text and same-case source-document references for confirmed outcomes. Missing source documents block duplicate confirmation.
- Legacy manifest and duplicate candidate backfills are dry-run by default and require explicit `--apply`.
- Workflow traceability, ERD, database catalog, migration guide, API handoff and release notes are updated.

## Verification

- Baseline V9.3.1 suite: 114 passed.
- Final V9.3.2 suite: **139 passed**.
- `python -m compileall -q app tests scripts`: passed.
- `docs/Workflow.drawio` XML and Docker Compose YAML parse: passed.
- PostgreSQL dialect DDL compilation for the new ORM tables: passed.
- OpenAPI schema generation and contract tests: passed.
- Migration structure/ORM parity tests and supplied workflow SHA-256 checks: passed (see handoff).

## Migration

Apply `db/migration/V13__evidence_provenance_reconciliation.sql` after V12 via the agreed single Flyway owner. Review Flyway history and take a restorable backup first. Run `scripts/backfill_evidence_manifest.py` and `scripts/backfill_duplicate_candidates.py` in dry-run mode before considering `--apply`.

## Explicit non-claims / open gates

- V13 was not executed against a live PostgreSQL instance in this environment (no PostgreSQL server, `psql` or Docker runtime was available).
- PostgreSQL trigger/FK runtime behavior, concurrent upload sequencing, staging load, backup/restore and retention/restore drills remain unverified.
- The service does not verify bank statement authenticity, account ownership, employment, approved bank CSV schema, income eligibility, I/E/D totals, DSR, stress or credit decision.
- A reconciliation candidate is not a Maker decision. The review API records an append-only evidence review event but does not assign or complete a Camunda User Task.
- Malware scanning/quarantine, Awaiting Evidence timers/expiry/resubmission, Maker–Checker freeze, Checker/override authority, JSON/CSV/PDF package export, G3/G4 and reopen remain open workflow items.
