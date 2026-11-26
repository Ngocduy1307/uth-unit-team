# ERD Additions — V9.5.2

V9.5.2 adds two columns to the existing `document_security_events` entity and database triggers. No new business case tables are introduced. The scanner response also returns the SHA-256 computed over the exact byte stream sent to ClamAV; that digest is compared to the current document row before a trusted verdict is written.

```mermaid
erDiagram
    CASES ||--o{ DOCUMENTS : contains
    DOCUMENTS ||--o{ DOCUMENT_SECURITY_EVENTS : has_scan_history

    DOCUMENTS {
      uuid id PK
      uuid case_id FK
      varchar sha256
      varchar mime_type
      varchar detected_mime_type
      varchar malware_scan_status
      varchar evidence_status
      varchar processing_status
      text stored_path
    }

    DOCUMENT_SECURITY_EVENTS {
      uuid id PK
      uuid document_id FK
      varchar event_type
      varchar scan_status
      varchar engine_name
      varchar engine_version
      varchar scanned_sha256
      varchar attestation_version
      jsonb details
      timestamptz occurred_at
      varchar recorded_by
    }
```

## V17 database invariants

1. `attestation_version=V1_CLAMAV` requires `event_type` and verdict to match, engine `ClamAV`, non-empty engine version and a lowercase SHA-256.
2. The event's `scanned_sha256` must equal the current `documents.sha256` at insert time.
3. A document can change to `CLEAN`/`INFECTED` only after a matching V1_CLAMAV event exists for the same document and hash.
4. A completed scan verdict cannot be reset or changed in place; upload a new immutable document instead.
5. `document_security_events` is append-only.
6. `EXEMPT` remains readable as historical data but new/updated rows cannot use it; legacy rows are not accepted as technical Checker evidence.

The application stores only a reference to platform KMS-managed volume encryption. Actual encryption-at-rest is infrastructure-owned and is not represented as an app-level cryptographic column.
