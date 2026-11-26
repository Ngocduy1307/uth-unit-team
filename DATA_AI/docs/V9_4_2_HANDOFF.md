# DATA-AI V9.4.2 – Handoff

## Release scope

V9.4.2 adds a case-scoped append-only audit chain and controlled Maker Override / Policy Exception proposal records with Named Authority decision records. It is built on V9.4.1 and adds Flyway migration `V15__audit_trail_override_authority.sql`.

## Validation performed in the source-update environment

- Baseline V9.4.1 regression: 159 tests passed before changes.
- V9.4.2 full regression: see release notes; all tests must pass in the release build.
- Python `compileall` for application, scripts and tests.
- Runtime OpenAPI exported to `contracts/data-ai-openapi.json`; route paths and security headers checked.
- SQLAlchemy metadata DDL compiled with the PostgreSQL dialect for the three V15 ORM tables.
- Static V15 migration contract checks for append-only triggers, same-case evidence references, proposal/version binding, Named Authority separation and terminal-event constraints.
- Workflow file was compared byte-for-byte with the supplied `Workflow(2).drawio`.
- ZIP integrity and SHA-256 verified after packaging.

## APIs added

1. `POST /api/v1/cases/{case_id}/governance/versions/{version_id}/override-requests`
2. `GET /api/v1/cases/{case_id}/governance/override-requests`
3. `GET /api/v1/cases/{case_id}/governance/override-requests/{request_id}`
4. `POST /api/v1/cases/{case_id}/governance/override-requests/{request_id}/authority-review`
5. `POST /api/v1/cases/{case_id}/governance/override-requests/{request_id}/withdraw`
6. `GET /api/v1/cases/{case_id}/governance/audit-trail`
7. `GET /api/v1/cases/{case_id}/governance/audit-trail/verify`

V9.4.1 Freeze and Checker confirmation now append V9.4.2 audit events in the same transaction.

## Important security and ownership boundaries

- Maker proposals are immutable and bound to the exact V14 snapshot SHA-256 and a proposal SHA-256.
- Named Authority decisions are only accepted after technical Checker confirmation and the authority actor must differ from the proposing Maker and Checker.
- Grant/scope references are recorded, but Backend/SSO must validate the real grant, active period, product/policy scope, delegation limits and MFA before signing the assertion.
- DATA-AI records an approval; it does **not** apply the override, update a policy engine, recalculate a credit decision or complete a Camunda task.
- Proposal payload reads are restricted to MAKER, CHECKER, NAMED_AUTHORITY and BANK_POLICY_OWNER. BANK_ADMIN/SYSTEM_ADMIN can read audit events and hashes but not sensitive proposal payloads. Dual MAKER+CHECKER assertions are rejected. Named Authority revalidation after Case row-lock uses a dedicated bank-scoped gate without widening general case API permissions.
- Audit hash chaining is tamper-evident but is not an external digital signature or WORM anchor. Export to independent SIEM/WORM is still required.

## Roadmap position

This release is source-level cycle 6 of 9. Remaining cycles are V9.5.1 Workflow Integration, V9.5.2 Production Testing, and V10.0 Final Acceptance.

## Production gates (not completed here)

1. Apply V15 to a disposable PostgreSQL clone at V14; inspect triggers, composite FKs, partial unique indexes and rollback behavior.
2. Run legacy audit backfill dry-run; validate counts/order; apply once only after verified backup/PITR.
3. Test concurrent audit appends, cross-bank access, wrong grant/scope, stale snapshot, duplicate decisions, expiry and same-case evidence references on PostgreSQL.
4. Configure Backend/SSO authority registry and assignment validation; do not accept caller-supplied grant references without assertion-side validation.
5. Integrate Business Engine consumption of the exact approved proposal hash and Camunda task/timer/escalation correlation.
6. Configure KMS/application encryption for sensitive JSON, independent SIEM/WORM export, retention, backup encryption and restore testing.

No live PostgreSQL server, `psql` or Docker runtime was available for this source-only update. PostgreSQL-dialect DDL compilation and static migration contract tests do not replace executing Flyway V15 on the target PostgreSQL version.
