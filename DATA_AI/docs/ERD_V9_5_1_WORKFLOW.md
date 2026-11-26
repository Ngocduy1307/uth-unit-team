# ERD – DATA-AI V9.5.1 Workflow Integration

```mermaid
erDiagram
    CASES ||--o{ CASE_WORKFLOW_BINDINGS : correlates
    CASE_WORKFLOW_BINDINGS ||--o{ WORKFLOW_OUTBOX_EVENTS : emits
    CASE_WORKFLOW_BINDINGS ||--o{ WORKFLOW_INBOX_EVENTS : receives
    CASES ||--o{ CASE_EVIDENCE_REQUESTS : requests
    CASE_EVIDENCE_REQUESTS ||--o{ CASE_RESUBMISSIONS : receives
    CASES ||--o{ CASE_WORKFLOW_REOPENS : reopens
    CASE_ANALYSIS_VERSIONS ||--o{ CASE_WORKFLOW_REOPENS : based_on
    CASES ||--o{ CASE_WORKFLOW_RELEASE_GATES : records
    CASE_ANALYSIS_VERSIONS ||--o{ CASE_WORKFLOW_RELEASE_GATES : references
    CASES ||--o{ CASE_WORKFLOW_EXPORT_PACKAGES : exports
    CASE_ANALYSIS_VERSIONS ||--o{ CASE_WORKFLOW_EXPORT_PACKAGES : snapshots
    CASE_OVERRIDE_REQUESTS ||--o| CASE_OVERRIDE_APPLICATION_RECEIPTS : applied_by

    CASES {
      uuid id PK
      string bank_id
    }
    CASE_WORKFLOW_BINDINGS {
      uuid id PK
      uuid case_id FK
      string process_instance_id UK
      string business_key
      string status
    }
    WORKFLOW_OUTBOX_EVENTS {
      uuid id PK
      uuid case_id FK
      uuid binding_id FK
      string idempotency_key
      string payload_sha256
      string status
      int attempts
    }
    WORKFLOW_INBOX_EVENTS {
      uuid id PK
      uuid case_id FK
      uuid binding_id FK
      string external_event_id UK
      bigint process_sequence
      string payload_sha256
    }
    CASE_EVIDENCE_REQUESTS {
      uuid id PK
      uuid case_id FK
      int request_no
      string status
      datetime due_at
    }
    CASE_RESUBMISSIONS {
      uuid id PK
      uuid case_id FK
      uuid evidence_request_id FK
      json impact_list
      string impact_sha256
    }
    CASE_WORKFLOW_REOPENS {
      uuid id PK
      uuid case_id FK
      uuid based_on_version_id FK
      uuid new_version_id FK
      string status
    }
    CASE_WORKFLOW_RELEASE_GATES {
      uuid id PK
      uuid case_id FK
      uuid version_id FK
      string gate_code
      string gate_reference
    }
    CASE_WORKFLOW_EXPORT_PACKAGES {
      uuid id PK
      uuid case_id FK
      uuid version_id FK
      string package_sha256
      string snapshot_sha256
    }
    CASE_OVERRIDE_REQUESTS {
      uuid id PK
      uuid version_id FK
      string proposal_sha256
    }
    CASE_OVERRIDE_APPLICATION_RECEIPTS {
      uuid id PK
      uuid case_id FK
      uuid request_id FK
      string applied_proposal_sha256
      string applied_version_sha256
      string policy_version
    }
    CASE_ANALYSIS_VERSIONS {
      uuid id PK
      uuid case_id FK
      int version_no
      string snapshot_sha256
    }
```

V16 adds nine workflow tables. The diagram describes logical relationships; verify deployed PostgreSQL constraints/indexes using Flyway metadata and catalog queries after applying V16. External Camunda, SSO, Business Engine and object-store entities are intentionally not represented as local DATA-AI tables.
