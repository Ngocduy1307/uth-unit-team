# DATA-AI V9.4.1 – Governance, Versioning & Maker–Checker Freeze

## Release scope

V9.4.1 adds a DATA-AI-owned immutable snapshot of case evidence/input records and an append-only Maker–Checker technical governance ledger. The implementation is deliberately bounded: Backend/SSO remains authoritative for staff identity, role grants, case assignment and authorization; Camunda 8 remains authoritative for User Tasks and process orchestration; bank policy owners remain authoritative for policy and credit decisions.

A Checker confirmation means only that an authorized, independent Checker reviewed the frozen DATA-AI evidence/input snapshot and that the technical readiness gates recorded at freeze time were clear. It is **not** a credit approval, account-ownership verification, evidence authenticity statement, accepted-income determination or authoritative I/E/D, P, R, DSR, stress or policy result.

## Delivered

- Flyway V14 adds `case_analysis_versions` with a sequential per-case version number, parent-version linkage, canonical SHA-256 snapshot hash, snapshot JSONB, readiness assessment and Maker actor.
- Flyway V14 adds `case_governance_events` as an append-only event ledger: `FROZEN`, `CHECKER_CONFIRMED`, `RETURNED_TO_MAKER` and `VERSION_SUPERSEDED`.
- Database functions serialize version creation under a case-row lock, enforce sequential versions and same-case parent linkage, require a Checker identity different from the Maker, allow only one Checker decision per version, block Checker confirmation when readiness blockers remain, and defer a constraint check so a version cannot commit without its `FROZEN` event.
- A database trigger locks case-owned input rows and `document_security_events` while the latest version is frozen or Checker-confirmed. Re-parenting an OCR field to a different document is prohibited, preventing a field from being moved out of the frozen case. `RETURNED_TO_MAKER` is the only V9.4.1 transition that re-enables source edits. The next Maker freeze creates a new immutable version and records the old returned version as superseded.
- Snapshot data covers the case and tenant/customer IDs, document receipt and detected-MIME metadata (never physical storage paths or storage object keys), sanitized append-only document security scan events (no free-form `details` payload), evidence manifest, extracted fields and source anchors, transactions, applicant form snapshots, processing/pipeline records, data-quality issues, payroll/monthly observed-income evidence, customer declarations, consent references, duplicate candidates, reconciliation runs and prior evidence-review decisions.
- Snapshot hash is computed over canonical UTF-8 JSON with sorted keys and compact separators. Snapshot schema is explicitly versioned. The detail API and Checker review recompute the hash and verify the duplicated readiness projection before exposing/confirming the snapshot.
- Readiness blockers include no evidence documents, missing manifest entries, malware scan not `CLEAN`/`EXEMPT`, missing matching append-only scan-event evidence (`CLEAN` also requires a recorded scanner engine), incomplete document processing, unresolved duplicate candidates, unresolved reconciliation runs and open critical data-quality issues. OCR abstentions/unreviewed extraction fields are retained as warnings requiring human scrutiny; no calibration is inferred.
- New API routes are added for Maker freeze, version history/detail and Checker confirm/return. All routes require the existing internal-service authentication and trusted actor/bank context.
- Every mutation writes a governance event and case audit event in the same transaction.

## API contract

| Method | Path | Role | Behavior |
|---|---|---|---|
| POST | `/api/v1/cases/{case_id}/governance/freeze` | MAKER | Lock inputs, build snapshot, hash it, create next sequential version and FROZEN event |
| GET | `/api/v1/cases/{case_id}/governance/versions` | MAKER or CHECKER | List version metadata, readiness and event history |
| GET | `/api/v1/cases/{case_id}/governance/versions/{version_id}` | MAKER or CHECKER | Read immutable snapshot and event history |
| POST | `/api/v1/cases/{case_id}/governance/versions/{version_id}/checker-review` | CHECKER | `CONFIRM` if readiness is clear, otherwise `RETURN` to Maker with reason |

### Role and tenant controls

- Identity and role values must originate in the authenticated Backend/SSO principal and be forwarded in the server-generated Signed Service Assertion. Never accept browser-supplied actor/role headers.
- Only a human `MAKER` can freeze; service identities, `BANK_ADMIN`, `SYSTEM_ADMIN` and dual-role MAKER+CHECKER contexts cannot perform Maker/Checker actions.
- Only a human `CHECKER` can confirm/return. The Checker actor ID must differ from the Maker actor ID recorded on the version.
- All routes enforce the case bank scope using the trusted assertion. Cross-bank resources are hidden as not found.
- Backend remains responsible for task assignment and verifying the actor is assigned to the corresponding Camunda User Task. DATA-AI does not query or complete Camunda tasks.

## State behavior

- First Maker freeze creates version 1 and records `FROZEN`.
- While frozen, inserts/updates/deletes to protected case-owned data tables fail at PostgreSQL level.
- Checker `CONFIRM` is allowed only when the version's stored readiness has no blockers. The state becomes `CHECKER_CONFIRMED` and remains locked.
- Checker `RETURN` writes `RETURNED_TO_MAKER`; protected source tables become editable again.
- After a return, Maker edits source records and freezes again. V14 requires the next sequential version and parent link, and records `VERSION_SUPERSEDED` for the returned version.
- A Checker-confirmed version cannot be reopened in V9.4.1. Reopen/snapshot invalidation and policy/evidence change impact are later workflow scope.
- A Checker return does not itself change Camunda task status. Backend/Camunda must consume the event or API result and manage its own task state.

## Technical readiness semantics

A snapshot may be frozen even when it is not ready for Checker confirmation. Its readiness JSON records `BLOCKED_FOR_TECHNICAL_CHECKER` and the exact blocker codes. A Checker can return it, but cannot confirm it until a later Maker version has clean readiness.

Important blockers:

- `NO_EVIDENCE_DOCUMENTS`
- `DOCUMENTS_MISSING_MANIFEST`
- `DOCUMENT_SCAN_NOT_CLEARED`
- `DOCUMENT_SCAN_EVIDENCE_MISSING`
- `DOCUMENT_PROCESSING_INCOMPLETE`
- `DUPLICATE_CANDIDATES_NOT_REVIEWED`
- `RECONCILIATION_RUNS_NOT_REVIEWED`
- `CRITICAL_DATA_QUALITY_ISSUES_OPEN`

`NEEDS_MORE_EVIDENCE` is not a terminal review decision and therefore does not clear a duplicate/reconciliation blocker. `NOT_SCANNED` does not satisfy the file-safety gate. The current service has no integrated malware scanner, so normal uploads will not be eligible for Checker confirmation until a trusted scanner integration sets a valid `CLEAN`/`EXEMPT` state and records a matching `document_security_events` row. A `CLEAN` status without a matching append-only event and scanner engine is insufficient.

## Migration and rollout

1. Confirm Flyway history is at V13 and V1–V13 were applied by the single agreed migration owner.
2. Take and restore-test a PostgreSQL backup or PITR checkpoint.
3. Apply `db/migration/V14__case_analysis_version_governance_freeze.sql` on a disposable PostgreSQL clone first.
4. Verify the new composite FKs, partial unique indexes, append-only triggers, sequential version trigger, Checker separation trigger and frozen-input guard.
5. Run a controlled concurrency test: a source write racing with Freeze must serialize on the case row and be either included in the snapshot or rejected after freeze; it must never silently change the frozen snapshot.
6. Test Maker freeze → Checker return → source edit → next Maker freeze/supersede → independent Checker confirmation with clean synthetic fixtures.
7. Verify a frozen source UPDATE/INSERT/DELETE fails with SQLSTATE `55000`, while a source edit after `RETURNED_TO_MAKER` succeeds.
8. Only then wire Backend/SSO task-assignment assertions and Camunda event handling. Do not expose DATA-AI directly to browser clients.

## Verification in this source update

- Baseline V9.3.2: 139 tests passed before changes.
- V9.4.1 source suite: run result recorded in `V9_4_1_HANDOFF.md`.
- Python compile and OpenAPI runtime/checked-in JSON parity are part of the local verification.
- PostgreSQL DDL compilation from SQLAlchemy model metadata is checked locally.

Static DDL inspection and unit tests do not replace execution of V14 against a real PostgreSQL instance. The build environment has no PostgreSQL server/`psql`/Docker runtime, so V14 trigger execution, lock/concurrency behavior, migration rehearsal and backup/restore remain staging gates.

## Explicitly not delivered

- Full Camunda 8 process, User Task assignment/completion, DMN gates or timer events.
- Actual malware scanner, quarantine/sandbox or object-storage security integration.
- Field-by-field OCR correction UI or official bank-approved OCR calibration/layouts.
- Authoritative I/E/D/P calculations, R/DSR, stress scenarios, policy DMN or narrative.
- Named Authority override/escalation and policy exception approval (V9.4.2 scope).
- JSON/CSV/PDF analysis package, G3/G4 release gates, expiry, reopen and impact-list recomputation.
- Production PostgreSQL, Backend/Spring Boot or Camunda deployment sign-off.

## Sensitive snapshot handling

`case_analysis_versions.snapshot_data` contains customer/application and financial-evidence fields required for the review record. The source archive does not implement application-level encryption for this JSONB payload. Before production use, the database owner must confirm encryption at rest (or approve an application/KMS envelope-encryption design), least-privilege grants, backup encryption, retention/legal-hold behavior, access logging and a DSR/purge policy that is consistent with the append-only governance/audit requirements. Never expose version detail through a browser-to-DATA-AI direct call; Backend must authorize assignment and purpose before proxying it.
