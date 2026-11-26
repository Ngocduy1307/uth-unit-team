# ERD V9.4.2 – Audit and Override Governance

```mermaid
erDiagram
    cases ||--o{ case_audit_entries : "case audit sequence"
    cases ||--o{ case_analysis_versions : versions
    case_analysis_versions ||--o{ case_override_requests : "snapshot-bound proposal"
    cases ||--o{ case_override_requests : "case scope"
    case_override_requests ||--o{ case_override_events : "append-only decisions"
    case_analysis_versions ||--o{ case_governance_events : "freeze/checker events"
    case_analysis_versions ||--o{ case_audit_entries : "optional version ref"

    case_audit_entries {
        uuid id PK
        uuid case_id FK
        varchar bank_id
        bigint sequence_no
        varchar actor_id
        varchar actor_role
        varchar action_code
        varchar entity_type
        varchar entity_id
        uuid version_id FK
        uuid request_id
        varchar previous_entry_sha256
        varchar entry_sha256
        timestamptz created_at
    }
    case_override_requests {
        uuid id PK
        uuid case_id FK
        uuid version_id FK
        varchar bank_id
        varchar request_kind
        varchar exception_code
        varchar policy_reference
        varchar policy_version
        varchar requested_by
        jsonb requested_change
        jsonb impact_summary
        jsonb evidence_refs
        varchar version_sha256
        varchar proposal_sha256
        timestamptz created_at
    }
    case_override_events {
        uuid id PK
        uuid case_id FK
        uuid request_id FK
        varchar event_type
        varchar actor_id
        varchar actor_role
        varchar authority_grant_ref
        varchar authority_scope_ref
        timestamptz valid_until
        varchar proposal_sha256
        timestamptz created_at
    }
```

## Key constraints

- `case_audit_entries`: unique `(case_id, sequence_no)`, previous head must match the latest entry, bank code must match case, append-only.
- `case_override_requests`: same-case composite FK to V14 version; `requested_by` must equal `case_analysis_versions.created_by`; the request's version SHA must equal the stored version hash; unique `(case_id, version_id, proposal_sha256)`; same-case evidence reference trigger; append-only.
- `case_override_events`: same-case request FK; exactly one `REQUESTED`; at most one terminal decision; authority decision is only valid after Checker confirmation and Named Authority actor must differ from Maker and Checker; append-only.

The role/permission catalogue adds `NAMED_AUTHORITY`, `OVERRIDE_APPROVE`, `POLICY_EXCEPTION_APPROVE` and `CASE_GOVERNANCE_AUDIT_VIEW`. Backend/SSO still owns actual grant validation. DATA-AI approval is not applied to a policy engine or credit decision.
