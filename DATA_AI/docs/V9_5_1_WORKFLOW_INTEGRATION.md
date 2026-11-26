# V9.5.1 Workflow Integration Contract

## 1. System ownership

| System | Owns | DATA-AI integration behavior |
|---|---|---|
| Spring Boot / SSO | End-user identity, assignment, bank/tenant scope, consent and named authority grants | Supplies trusted signed actor assertions and service credentials; never trusts browser role headers |
| Camunda 8 | BPMN, process instance, User Tasks, timers, notifications, DMN invocation and incident routing | Supplies process IDs, correlates business key, polls outbox events and sends signed callbacks |
| DATA-AI | Evidence intake, extraction/provenance, technical review, immutable input versions, workflow correlation/events, evidence package | Writes transactional outbox/inbox; records resubmission impact, reopen, release-gate reference and external receipts |
| Bank Business Engine / Policy | Authoritative I/E/D, proposed schedule, residual/DSR, stress, policy evaluation and override execution | Supplies exact product/policy/calculation version references and Business Engine application receipt |
| Bank release process | Operational G3/G4 acceptance and authorization | Supplies external gate reference through `RELEASE_AUTHORITY`; DATA-AI does not perform release test |

## 2. Outbox event contract

Each event is stored with `event_id`, `case_id`, `binding_id`, `event_type`, `idempotency_key`, `correlation_id`, allowlisted `payload`, `payload_sha256`, `attempts`, `status` and timestamps. Payload sanitizer discards unknown keys and rejects unsafe non-scalar values. Do not place customer PII, document content or secrets in event variables.

A worker claims by `POST /api/v1/workflow/outbox/claim` with `worker_id`, `limit` and `lease_seconds`. The worker sends the event to the target system, then calls `POST /api/v1/workflow/outbox/{event_id}/ack` with `worker_id` and decision:

- `DELIVERED`: remote system accepted the event.
- `RETRY`: delivery may be retried after bounded backoff; max 8 attempts.
- `DEAD_LETTER`: stop automatic delivery; manual incident review is required.

Only the worker holding a live lease may ACK. Delivery is at-least-once; the target must deduplicate using `idempotency_key`/`event_id`.

## 3. Inbox callback contract

`POST /api/v1/workflow/events` accepts `external_event_id`, `process_instance_id`, `process_sequence`, `event_type` and safe scalar `payload`. The callback must carry a signed `WORKFLOW_ORCHESTRATOR` assertion and trusted bank scope. The JSON Schema is `contracts/camunda-workflow-inbox-event-v1.schema.json`; examples are under `contracts/examples/`. Sequence numbers start at 1 and advance contiguously per process binding. Exact event replay returns the original event; reuse of the same external ID with different content returns conflict.

Implemented event allowlist includes process/task lifecycle, evidence expiry, case expiry, process completion and external G3/G4 pass receipts. The callback schema intentionally does not model arbitrary variables or complete arbitrary Camunda task payloads.

## 4. Evidence lifecycle

`POST /api/v1/cases/{case_id}/workflow/evidence-requests` creates an `AWAITING_EVIDENCE` row tied to the current immutable version and due time. Camunda owns the timer and sends `EVIDENCE_EXPIRED` when the due time is reached. A request cannot be expired early.

The resubmit endpoint requires all supplied docs to belong to the same case, have one manifest entry, pass manifest-chain and file SHA-256 checks, and have a valid CLEAN/EXEMPT security event. It stores immutable document IDs + an impact JSON/hash. A successful response does not create a new analysis version or recalculate income/debt/policy; the Maker reviews the impact and freezes the next version separately.

## 5. Governed reopen

A reopen can be recorded only from Checker-confirmed latest version. Evidence/external-review change uses Maker scope; policy/product change uses Bank Policy Owner scope and requires policy/product references. It opens a narrowly scoped DB exception for case-input mutation. The next Maker Freeze links the new version and consumes the reopen. No reopen record means V14 database freeze continues to reject writes.

## 6. Release and override integration

G3 Shadow and G4 Operational APIs store externally validated references. G4 requires a recorded G3 for the exact same version, product code/version and policy reference/version. G4 can only be recorded by the dedicated RELEASE_AUTHORITY role.

A Named Authority decision `APPROVED` does not imply policy execution. The Business Engine calls the application-receipt endpoint with exact proposal hash, snapshot hash, policy reference/version and external receipt reference. The assertion must contain only `BUSINESS_ENGINE`. The receipt is immutable. G4/export fail closed when the approval is not applied or receipt hashes do not match.

## 7. Evidence export

The package contains:
- `analysis.json` – immutable DATA-AI snapshot;
- `evidence.csv` – evidence file metadata/hash rows, not original binaries;
- `summary.pdf` – generated summary;
- `manifest.json` – case/version/product/policy/calculation references, evidence manifest head, audit chain head, per-file hashes and scope disclaimers.

The ZIP bytes are SHA-256 addressed and re-hashed before download. Creation requires a Checker-confirmed version, valid file bytes, complete evidence manifest, valid audit chain, no open reopen and valid override/application receipt state.

## 8. Production integration requirements

- Configure service accounts and per-service signing keys with rotation; use TLS/mTLS and private networking.
- Connect an actual Camunda worker, BPMN model, task assignment, timer, DMN and incident handler.
- Configure the actual Business Engine adapter and verify application receipt signatures/authority outside DATA-AI.
- Replace local filesystem evidence/export storage with an approved encrypted object store and staged commit process.
- Run V16 against a disposable PostgreSQL clone before production, plus backup/restore, concurrency, security, retention, load and recovery acceptance.
