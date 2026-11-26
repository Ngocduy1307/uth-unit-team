# DATA-AI V9.5.2 Release Notes

## Summary

Production security hardening aligned to `Workflow(3).drawio`, primarily the intake/file-safety, quarantine, OCR gate, workflow integrity and recovery controls.

## Change highlights

1. Added ClamAV native INSTREAM adapter using a no-follow file descriptor; the scanner hashes the exact stream bytes and only explicit `stream: OK` becomes CLEAN and explicit FOUND becomes INFECTED.
2. Added `POST /api/v1/cases/{case_id}/documents/{document_id}/security-scan`, restricted to a dedicated DOCUMENT_SCANNER signed identity and bank scope.
3. Added exact streamed SHA-256 and attestation version to document security events; scan response digest, database document digest and post-scan storage digest must all agree. V17 adds append-only protection and DB-side guards on document scan status.
4. OCR cannot run without V1_CLAMAV CLEAN attestation for the exact current document hash; the parser reads only a private read-only processing copy that is independently rehashed from a no-follow source descriptor.
5. Uploads are checked for real PDF/JPEG/PNG/CSV signatures; images are parsed and capped at 40 million pixels, and CSV is UTF-8/NUL checked.
6. INFECTED documents are isolated under `_quarantine` and blocked.
7. Production/staging preflight rejects placeholder assertion/token/database secrets, requires PostgreSQL `sslmode=verify-full` plus an absolute readable `sslrootcert`, ClamAV, Flyway V17 and non-placeholder platform KMS references for separate storage/export volumes.
8. API container runs non-root, read-only, no added capabilities, no-new-privileges and localhost-published ports by default.
9. Added backup/restore helpers, storage integrity audit, readiness checks and security headers.
10. Replaced checked-in Workflow diagram with exact `Workflow(3).drawio` supplied for this release and regenerated OpenAPI.

## Compatibility and operational notes

- Historical CLEAN scan flags are not trusted until a new ClamAV V1 scan is recorded. They may be rescanned in place if the bytes remain available and unchanged.
- Legacy EXEMPT is retained only as historical state and cannot pass readiness or be written by new/updated rows under V17.
- Scanner outage or unrecognized verdict leaves the file untrusted and returns a service-unavailable response.
- ClamAV must be on a private network; the clamd native TCP protocol is not encrypted by this adapter.
- Platform KMS environment fields are deployment assertions/references. The application does not encrypt file bytes itself.

## Verification record

- Final source suite: **213 passed**.
- The ClamAV protocol tests use a deterministic fake daemon; they do not prove a real ClamAV engine/signature database is deployed.
- Docker Compose YAML parses and container hardening assertions pass; Docker image build/runtime was not run because Docker is not available in the test environment.
- OpenAPI artifact is generated from the current FastAPI runtime; PostgreSQL DDL is compiled with the PostgreSQL dialect but PL/pgSQL is not executed.

## Acceptance status

Source-level verification is not equivalent to production acceptance. Live PostgreSQL/Flyway, ClamAV, KMS, Docker, load, penetration and DR tests remain staging requirements.
