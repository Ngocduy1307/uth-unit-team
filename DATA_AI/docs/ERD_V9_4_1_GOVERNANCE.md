# V9.4.1 Governance ERD

```mermaid
erDiagram
    CASES ||--o{ CASE_ANALYSIS_VERSIONS : has
    CASE_ANALYSIS_VERSIONS ||--o{ CASE_GOVERNANCE_EVENTS : records
    DOCUMENTS ||--o{ DOCUMENT_SECURITY_EVENTS : records_scan_history
    CASE_ANALYSIS_VERSIONS ||--o| CASE_ANALYSIS_VERSIONS : supersedes

    CASES {
        uuid id PK
        string bank_id
        uuid bank_organization_id
        uuid customer_id
    }
    DOCUMENTS {
        uuid id PK
        uuid case_id FK
        string sha256
        string malware_scan_status
    }
    DOCUMENT_SECURITY_EVENTS {
        uuid id PK
        uuid document_id FK
        string event_type
        string scan_status
        string engine_name
        string engine_version
        timestamp occurred_at
        string recorded_by
    }
    CASE_ANALYSIS_VERSIONS {
        uuid id PK
        uuid case_id FK
        int version_no
        uuid based_on_version_id FK
        string snapshot_schema_version
        string snapshot_sha256
        jsonb snapshot_data
        jsonb readiness
        string created_by
        string created_by_role
        timestamp created_at
    }
    CASE_GOVERNANCE_EVENTS {
        uuid id PK
        uuid case_id FK
        uuid version_id FK
        string event_type
        string actor_id
        string actor_role
        text reason
        jsonb details
        timestamp created_at
    }
```

- `case_analysis_versions` is immutable. `based_on_version_id` and `case_id` use a same-case composite foreign key.
- `case_governance_events` is append-only and same-case linked to the version.
- The frozen snapshot includes sanitized `document_security_events`; the V14 freeze guard blocks later security-event inserts until Checker returns the case to Maker. Moving an `extracted_fields.document_id` to a different document is prohibited so a field cannot be moved out of a frozen case.
- Partial unique indexes allow one freeze, one Checker decision and one supersede event per version.
- Checker actor ID must differ from the version Maker. This data layer is not a Camunda task database or credit approval engine.
