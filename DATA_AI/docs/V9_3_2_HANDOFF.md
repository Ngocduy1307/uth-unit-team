# DATA-AI V9.3.2 Handoff

**Baseline:** user-supplied `DATA_AI_V9_3_1_OCR_GOVERNANCE_UPDATE(1).zip` and `Workflow(2).drawio`.

## Source integrity of inputs

- Supplied V9.3.1 ZIP SHA-256: `550b2b477db706f32c87d79f5fe5178905bf7de367317cf2323857283f514e0a`; matched its accompanying SHA-256 file.
- `Workflow(2).drawio` SHA-256: `7a86f4cad227a0112f02f76e72b9d93db7c44cf3d5c2c930971e5a8771fdd6b7`; matched `DATA_AI/docs/Workflow.drawio` before changes and remains byte-for-byte preserved.

## Implemented

- V13 append-only case evidence manifest with sequence and SHA-256 hash chain; new successful uploads create manifest rows in the same transaction as document metadata and audit event.
- Provenance API verifies manifest-chain metadata, recomputes stored-file SHA-256, compares all receipt metadata fields (filename, digest, MIME and byte length), reports manifest completeness separately from metadata parity, and exposes OCR/page/bbox and CSV/source-row lineage.
- Safe legacy manifest backfill script with dry-run default, stored-byte checks and explicit `--apply`; backfilled actor attribution is `LEGACY_BACKFILL`.
- Legacy transaction duplicate candidate scan script with dry-run default and explicit `--apply`; no transaction is automatically hidden/deleted.
- PDF–CSV statement balance arithmetic candidate API, selected source-document byte hash verification, positive page and finite positive bounding-box checks, finite-number validation, CSV period filtering, explicit incomplete/abstained/variance states and immutable run snapshots.
- The production reconciliation calibration allowlist is intentionally empty. No arbitrary `CALIBRATED_*` label is accepted; the supplied package contains no approved independent calibration corpus, so all current native PDF/OCR/manual bases remain `ABSTAINED`. Test fixtures enable a synthetic basis only inside the test process.
- Structured transaction duplicate pair candidates with exact fingerprint hash and links to original document/row IDs. Duplicate candidates do not auto-delete or suppress transactions.
- Append-only Maker review decision API for reconciliation and duplicate candidates, with trusted-role enforcement, mandatory reason, same-case source references and Camunda task-completion boundary.
- Same-case composite FK constraints for manifest/document, duplicate/transaction, reconciliation/document and review/target relationships. ORM and V13 DDL now include the same target-link/decision-code guards; migration-contract tests protect this parity. Review API rejects meaningful-text violations and blocks duplicate confirmation when source-document references are missing.
- OpenAPI JSON, API notes, V9.3.2 design/handoff docs, DB catalog and workflow traceability updated.
- User-supplied `Workflow.drawio` preserved byte-for-byte.

## Test results

- Baseline before V9.3.2 changes: **114 passed**.
- Final V9.3.2 local suite after integrity hardening: **139 passed** (25 additional tests over baseline).
- `python -m compileall -q app tests scripts`: passed.
- Docker Compose YAML parsing and `docs/Workflow.drawio` XML parsing: passed.
- `contracts/data-ai-openapi.json` regenerated from runtime FastAPI app and matched exactly: passed (32 paths).
- `build_duplicate_pairs` tests added for stable, bounded candidate pair generation; manifest metadata/completeness, calibration abstention, invalid bounding boxes and non-finite amounts are also covered.
- SQLAlchemy PostgreSQL DDL compilation for new models: passed.
- Runtime OpenAPI vs checked-in JSON contract test: passed.
- Full migration execution on live PostgreSQL: not run in this environment.

## Workflow traceability delta

| Workflow node | V9.3.2 result |
|---|---|
| Intake Manifest/Hash (INC 01) | Source-level append-only hash-chained manifest for new uploads; legacy backfill tool included |
| File integrity / zero silent loss | Reconciliation API re-hashes selected stored objects; this is not malware scanning/quarantine |
| Maker PDF–CSV totals comparison (INC 03) | Arithmetic candidate snapshot and Maker review record APIs; account ownership and task completion remain external |
| Transaction cross-check / duplicate resolution (AFF 01/04) | Exact-match pair candidates with two source references; Maker decision appended, no auto deletion |
| OCR field provenance | Page/bbox/method/catalogue metadata exposed via provenance endpoint |
| Other workflow nodes | No change to consent DMN, Camunda timers, Awaiting Evidence/Expired/resubmit, proposed schedule, I/E/D authority, DSR/stress/policy, Maker–Checker/Freeze/Override, export package, G3/G4 or reopen |

## Migration and deployment

- Added `db/migration/V13__evidence_provenance_reconciliation.sql` after V12.
- Apply via the single agreed Flyway owner only after backup and review.
- Existing pre-V13 documents are not automatically backfilled; run `python scripts/backfill_evidence_manifest.py` first as dry-run, then `--apply` after reviewing the report and storage bytes.
- `EvidenceManifestEntry`, duplicate candidate, reconciliation snapshot and review decision tables are protected by append-only triggers. The tables cannot be updated/deleted through ordinary application SQL; retention/purge needs a governed DBA process.

## Important caveats

- A balance match is `BALANCE_MATCH_CANDIDATE`, not proof of authenticity, account ownership or income eligibility.
- Native PDF text and OCR confidence remain uncalibrated; these inputs cause `ABSTAINED` until a Maker reviews the source.
- Current CSV adapter remains generic and `PENDING_BANK_SIGNOFF`; no two official bank CSV schemas or signed-off layouts were supplied.
- Current tolerance is an explicit API input with default zero and max 1,000,000 VND. This is a technical bound, not a bank-approved tolerance policy.
- Maker review API records evidence review; Backend/Camunda owns assignment, task completion, Checker separation, expiry and escalation.
- V13 has static/model-level validation only; no `psql`, PostgreSQL server or Docker runtime was available in this environment. Real PostgreSQL migration rehearsal, trigger/FK tests, concurrent load and recovery remain open.
