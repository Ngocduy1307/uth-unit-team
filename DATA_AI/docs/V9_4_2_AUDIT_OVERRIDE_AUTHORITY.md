# DATA-AI V9.4.2 – Audit, Override & Policy Exception Governance

## Scope and ownership

V9.4.2 adds DATA-AI records and integrity controls for the `Audit`, `Override / Policy Exception` and `Named Authority` nodes under CAT 01 in `Workflow.drawio`. It is not a bank policy engine or workflow engine.

- Backend/SSO remains authoritative for identity, staff assignment, Named Authority grants, active dates, bank/product/policy scope, limits, delegation and MFA.
- Bank Policy Owner remains authoritative for the published policy reference/version and its interpretation.
- Business Engine/Backend remains responsible for checking whether a recorded approval is valid for the current calculation/process and for applying an authorized change.
- Camunda remains authoritative for User Task assignment/completion, escalation timers, notifications and process state.
- DATA-AI binds a proposal to a V14 immutable evidence/input version, records the authority decision and exposes a tamper-evident audit history. It does not compute DSR, decide credit, apply an override, update policy or complete a Camunda task.

## 1. Hash-chained case audit

Flyway V15 adds `case_audit_entries`:

- Monotonic `sequence_no` per case, serialized by a PostgreSQL case-row lock.
- `previous_entry_sha256` links each event to the preceding event; the first event uses 64 zeroes.
- `entry_sha256` covers canonical JSON containing case/bank scope, sequence, actor/role, action/entity, request correlation ID, version reference, reason, before/after hashes, redacted details, previous hash and occurrence timestamp.
- The insert trigger enforces matching bank scope, sequential numbering and previous-head continuity. UPDATE/DELETE are rejected by the database trigger.
- `GET /api/v1/cases/{case_id}/governance/audit-trail` reads a bounded page after a sequence number.
- `GET /api/v1/cases/{case_id}/governance/audit-trail/verify` recomputes every entry hash and checks sequence/previous-hash continuity.

The V9.4.1 Freeze and Checker endpoints now append corresponding entries in the same transaction as the governance event. V9.4.2 proposal creation, withdrawal and Named Authority decisions also append entries in the same transaction. The old `audit_events` table remains available for older application activity.

Hash chaining is tamper-evident, not a digital signature or an externally anchored WORM system. A database owner capable of replacing the entire ledger could recompute hashes. Production still needs independent SIEM/WORM export, access controls, retention, backup encryption and periodic external anchoring.

### Legacy audit backfill

`scripts/backfill_case_audit.py` copies existing case-scoped `audit_events` into the V15 ledger while retaining source row ID/action and a SHA-256 digest of legacy details (not the raw legacy details). It is dry-run by default:

```bash
python scripts/backfill_case_audit.py
python scripts/backfill_case_audit.py --case-id <CASE_UUID>
```

Only after V15 is migrated on a disposable/staging database and a restorable backup is verified, run:

```bash
python scripts/backfill_case_audit.py --apply
```

Run the backfill before enabling V9.4.2 mutation routes in a target environment so imported history is appended in source order ahead of new live events. The script does not mutate or delete the legacy `audit_events` rows.

## 2. Maker Override / Policy Exception proposal

`POST /api/v1/cases/{case_id}/governance/versions/{version_id}/override-requests`

A dedicated Maker (the actor who created the linked V14 version) may create an immutable proposal with:

- `request_kind`: `OVERRIDE` or `POLICY_EXCEPTION`;
- `exception_code`;
- `policy_reference` and `policy_version` as supplied from the bank policy context;
- a reason, proposed-change JSON and impact-summary JSON;
- one or more `evidence_refs` that must resolve to records belonging to the same case;
- `version_sha256`, binding the request to the immutable V14 snapshot;
- `proposal_sha256`, covering the complete canonical proposal.

The database enforces the same-case version relationship, that the requester is the Maker recorded on that version, frozen/current version state at request creation, unique proposal hash per version, and same-case evidence references. The proposal and its `REQUESTED` event cannot be updated or deleted.

Requests may be created while the version is `FROZEN` (status `PENDING_CHECKER`) or after technical Checker confirmation (status `PENDING_AUTHORITY`). The Maker cannot change the request after submission. A changed proposal requires a new evidence/input version and a new request.

## 3. Named Authority decision

`POST /api/v1/cases/{case_id}/governance/override-requests/{request_id}/authority-review`

The actor must present the `NAMED_AUTHORITY` role in the Backend-signed assertion. The request body must include `authority_grant_ref` and `authority_scope_ref`, which Backend/SSO must validate as current and applicable before signing. DATA-AI records these references; it does not query the grant registry or infer limits from a role label.

A decision is accepted only when:

- the linked V14 version remains `CHECKER_CONFIRMED` and its SHA-256 still verifies;
- the stored proposal hash recomputes exactly;
- the authority actor differs from the proposing Maker and the Checker who confirmed the version;
- no prior terminal decision exists;
- the authority grant/scope references and reason are present;
- approval has a future timezone-aware `valid_until`.

`APPROVE` and `REJECT` are append-only terminal outcomes. Approval is bound to the exact `proposal_sha256`; editing the request or approving a different proposed value is not possible. Expiry is exposed as a derived `EXPIRED` status when `valid_until` is passed. A background timer/notification/escalation remains Backend/Camunda-owned.

The API explicitly returns `override_applied: false`, `policy_engine_updated: false` and `camunda_task_completed: false`. Backend/Business Engine must separately validate the decision and carry out the permitted change. A new decision or changed terms require a new governed request; they are not edits to the original event.

## 4. API summary

| Method | Route | Required role | Meaning |
|---|---|---|---|
| POST | `/api/v1/cases/{case_id}/governance/versions/{version_id}/override-requests` | MAKER | Submit immutable override/exception proposal |
| GET | `/api/v1/cases/{case_id}/governance/override-requests` | MAKER, CHECKER, NAMED_AUTHORITY, BANK_POLICY_OWNER | List proposal details and derived state |
| GET | `/api/v1/cases/{case_id}/governance/override-requests/{request_id}` | Same as list | Read proposal and event history |
| POST | `/api/v1/cases/{case_id}/governance/override-requests/{request_id}/authority-review` | NAMED_AUTHORITY | Approve/reject after technical Checker confirmation |
| POST | `/api/v1/cases/{case_id}/governance/override-requests/{request_id}/withdraw` | Original MAKER | Withdraw while pending |
| GET | `/api/v1/cases/{case_id}/governance/audit-trail` | Scoped human governance/audit role | Read audit pages |
| GET | `/api/v1/cases/{case_id}/governance/audit-trail/verify` | Scoped human governance/audit role | Verify full hash chain |

All routes remain internal service endpoints, bank scoped, protected by the internal token and signed service assertion. Do not expose DATA-AI directly to browser clients. Broad `BANK_ADMIN`/`SYSTEM_ADMIN` audit readers can inspect the audit hash/event ledger, but are intentionally denied the sensitive `requested_change` and `impact_summary` proposal payload endpoints. Backend/SSO must sign only case-assigned Maker/Checker and correctly assigned Named Authority/Policy Owner identities for proposal reads; the role alone is not a case assignment.

## 5. Database objects and migration

V15 adds:

- `case_audit_entries` – per-case sequence and hash chain;
- `case_override_requests` – immutable Maker proposal;
- `case_override_events` – append-only request/decision/withdrawal events;
- reference role `NAMED_AUTHORITY` and permissions `OVERRIDE_APPROVE`, `POLICY_EXCEPTION_APPROVE`, `CASE_GOVERNANCE_AUDIT_VIEW`.

All tables have same-case foreign keys where relevant and UPDATE/DELETE protections. A terminal partial unique index permits only one of `APPROVED`, `REJECTED` or `WITHDRAWN` for a request.

Apply `V15__audit_trail_override_authority.sql` after V14. Never edit V1–V14. Use one agreed Flyway owner. Run a PostgreSQL clone rehearsal for triggers, index creation, foreign keys, concurrent audit inserts and rollback before staging.

## 6. Deployment and integration gates

1. Restore a backup/PITR checkpoint on a disposable PostgreSQL clone at V14.
2. Apply V15; verify three tables, composite FKs, unique proposal/terminal indexes and append-only triggers.
3. Run the legacy audit backfill in dry-run, inspect counts, then apply once on the clone.
4. Run audit-trail page and verify APIs; intentionally alter a row only on the disposable clone to ensure verification fails, then restore the clone.
5. Test Maker proposal → Checker confirm → Named Authority approve/reject; verify same-actor, cross-bank, stale-version, duplicate decision, expiry, cross-case evidence and wrong-grant/scope cases.
6. Backend/SSO must validate the grant reference against actor, bank, product, exception type, limits and effective dates before it signs the request.
7. Business Engine must consume the approved exact proposal hash separately; do not treat the DATA-AI API response as a policy execution command.
8. Camunda must maintain its own task assignment, state, timer, notifications and escalation. Correlate its process/task IDs in Backend-owned logs and integration metadata.
9. Export audit records to independent WORM/SIEM storage; verify backup encryption, retention and restore procedures.

No real PostgreSQL server, `psql` or Docker runtime is available in this source-update environment. V15 has static contract checks and SQLAlchemy PostgreSQL-dialect DDL compilation, but migration execution, trigger behavior and concurrency remain staging gates.

## Explicitly not delivered

- Authoritative Named Authority grant registry, delegation limits, scope/date evaluation, MFA or staff assignment validation.
- Bank policy evaluation, calculations, DSR/stress, approval of credit or actual execution of an override.
- Camunda User Task, timer, expiry notification, escalation routing or task completion.
- External WORM/SIEM anchor or database-owner-resistant digital signature of the audit chain.
- Application-level KMS encryption of sensitive snapshot/proposal JSON.
