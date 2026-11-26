# DATA-AI V10.0 — V18 ERD Additions

The following is the additive DATA-AI V18 data domain. Existing entities from V1–V17 are unchanged.

```mermaid
erDiagram
    CASES ||--o{ CASE_SCOPE_CONSENT_ATTESTATIONS : receives
    CASES ||--o{ CASE_INPUT_DECLARATION_REVISIONS : contains
    CASE_INPUT_DECLARATION_REVISIONS ||--o{ CASE_INPUT_DECLARATION_EVIDENCE_LINKS : cites
    DOCUMENTS ||--o{ CASE_INPUT_DECLARATION_EVIDENCE_LINKS : supports
    CASES ||--o{ CASE_INPUT_REVIEW_DECISIONS : reviews
    CASE_INPUT_DECLARATION_REVISIONS ||--o{ CASE_INPUT_REVIEW_DECISIONS : reviewed_by_maker
    CASES ||--o{ CASE_FINANCIAL_INPUT_BUNDLES : packages
    CASE_FINANCIAL_INPUT_BUNDLES ||--o{ CASE_PROPOSED_SCHEDULE_REFERENCES : schedule_for
    CASE_FINANCIAL_INPUT_BUNDLES ||--o{ CASE_BUSINESS_ENGINE_RECEIPTS : calculated_from
    CASE_PROPOSED_SCHEDULE_REFERENCES ||--o{ CASE_BUSINESS_ENGINE_RECEIPTS : exact_schedule
    CASES ||--o{ CASE_BUSINESS_ENGINE_RECEIPTS : receives

    CASES {
      uuid id PK
      uuid customer_id
      string bank_id
      date analysis_date
    }
    CASE_SCOPE_CONSENT_ATTESTATIONS {
      uuid id PK
      uuid case_id FK
      string bank_id
      string scope_code
      string scope_status
      string consent_status
      string backend_decision_reference
      string attestation_sha256
      timestamptz attested_at
    }
    CASE_INPUT_DECLARATION_REVISIONS {
      uuid id PK
      uuid case_id FK
      uuid customer_id FK
      string section_code
      int revision_no
      jsonb payload
      string payload_sha256
      uuid client_request_id
      uuid supersedes_revision_id FK
    }
    CASE_INPUT_DECLARATION_EVIDENCE_LINKS {
      uuid id PK
      uuid case_id FK
      uuid declaration_revision_id FK
      uuid document_id FK
      string document_sha256
    }
    CASE_INPUT_REVIEW_DECISIONS {
      uuid id PK
      uuid case_id FK
      uuid declaration_revision_id FK
      string target_type
      uuid target_id
      string decision_code
      jsonb evidence_refs
      string reviewed_by
      string reviewer_role
    }
    CASE_FINANCIAL_INPUT_BUNDLES {
      uuid id PK
      uuid case_id FK
      int bundle_no
      string readiness_status
      jsonb readiness
      jsonb bundle_data
      string bundle_sha256
    }
    CASE_PROPOSED_SCHEDULE_REFERENCES {
      uuid id PK
      uuid case_id FK
      uuid bundle_id FK
      string schedule_reference
      string schedule_sha256
      string product_code
      string product_version
      int term_months
    }
    CASE_BUSINESS_ENGINE_RECEIPTS {
      uuid id PK
      uuid case_id FK
      uuid bundle_id FK
      uuid schedule_reference_id FK
      string input_bundle_sha256
      string calculation_reference
      string policy_reference
      string product_version
      string product_sha256
      string policy_sha256
      string result_status
      jsonb scenario_references
      string output_sha256
    }
```

## Database invariants

- All seven V18 entities are append-only in PostgreSQL: UPDATE/DELETE is rejected by trigger.
- Same-case composite foreign keys protect declaration/evidence and bundle/schedule/receipt relationships.
- Scope attestation bank ID must match the Case bank ID.
- Declaration revisions are sequential by `(case_id, section_code, revision_no)`; client request IDs are unique per case when present.
- `CaseInputReviewDecision.reviewer_role` is `MAKER`; the service checks the signed actor and exact target row/source document.
- A completed Business Engine receipt must reference a schedule row, the same case/bundle/product/version and exactly BASELINE/STRESS_1/STRESS_2 scenario keys.
- All input/output/product/policy/schedule hashes are 64-character lowercase SHA-256 digests.
- V14 Freeze snapshots include the seven V18 tables; a post-receipt change requires a governed successor version before export.

V18 migration path: `db/migration/V18__data_ai_workflow_input_handoff.sql`.
