# DATA-AI V9.5.2 Handoff

## Release

**DATA-AI V9.5.2 — Production Security & Recovery Hardening**

Baseline: V9.5.1 source archive supplied in this conversation. Workflow baseline: `Workflow(3).drawio` supplied in this conversation.

## Delivered

- ClamAV INSTREAM client and `DOCUMENT_SCANNER`-only scan route.
- Exact streamed-byte SHA-256 from the no-follow ClamAV input descriptor, scanner engine/version, V1_CLAMAV attestation and post-scan storage rehash comparison.
- OCR reads only a private read-only processing copy created from a no-follow file descriptor and rehashed against the scanned digest; storage path tampering blocks processing and emits an integrity incident.
- Image decompression-bomb guard (maximum 40 million pixels).
- Append-only document security events and DB-side scan-state guard in Flyway V17.
- Fail-closed OCR/process gate and stricter Maker readiness / resubmission checks.
- File signature/MIME validation and safe server-side filename normalization.
- Private file/directory permissions and infected-file quarantine.
- Production/staging config gate: non-placeholder 32-byte internal token, non-placeholder assertion key, PostgreSQL verify-full plus absolute readable CA file and 24-byte DB password, private scanner host, separate non-placeholder KMS-attested storage/export volumes and Flyway V17 pin.
- Non-root/read-only/capability-dropped API container; bounded PIDs/file descriptors; ports local-only by default; explicit secrets; readiness probes and security headers.
- PostgreSQL backup/restore helpers require verify-full + trusted CA, include SHA-256 checks, and refuse restoring over the declared production database; storage hash audit script included.
- Updated Workflow(3) diagram, OpenAPI contract, ERD and workflow traceability.

## Verification

Baseline V9.5.1: 191 tests passed before changes.
V9.5.2 current source test suite: **213 passed**. Tests cover ClamAV protocol framing with a deterministic fake daemon, exact streamed-byte hashing, MIME/signature and image-pixel validation, symlink rejection, verified OCR processing copies, production preflight, V17 migration contract and OCR gate. Python compile, shell syntax, runtime OpenAPI parity (57 paths), PostgreSQL dialect DDL compilation, Compose YAML parsing, workflow XML equality and archive integrity are separately checked.

The test environment did not have live PostgreSQL, Docker, KMS or ClamAV, so no live integration or production acceptance is claimed.

## Deployment stop conditions

Do not deploy to production until all external blockers in `V9_5_2_PRODUCTION_HARDENING.md` are completed. In particular, confirm real KMS encryption, actual ClamAV scanning, PostgreSQL TLS and Flyway V17, and a successful backup/restore from the paired database and storage snapshots.
