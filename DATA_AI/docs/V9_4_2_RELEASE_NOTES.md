# DATA-AI V9.4.2 – Audit, Override & Policy Exception

## Delivered

- V15 adds a per-case monotonically sequenced, SHA-256 hash-chained `case_audit_entries` ledger. PostgreSQL locks the case row and validates bank scope, next sequence and previous-head hash; UPDATE/DELETE are blocked.
- V9.4.1 Maker Freeze and Checker Confirm/Return mutations now append V15 audit rows in the same transaction.
- Added audit page and full-chain verification endpoints.
- Added immutable Maker `OVERRIDE` / `POLICY_EXCEPTION` requests tied to a V14 snapshot hash, exact proposal hash, policy reference/version, reason, impact summary and mandatory same-case evidence refs.
- Added append-only `REQUESTED`, `APPROVED`, `REJECTED`, `WITHDRAWN` events with one terminal outcome per request.
- Added dedicated `NAMED_AUTHORITY` role/permission reference and checks requiring an independent authority actor distinct from the proposing Maker and version Checker.
- Approval is bound to the exact proposal hash, requires authority grant/scope references and a future timezone-aware expiry; expired state is derived from `valid_until`.
- Added dry-run-first `scripts/backfill_case_audit.py` to import legacy `audit_events` without mutating them. Legacy detail payloads are reduced to a SHA-256 digest rather than copied in full.
- OpenAPI updated to 43 paths; ERD, authorization contract, RBAC catalogue, DB table catalogue and Workflow API traceability updated.

## Important boundaries

- Backend/SSO must validate Named Authority grant, scope, limits, effective dates, assignment and MFA before signing. DATA-AI only records the grant/scope references.
- `APPROVED` is an auditable approval record only. It does not apply the override, update the policy engine, calculate credit or complete a Camunda task.
- Hash-chain verification is tamper-evident but is not a digital signature or external WORM anchor. Independent SIEM/WORM export remains required.
- Existing legacy `audit_events` are not automatically migrated by V15; run the script in dry-run then `--apply` after V15 on a verified clone, before enabling new writes.

## Verification

- Full pytest suite: **173 passed** (V9.4.1 baseline 159 passed).
- Python source/script/test compile and OpenAPI runtime parity are checked.
- PostgreSQL dialect DDL compilation covers the three V15 ORM tables/indexes.
- V15 SQL migration is inspected by contract tests but was not executed against a real PostgreSQL instance in this environment.

## Migration

Apply `V15__audit_trail_override_authority.sql` after V14. Do not edit older migrations. Run the clone/backup/trigger/concurrency rehearsal in `V9_4_2_AUDIT_OVERRIDE_AUTHORITY.md`.

- Proposal-detail read access is narrower than audit-ledger access: BANK_ADMIN/SYSTEM_ADMIN may inspect audit events and hashes but are not allowed to read requested-change/impact-summary payloads.
- Named Authority post-lock authorization now uses a dedicated bank-scoped verifier; it does not widen the general DATA-AI case access roles. Maker/Checker dual-role assertions are denied for proposal detail access.
- Backfill remains dry-run by default and must be rehearsed on a V15-migrated PostgreSQL clone before applying.
