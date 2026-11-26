# DATA-AI V9.4.1 – Handoff

## Baseline and source

- Baseline: supplied `DATA_AI_V9_3_2_EVIDENCE_RECONCILIATION_UPDATE.zip`.
- Workflow source: supplied `Workflow(2).drawio`.
- Workflow was checked against the copy at `docs/Workflow.drawio`; both SHA-256 values were `7a86f4cad227a0112f02f76e72b9d93db7c44cf3d5c2c930971e5a8771fdd6b7`.
- V9.3.2 archive integrity and supplied `.sha256` passed before editing.
- Baseline test suite: 139 passed.

## Release contents

- V14: `case_analysis_versions` and `case_governance_events`.
- ORM: `CaseAnalysisVersion`, `CaseGovernanceEvent`.
- Service logic: `app/governance.py` (canonical snapshot hashing, readiness assessment, role separation and state derivation).
- API: Maker freeze, version list/detail and Checker confirm/return.
- Database: sequential version and parent check, deferred requirement for a FROZEN event, independent Checker transition validation, append-only snapshot/event triggers, and source mutation lock while frozen (including `document_security_events` and prevention of OCR-field document reparenting).
- OpenAPI: 36 paths total, including four governance paths.
- Tests: governance role/state/readiness/schema checks, scan-event evidence, snapshot integrity checks, sanitized snapshot scope and V14 migration contract tests.

## Test result

Final result: **159 passed** (`pytest -q`). The supplied V9.3.2 baseline was 139 passed; V9.4.1 adds coverage for canonical hashing, Maker/Checker role split, state transitions, technical blockers, auditable scan events, persisted snapshot integrity, tenant/security provenance capture, API path coverage, ORM/migration alignment and frozen mutation guard coverage.

Additional local checks: Python `compileall`, OpenAPI JSON parity, PostgreSQL dialect compilation of both new ORM tables/indexes, Docker Compose YAML parse, Workflow XML parse, ZIP integrity and SHA-256 checksum.

## Operational blockers

- V14 was not executed against a PostgreSQL server. No PostgreSQL/psql/Docker runtime is available in this environment.
- The service does not currently integrate a malware scanner. Documents whose scan status is `NOT_SCANNED` block Checker confirmation. A `CLEAN`/`EXEMPT` column value by itself is also insufficient; the snapshot requires a matching append-only `document_security_events` event (and scanner engine for `CLEAN`).
- Backend/SSO must supply trusted, assigned Maker/Checker identities in signed assertions. DATA-AI's role catalogue is not the source of role grants.
- Camunda task assignment/completion is not implemented in DATA-AI. Backend/Camunda must correlate process tasks and this governance record.
- Checker-confirmed versions stay locked. Reopen/impact-list handling is later roadmap scope.
- No calculation/policy/credit decision has been added. Snapshot is evidence/input only. Snapshot JSONB contains customer/application and financial-evidence fields; production must confirm encryption at rest, least-privilege access, encrypted backups, retention/legal-hold and DSR/purge policy. Application-level KMS envelope encryption is not implemented in this release.

## Deployment sequence

1. Backup/restore rehearsal and Flyway history check at V13.
2. Apply V14 on disposable PostgreSQL clone.
3. Test frozen mutation rejection, return-to-Maker unlock and re-freeze versioning.
4. Run concurrent writer vs Freeze race test.
5. Validate signed role provenance and bank scoping through Backend/SSO.
6. Verify the deferred `FROZEN` constraint and matching scan-event readiness checks.
7. Integrate Camunda task correlation without treating Checker confirmation as credit approval.

## Source archive exclusions

No `.env`, credentials, real customer documents, virtual environments, local DB volume or generated storage files are included.
