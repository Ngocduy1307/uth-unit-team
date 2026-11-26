# Workflow(3) ↔ DATA-AI API Traceability — V9.5.2

Workflow source file: `docs/Workflow.drawio` (copied byte-for-byte from the user's `Workflow(3).drawio`).

| Workflow node / label | DATA-AI API / component | V9.5.2 result | External owner / note |
|---|---|---|---|
| `n-intake` — Tiếp nhận hồ sơ & chứng từ; Manifest & Hash | `POST /api/v1/cases`, `POST /api/v1/cases/{id}/documents`, `app/service.py`, V13 manifest | Existing manifest/hash preserved; uploaded MIME is derived from bytes; safe file permissions. | Backend owns applicant/case identity and form intake. |
| `n-scope` — Consent & scope DMN | Signed assertion + bank scoping | No implicit consent is inferred. | Bank DMN/Backend must provide valid consent reference/status and purpose. |
| `n-safe` — Hash, format, limits | `validate_upload_content`, `ClamAV` adapter | PDF/JPEG/PNG/CSV signature validation; ClamAV streams through a no-follow descriptor and hashes the exact sent bytes; pre-/post-scan storage hashes must also match. | ClamAV is a separate private infrastructure dependency. |
| `gw-file` — Accepted / Quarantined / Rejected | `POST /api/v1/cases/{case_id}/documents/{document_id}/security-scan` | CLEAN requires exact V1_CLAMAV attestation; INFECTED moves to private quarantine and sets BLOCKED; outage/unknown verdict remains untrusted. | Camunda service task calls scanner route; no real Camunda process is started by DATA-AI. |
| `n-maker-verify` — Ownership, period, PDF–CSV totals, employment | Existing evidence reconciliation and Maker review APIs | Source evidence can be cross-linked; DATA-AI does not assert bank-account ownership or employment. | Maker and authoritative Bank systems own those checks. |
| `n-extract` — OCR / Abstain | `/api/v1/cases/{case_id}/documents/{document_id}/process`, `app/service.py` | OCR blocked until a V1_CLAMAV CLEAN event matches the current file hash; extraction abstention remains. | Camunda routes OCR outage to manual task. |
| `n-manual-extract` — Maker review/manual entry | Existing OCR governance and evidence review | Existing review/abstain foundation retained. | User Task creation/assignment is in Camunda/Backend. |
| `n-inc`, `n-exp`, `n-debt` — I/E/D | Existing transaction ledger, extraction and quality findings | Evidence candidates and provenance retained; no final affordability decision is asserted. | Authoritative I/E/D aggregation requires the approved Business Engine and Bank data. |
| `n-maker-reconcile` — I-E-D, duplicate review | V9.3.2 evidence reconciliation and review APIs | Existing duplicate/reconciliation review retained; readiness requires terminal review. | Maker makes the source-data decision. |
| `n-schedule` — Proposed Schedule P | Product/version references in workflow contracts | DATA-AI stores reference/version context. | Bank/Business Engine validates proposed schedule totals and product rules. |
| `gw-complete`, `n-short-hist`, `n-provisional`, `n-awaiting` | Evidence request/resubmission APIs V9.5.1 | Awaiting Evidence, Impact List and successor-version lifecycle retained. | Camunda owns DMN routing and User Tasks. Insufficient history threshold remains Bank policy. |
| `gw-timer`, `n-exp-wait` — Timer / Expired | Workflow Inbox/Outbox | Expiry callback can be recorded idempotently. | Actual timer/DMN execution belongs to Camunda. |
| `n-resubmit` — New version & Impact List | `POST /api/v1/cases/{case_id}/workflow/evidence-requests/{request_id}/resubmit` | Each resubmitted file must pass manifest/hash and V1_CLAMAV CLEAN attestation before impact review. | Maker reviews Impact List and freezes successor version. |
| `n-calc`, `n-calc-hold`, `n-stress`, `n-policy`, `n-explain` | Workflow integration and incident references | DATA-AI records safe references/callbacks. | Residual/DSR, stress, policy DMN and narrative remain external Business Engine responsibilities. |
| `n-maker-review`, `n-freeze`, `n-checker` | V9.4.1 governance APIs | Immutable freeze and independent Checker controls retained; scan readiness is stricter. | Backend/SSO owns identity and task assignment. |
| Override / Named Authority | V9.4.2 override, authority and Business Engine receipt APIs | Proposal, authority review and application receipts remain independently hash-bound. | Bank Named Authority and Business Engine perform actual approval/application. |
| `n-export` — JSON/CSV/PDF with hashes | `POST /api/v1/cases/{case_id}/workflow/export-packages` | Existing hashed package retained; only Checker-confirmed technical versions can export. | Does not constitute a credit decision. |
| `gw-mode`, `n-shadow`, `n-oper` — G3/G4 | Workflow release-gate API | Stores external gate references; G4 requires required Business Engine receipt where override applied. | Bank release authority controls operational enablement. |
| `gw-post`, `n-post-exp`, `n-reopen-pol`, `n-reopen-ev` | Workflow expiry/reopen API | Existing post-event expiry and controlled reopen references retained. | Camunda/Bank policy events trigger these actions; DATA-AI creates no autonomous policy decision. |

## V9.5.2 cross-cutting controls

- Tenant scope is revalidated after the Case row lock for scanner operations.
- Production preflight rejects placeholder service/database/signing secrets, requires PostgreSQL verify-full with an absolute readable CA certificate, ClamAV and non-placeholder KMS references, and pins `REQUIRED_FLYWAY_VERSION=17`.
- Uploaded images are limited to 40 million pixels to reduce decompression-bomb risk. API container additionally limits PIDs and file descriptors.
- Storage integrity failures block processing and emit a workflow incident event; no path is silently marked CLEAN.

- Production/staging startup checks non-placeholder signed assertion/internal/database secrets, PostgreSQL `sslmode=verify-full` plus absolute readable CA file, ClamAV host, non-placeholder KMS volume key references and Flyway V17 pin.
- `/health` is liveness; `/ready` checks PostgreSQL, Flyway V17 and ClamAV availability.
- API container runs non-root with a read-only root filesystem, dropped Linux capabilities and no-new-privileges.
- Backup/restore scripts require explicit destination/restore confirmation; storage hash audit detects missing or modified evidence objects.

## Remaining workflow gaps (not claimed complete)

- Real Bank consent/Scope DMN and consent evidence validation.
- Real Camunda BPMN deployment, service/user task assignment, timer execution and incident lifecycle.
- Account ownership, current employment and authoritative statement matching.
- Approved Business Engine calculations for I/E/D, proposed schedule, residual, DSR/Q and stress scenarios.
- Policy DMN thresholds and authoritative narrative.
- Actual Backend/SSO, KMS, ClamAV, PostgreSQL, Bank release gate and production topology integration.
- Load, penetration, data-protection, backup/restore and DR acceptance.
