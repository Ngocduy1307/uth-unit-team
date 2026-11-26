# DATA-AI V9.4.1 – Governance, Versioning & Maker–Checker Freeze

## Delivered

- V14 immutable per-case evidence/input snapshots with canonical SHA-256 hash and sequential version lineage.
- Append-only `FROZEN`, `CHECKER_CONFIRMED`, `RETURNED_TO_MAKER` and `VERSION_SUPERSEDED` event ledger.
- Maker-only freeze and independent Checker confirm/return APIs.
- Maker and Checker must be distinct signed-assertion actor IDs; dual Maker+Checker role contexts and service identities are denied.
- PostgreSQL row locking serializes Freeze against case-owned data writes; frozen source data and append-only document security scan events remain immutable until a Checker returns the version. A deferred database constraint prevents a version row from committing without its FROZEN event.
- Checker confirmation requires no unresolved technical readiness blockers, including a matching append-only scan event for every `CLEAN`/`EXEMPT` document (and a recorded scanner engine for `CLEAN`).
- Snapshot reads and Checker confirmation recompute SHA-256 and confirm the readiness projection matches the hashed snapshot.
- OpenAPI contract updated to expose four governance routes and typed request schemas.
- Workflow traceability, table catalog, ERD, migration guide and handoff documentation updated.

## Verification

See `docs/V9_4_1_HANDOFF.md` for exact results. V9.3.2 baseline was 139 tests; V9.4.1 adds governance and migration-contract coverage. Source compile, OpenAPI parity, schema DDL compilation and archive integrity are checked locally.

## Important boundary

Checker confirmation is a DATA-AI evidence/input technical review only. It is not a credit decision and does not complete a Camunda task. Backend/SSO remains authoritative for identities, role grants, staff assignment and bank authorization. Camunda remains authoritative for process/task state. V9.4.2 is expected to address audit/override/policy exception and authority escalation.

## Migration

Apply `V14__case_analysis_version_governance_freeze.sql` after V13. Never edit older migrations. Execute V14 on a disposable PostgreSQL clone and complete lock/concurrency/trigger rehearsal before staging. Do not migrate shared/production data without a restorable backup and a single agreed Flyway owner.

## Not yet verified

No real PostgreSQL instance, psql or Docker runtime was available in the source-update environment. SQL trigger execution and the deferred constraint still require disposable-PostgreSQL verification. Migration execution, trigger/FK behavior, transaction races, backup/restore, full Backend integration and Camunda task correlation remain open.
