# DATA-AI V9.3.2 – Evidence, Provenance & Reconciliation

**Release status:** source-level implementation complete; PostgreSQL migration rehearsal, Maker/Camunda integration and Bank Policy sign-off remain open.

## Workflow nodes advanced

This increment advances the DATA-AI-owned evidence components of the supplied `Workflow.drawio`:

- Intake & Manifest/Hash (INC 01): append-only per-case receipt manifest with SHA-256 hash chaining.
- Maker verify / PDF–CSV statement total comparison (INC 03): a machine-generated arithmetic comparison candidate, with explicit abstention and source integrity checks.
- Transaction dedupe / Maker reconcile (AFF 01 / AFF 04): exact-fingerprint duplicate pairs linked to both original transaction rows, never automatic removal.
- ARC 07 reviewability: immutable review decisions and evidence references that Backend/Camunda can attach to a Maker task.

## Implemented source changes

### 1. Evidence manifest and provenance

- Every new successful upload creates an `evidence_manifest_entries` record in the same database transaction as the document and `DOCUMENT_RECEIVED` audit event.
- A case row lock serializes sequence assignment. Each entry stores sequence, document ID, filename, MIME, byte size, SHA-256, previous entry hash, current entry hash, receipt time and trusted actor.
- Hash calculation is deterministic JSON (sorted keys, UTF-8, compact separators) followed by SHA-256. The hash version is `1`.
- PostgreSQL triggers reject UPDATE/DELETE on manifest rows. Same-case composite foreign keys prevent a manifest from referencing another case's document.
- `GET /api/v1/cases/{case_id}/evidence/provenance` verifies the chain, re-hashes stored objects, compares manifest/document metadata, and returns OCR page/bounding-box anchors plus CSV source row anchors.
- Historical documents created before V13 are not silently assigned false historical upload attribution. They are reported as `UNMANIFESTED`; use `scripts/backfill_evidence_manifest.py` in dry-run mode, review storage-missing/hash-mismatch rows, then `--apply` after V13 and backup. The actor is recorded as `LEGACY_BACKFILL`.

### 2. PDF–CSV arithmetic reconciliation

- `POST /api/v1/cases/{case_id}/evidence/reconciliations` takes a PDF statement document ID, a CSV statement document ID and an explicit VND tolerance (default zero; maximum one million VND).
- Before comparing, the API verifies each stored file exists and recomputes to the document's SHA-256. It verifies the full case manifest chain and selected source metadata.
- PDF evidence must contain unique, normalized, syntactically valid `opening_balance`, `closing_balance`, `statement_start_date` and `statement_end_date` fields with positive page numbers and finite, positive-size source bounding boxes.
- CSV transaction rows are scoped to the selected CSV document and statement period. Invalid date/amount/direction rows make the result `INCOMPLETE`; rows outside the period are counted and excluded from the arithmetic.
- The arithmetic candidate is `opening balance + credits - debits` compared with PDF closing balance. The run stores the exact source hashes, period, totals, variance, tolerance, row counts and algorithm version.
- Result states are `INCOMPLETE`, `ABSTAINED`, `BALANCE_MATCH_CANDIDATE` and `BALANCE_VARIANCE_CANDIDATE`.
- The production calibration allowlist is intentionally empty. A `CALIBRATED_*` label by itself is not accepted; no approved independent calibration corpus was supplied, so native PDF/OCR and generic/manual bases keep the overall result `ABSTAINED`, even when an arithmetic candidate can be displayed. A Maker can review the original evidence and record a decision with references to both documents.
- This operation does not verify account ownership, statement authenticity, source-bank CSV approval, or income eligibility.

### 3. Duplicate candidates

- CSV processing now creates `transaction_duplicate_candidates` pair records when two transaction rows share the same normalized exact fingerprint: date, absolute amount, direction and normalized description.
- Candidate pairs reference both original transaction IDs and preserve each row's document ID and source row.
- A duplicate candidate is not a deduplication result. No row is removed, suppressed, or excluded from an income calculation by this release.
- Candidate creation is capped at ten matching prior rows per incoming row to bound pathological fan-out; a HIGH quality issue records truncation. Existing imported rows can be scanned with `scripts/backfill_duplicate_candidates.py` (dry-run by default, explicit `--apply`).

### 4. Maker review records

- `POST /api/v1/cases/{case_id}/evidence/reconciliations/{run_id}/review` records `CONFIRMED_MATCH`, `CONFIRMED_VARIANCE`, `REJECTED` or `NEEDS_MORE_EVIDENCE`.
- `POST /api/v1/cases/{case_id}/evidence/duplicate-candidates/{candidate_id}/review` records `CONFIRMED_DUPLICATE`, `NOT_DUPLICATE` or `NEEDS_MORE_EVIDENCE`.
- Both routes require trusted Maker or authorized bank-admin role, a reason, and same-case source document references for confirmed decisions.
- Reviews are append-only. Reconciliation runs and duplicate candidate snapshots are append-only as well. Database triggers reject mutation; same-case composite foreign keys protect related source records.
- The API records a review decision only. Backend/Camunda still owns task assignment, Maker identity/ownership attestation, task completion, Checker separation, workflow state and escalations.

## New API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/cases/{case_id}/evidence/provenance` | Verify manifest chain and source anchors |
| POST | `/api/v1/cases/{case_id}/evidence/reconciliations` | Create immutable PDF–CSV arithmetic candidate |
| GET | `/api/v1/cases/{case_id}/evidence/reconciliations` | List reconciliation snapshots and latest review |
| GET | `/api/v1/cases/{case_id}/evidence/duplicate-candidates` | List exact-fingerprint transaction pairs |
| POST | `/api/v1/cases/{case_id}/evidence/reconciliations/{run_id}/review` | Append Maker reconciliation review |
| POST | `/api/v1/cases/{case_id}/evidence/duplicate-candidates/{candidate_id}/review` | Append Maker duplicate review |

All `/api/v1/**` routes retain internal service authentication and bank-scoped actor checks. Review mutations also enforce Maker / bank-admin role policy.

## Migration V13

`db/migration/V13__evidence_provenance_reconciliation.sql` adds:

- `evidence_manifest_entries`
- `transaction_duplicate_candidates`
- `evidence_reconciliation_runs`
- `evidence_review_decisions`
- composite unique keys/FKs to enforce same-case document and transaction references
- append-only triggers on manifest, candidate, reconciliation and review ledgers

Apply after V12 with the agreed single Flyway owner. Back up the schema and inspect Flyway history first. Existing documents require a reviewed manifest backfill; V13 does not invent original uploader attribution.

## Verification and limits

- Unit/contract tests cover hash-chain construction/tamper detection, sequence gaps, manifest metadata/completeness, fingerprint normalization, bounded duplicate pair generation, arithmetic match/variance, strict source anchors, calibration abstention, non-finite amount/tolerance rejection, invalid rows, period filtering, Maker role gate and OpenAPI path publication.
- Static PostgreSQL DDL compilation and SQLAlchemy model metadata compilation pass.
- The full local test suite passes in this package; live PostgreSQL V13 execution, trigger/FK behavior under real DB, concurrent upload/reconciliation tests and backup/restore rehearsal have not been run here.
- No signed-off bank PDF layouts, bank CSV schemas, independent calibration corpus or accepted reconciliation tolerance policy were supplied. This release does not claim production OCR accuracy or bank policy approval.
- No malware scanner/quarantine, account ownership verification, employment confirmation, full Maker task UI, Camunda timer/expiry/resubmit, I/E/D authority, DSR, stress, policy DMN, Maker–Checker freeze, override, JSON/CSV/PDF export package, G3/G4 or reopen are implemented by V9.3.2.

## Acceptance gates before production

1. Apply V13 in a disposable PostgreSQL clone; verify all composite FKs and immutable triggers.
2. Run the manifest backfill dry-run; review missing/mismatched storage objects; apply only after approval.
3. Test upload sequence serialization with concurrent workers, chain tamper detection, and storage corruption detection.
4. Validate PDF/CSV pair selection, bank-defined tolerance, date coverage, account ownership and bank CSV schema in Maker/Camunda workflow.
5. Confirm Maker review decisions are linked to real Camunda task IDs and actor identity supplied server-side by Backend; do not trust browser-supplied actor headers.
6. Run privacy, retention, encryption, access-control, load and recovery testing in the target environment.
