# ERD V9.3.2 – Evidence provenance and reconciliation

```mermaid
erDiagram
    CASES ||--o{ DOCUMENTS : receives
    CASES ||--o{ EVIDENCE_MANIFEST_ENTRIES : chains
    DOCUMENTS ||--o| EVIDENCE_MANIFEST_ENTRIES : manifested_as
    DOCUMENTS ||--o{ EXTRACTED_FIELDS : extracts
    DOCUMENTS ||--o{ TRANSACTIONS : imports
    CASES ||--o{ TRANSACTIONS : contains
    CASES ||--o{ TRANSACTION_DUPLICATE_CANDIDATES : detects
    TRANSACTIONS ||--o{ TRANSACTION_DUPLICATE_CANDIDATES : left_or_right
    CASES ||--o{ EVIDENCE_RECONCILIATION_RUNS : compares
    DOCUMENTS ||--o{ EVIDENCE_RECONCILIATION_RUNS : pdf_or_csv_source
    CASES ||--o{ EVIDENCE_REVIEW_DECISIONS : records
    EVIDENCE_RECONCILIATION_RUNS ||--o{ EVIDENCE_REVIEW_DECISIONS : reviewed
    TRANSACTION_DUPLICATE_CANDIDATES ||--o{ EVIDENCE_REVIEW_DECISIONS : reviewed
```

## Design rules

- A manifest row is created once per document and chained by case sequence. SHA-256 protects byte-integrity checks; it does not prove origin/authenticity.
- Manifest, duplicate candidate, reconciliation snapshot and review records are append-only at the PostgreSQL trigger boundary.
- Composite foreign keys require referenced documents/transactions to belong to the same case as the record.
- A duplicate candidate links two rows but does not suppress either row.
- A reconciliation run captures both source hashes, selected statement period, totals, tolerance and arithmetic outcome at execution time.
- Review decisions are immutable events with a Maker/admin actor and reason. The latest decision is a display projection; prior decisions remain queryable.
- Backend/Camunda remains the owner for task state, task assignment, Maker ≠ Checker, workflow timers, policy and credit outcomes.
