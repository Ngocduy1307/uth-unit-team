# DATA-AI V9.5.2 — Production Security & Recovery Hardening

## Scope and relationship to Workflow(3)

This release hardens the DATA-AI ownership boundary in `Workflow(3).drawio`. It does not implement the Bank's consent DMN, Camunda BPMN timers/user tasks, credit calculations, policy thresholds, or final operational release decisions.

### Workflow controls delivered

| Workflow node / branch | DATA-AI V9.5.2 behavior | Boundary / remaining owner |
|---|---|---|
| `n-intake` — Manifest & Hash | Upload content is checked against its extension, MIME is derived from file bytes, storage files are private, and existing case manifest hashing remains enabled. | Backend still owns applicant identity and legal intake fields. |
| `n-scope` / `gw-scope` — Consent & scope DMN | Existing signed tenant context remains mandatory; no consent result is inferred from a file upload. | Bank DMN / Backend must provide the authoritative decision and consent evidence. |
| `n-safe` / `gw-file` — File safety | New ClamAV INSTREAM adapter, scanner version, exact scanned SHA-256, immutable scan event, and fail-closed handling. | ClamAV daemon must be deployed on a private network. An unavailable scanner returns 503 and never maps to CLEAN. |
| `n-quarantine` — Quarantined / Rejected | INFECTED documents are moved to a private quarantine directory, marked `QUARANTINED`/`BLOCKED`, and emit a no-PII workflow event. | Bank retention, forensic response, and operator notification remain infrastructure/process responsibilities. |
| `n-maker-verify` — Ownership, period, PDF–CSV totals, employment | Existing Maker/evidence review APIs remain the review boundary. | The Maker and Bank source systems must establish account ownership, statement period, totals, and employment facts. DATA-AI does not infer ownership. |
| `n-extract` / `n-manual-extract` | OCR/processing now rejects any document without a V1_CLAMAV CLEAN attestation bound to the current file hash. Existing OCR abstention behavior remains. | Camunda owns service/user task routing and outage/manual work assignment. |
| `n-inc`, `n-exp`, `n-debt`, `n-maker-reconcile`, `n-schedule` | Existing extraction, reconciliation, evidence and version references remain available. | Authoritative I/E/D decisions and proposed repayment schedule are still Bank/Business Engine responsibilities. |
| `n-awaiting`, `gw-timer`, `n-exp-wait`, `n-resubmit` | V9.5.1 evidence lifecycle/outbox APIs remain; file safety must be re-run on resubmitted documents. | Camunda owns timer execution; Backend/Bank owns evidence request content and deadlines. |
| `n-calc`, `n-calc-hold`, `n-stress`, `n-policy`, `n-explain` | Existing integration boundary and incident/event references remain. | Residual, DSR/Q, stress scenarios, DMN policy and narrative are external Business Engine/Bank functions. |
| Freeze / Checker / Override / Named Authority | Existing V9.4.1/V9.4.2 governance controls remain; scan attestation is now a readiness precondition. | Backend/SSO remains the source of identity, assignments and authority grants. |
| Export / G3 / G4 / post-event Reopen | Existing V9.5.1 hashed JSON/CSV/PDF package, release-gate references and reopen lifecycle remain. | G3/G4 external release decisions, operational use and post-completion policy events remain externally governed. |

## V9.5.2 implementation

### 1. Byte-bound malware scan

- `POST /api/v1/cases/{case_id}/documents/{document_id}/security-scan`
- The caller must be a dedicated `DOCUMENT_SCANNER` service identity in the signed Backend assertion, scoped to the same bank.
- DATA-AI streams the stored bytes to ClamAV using `zINSTREAM` and records the returned engine version.
- Scanner opens a no-follow file descriptor and computes SHA-256 over the exact bytes streamed to ClamAV. DATA-AI compares that stream digest with the document SHA-256 and a separate post-scan storage rehash.
- A `CLEAN`/`INFECTED` event records the exact `scanned_sha256` and `attestation_version=V1_CLAMAV`.
- Unknown replies, daemon outage, invalid file path, or hash drift fail closed. No synthetic CLEAN status is generated.
- INFECTED content is moved under `<STORAGE_DIR>/_quarantine`, marked `QUARANTINED` and `BLOCKED`, and cannot enter OCR.
- `document_security_events` is append-only. A database trigger prevents a document from changing to CLEAN/INFECTED unless a matching V1_CLAMAV event already exists for its current hash.
- Historical CLEAN/EXEMPT flags are not accepted as proof. A legacy CLEAN file can be re-scanned; an EXEMPT file must be re-intaken under the new workflow.

### 2. Upload validation and pipeline gate

- PDF/JPEG/PNG/CSV extension is checked against the file signature/content.
- PNG/JPEG containers are parsed/verified with Pillow; CSV must be UTF-8 and contain no NUL bytes.
- Original filenames are reduced to safe basename display labels; storage keys remain server-generated.
- Stored files use mode `0600`; per-case and quarantine directories use mode `0700` where supported.
- `service.process_document` and the HTTP process endpoint require a current-hash ClamAV V1 CLEAN event. Before parser execution, DATA-AI uses a no-follow descriptor to copy the stored bytes into a private `0400` processing copy and verifies its digest; parsers consume only that copy.
- Images above 40 million pixels are rejected to reduce image decompression-bomb risk.

### 3. Production configuration and transport

Production/staging startup fails closed unless:

- Internal service token is a non-placeholder unique secret with at least 32 bytes.
- At least one active, non-placeholder signed-assertion key is configured.
- PostgreSQL URL uses `sslmode=verify-full`, an explicit database user and a unique password of at least 24 bytes, plus an absolute readable `sslrootcert` CA file.
- A private `CLAMAV_HOST` is configured.
- Storage and export volumes are separately mounted with a `PLATFORM_MANAGED_KMS` provider and non-placeholder key references.
- `REQUIRED_FLYWAY_VERSION` remains pinned to `17` for this release.
- Storage/export directories are accessible to the non-root user and have no group/world permissions.

The KMS environment variables are deployment contract/attestation fields only. DATA-AI does not perform application-level envelope encryption in this release. Operations must independently verify the actual storage class, volume encryption, KMS policy, key rotation and restore-time key access before production approval.

### 4. Container and API hardening

- API container runs as UID/GID 10001, read-only root filesystem, dropped Linux capabilities, `no-new-privileges`, bounded `/tmp` tmpfs, `pids_limit=128` and bounded open-file descriptors.
- PostgreSQL/API/pgAdmin published ports bind to `127.0.0.1` by default.
- Compose no longer supplies a default database password, internal token or pgAdmin password; explicit `.env` values are required.
- API response headers include `nosniff`, frame denial, no-referrer, restrictive permissions policy and `no-store`.
- Request `Content-Length` is checked against `MAX_REQUEST_BODY_MB`.
- `/health` is liveness only. `/ready` checks DB, exact Flyway version V17 and ClamAV availability; production prerequisites are separately checked.

### 5. Backup / restore and storage audit

- `scripts/backup_postgres.sh` creates a custom-format PostgreSQL backup over `PGSSLMODE=verify-full` with an explicit readable `PGSSLROOTCERT`, validates its archive catalog, writes SHA-256 and restricts file permissions. Destination must be a platform-KMS-encrypted volume.
- `scripts/restore_postgres.sh` requires `PGSSLMODE=verify-full`, a readable CA file, an explicit `RESTORE_CONFIRM=OVERWRITE_TARGET_DATABASE`, and a recovery database name different from `PRODUCTION_PGDATABASE`. It restores only to a pre-created isolated target.
- `scripts/storage_integrity_audit.py` compares every active document storage object against the DB SHA-256 ledger and reports missing, mismatched or unsafe paths without printing file content.
- Database backup and file-volume snapshot must be coordinated to the same recovery point. The scripts do not create snapshots of Docker volumes or prove KMS encryption.

## Required deployment variables

See `.env.example`. Production/staging must set:

- `APP_ENV=production` (or `staging`)
- `INTERNAL_SERVICE_TOKEN`
- `SERVICE_ASSERTION_KEYS`
- `DATABASE_URL` including `sslmode=verify-full` and `sslrootcert=/absolute/path/to/postgres-ca.pem` readable by UID 10001
- `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_TIMEOUT_SECONDS`
- `STORAGE_ENCRYPTION_PROVIDER=PLATFORM_MANAGED_KMS`
- `STORAGE_ENCRYPTION_KEY_REFERENCE`
- `EXPORT_ENCRYPTION_PROVIDER=PLATFORM_MANAGED_KMS`
- `EXPORT_ENCRYPTION_KEY_REFERENCE`

The ClamAV TCP endpoint must be private and network-restricted. This adapter does not add TLS to clamd's native TCP protocol; use a protected private network or an approved local socket/proxy deployment.

## Checks performed in this development environment

- Full pytest suite: **213 passed** in the final working-tree run.
- Python bytecode compilation, shell syntax checks, OpenAPI artifact parity, PostgreSQL dialect DDL compilation, Compose YAML parsing, and archive integrity checks.
- ClamAV protocol tests using a deterministic fake daemon for CLEAN, INFECTED, and unknown/error replies. These verify protocol framing, not a real antivirus engine/database.
- Upload signature tests, legacy scan rejection, OCR gate, production configuration validation, OpenAPI parity, PostgreSQL dialect DDL compilation, Compose YAML parsing, shell syntax and source archive integrity.

## Not performed / external acceptance blockers

- No live PostgreSQL server, Docker/Podman daemon or Flyway CLI was available; Flyway V17 was not executed against a real database and the container image was not built/run.
- No live ClamAV server/signature database was available; real EICAR/infected-file verification remains staging work. The fake-daemon protocol tests validate framing/verdict parsing only.
- No KMS API integration or proof of platform volume encryption was performed. The key-reference settings do not perform encryption.
- No parser sandbox/worker isolation, ingress/reverse-proxy body limit, penetration test, concurrency/load test or coordinated database+storage DR drill was performed; these remain production acceptance requirements.
- No real Backend/SSO, Camunda 8, Business Engine, load, penetration, backup/restore or DR drill was performed.
- No claim of production approval is made by this source update.

## Suggested staging acceptance sequence

1. Provision isolated PostgreSQL with TLS certificate matching the configured DNS name and apply Flyway through V17.
2. Provision protected ClamAV service; test clean file, EICAR test file, daemon timeout and daemon outage. Confirm infected file is quarantined and OCR remains blocked.
3. Verify volume KMS encryption and that the configured workload identity can use the key after restart and restore.
4. Run `scripts/storage_integrity_audit.py` before and after restart, backup and recovery.
5. Back up to encrypted storage; restore into an isolated database and corresponding storage snapshot; compare document counts, manifest hashes, scan attestations and export hashes.
6. Run full Workflow(3) end-to-end with Backend/SSO, Camunda and Business Engine, including outbox retries, Evidence resubmit, incident Hold, Checker return, Named Authority, G3/G4 and Reopen.
7. Execute load, concurrency and penetration tests against the real topology; approve RPO/RTO with the Bank.
