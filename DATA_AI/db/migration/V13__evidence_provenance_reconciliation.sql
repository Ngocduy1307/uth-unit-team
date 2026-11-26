-- V13: immutable evidence manifest, PDF/CSV reconciliation snapshots and Maker review records.
-- DATA-AI creates candidates only. Bank/Camunda remains authoritative for task completion,
-- ownership verification, income eligibility, policy and credit decisions.
SET search_path TO data_ai;

ALTER TABLE documents ADD CONSTRAINT uq_documents_id_case UNIQUE (id, case_id);
ALTER TABLE transactions ADD CONSTRAINT uq_transactions_id_case UNIQUE (id, case_id);

CREATE TABLE evidence_manifest_entries (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    document_id UUID NOT NULL,
    sequence_no INTEGER NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size INTEGER NOT NULL,
    previous_entry_hash VARCHAR(64) NULL,
    entry_hash VARCHAR(64) NOT NULL UNIQUE,
    hash_version VARCHAR(8) NOT NULL DEFAULT '1',
    received_by VARCHAR(160) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_manifest_sequence_positive CHECK (sequence_no > 0),
    CONSTRAINT ck_evidence_manifest_file_size_positive CHECK (file_size > 0),
    CONSTRAINT ck_evidence_manifest_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_evidence_manifest_previous_hash CHECK (previous_entry_hash IS NULL OR previous_entry_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_evidence_manifest_entry_hash CHECK (entry_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_evidence_manifest_case_sequence UNIQUE(case_id, sequence_no),
    CONSTRAINT uq_evidence_manifest_document UNIQUE(document_id),
    CONSTRAINT fk_manifest_document_case FOREIGN KEY(document_id, case_id)
        REFERENCES documents(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_evidence_manifest_case_received ON evidence_manifest_entries(case_id, received_at);

CREATE TABLE transaction_duplicate_candidates (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    left_transaction_id UUID NOT NULL,
    right_transaction_id UUID NOT NULL,
    fingerprint_sha256 VARCHAR(64) NOT NULL,
    candidate_key VARCHAR(64) NOT NULL UNIQUE,
    match_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_status VARCHAR(24) NOT NULL DEFAULT 'PENDING_REVIEW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_duplicate_candidate_ordered_pair CHECK (left_transaction_id < right_transaction_id),
    CONSTRAINT ck_duplicate_candidate_fingerprint CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_duplicate_candidate_key CHECK (candidate_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_duplicate_candidate_review_status CHECK (review_status IN ('PENDING_REVIEW','REVIEWED')),
    CONSTRAINT uq_duplicate_candidate_pair UNIQUE(left_transaction_id, right_transaction_id),
    CONSTRAINT uq_duplicate_candidate_id_case UNIQUE(id, case_id),
    CONSTRAINT fk_duplicate_candidate_left_case FOREIGN KEY(left_transaction_id, case_id)
        REFERENCES transactions(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_duplicate_candidate_right_case FOREIGN KEY(right_transaction_id, case_id)
        REFERENCES transactions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_duplicate_candidate_case ON transaction_duplicate_candidates(case_id, created_at);
CREATE INDEX ix_duplicate_candidate_fingerprint ON transaction_duplicate_candidates(fingerprint_sha256);

CREATE TABLE evidence_reconciliation_runs (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    pdf_document_id UUID NOT NULL,
    csv_document_id UUID NOT NULL,
    pdf_sha256 VARCHAR(64) NOT NULL,
    csv_sha256 VARCHAR(64) NOT NULL,
    reconciliation_version VARCHAR(40) NOT NULL,
    result_status VARCHAR(32) NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_reconciliation_distinct_documents CHECK (pdf_document_id <> csv_document_id),
    CONSTRAINT ck_reconciliation_result_status CHECK (result_status IN (
        'INCOMPLETE','ABSTAINED','BALANCE_MATCH_CANDIDATE','BALANCE_VARIANCE_CANDIDATE')),
    CONSTRAINT ck_reconciliation_pdf_sha256 CHECK (pdf_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_reconciliation_csv_sha256 CHECK (csv_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT fk_reconciliation_pdf_case FOREIGN KEY(pdf_document_id, case_id)
        REFERENCES documents(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_reconciliation_csv_case FOREIGN KEY(csv_document_id, case_id)
        REFERENCES documents(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT uq_reconciliation_run_id_case UNIQUE(id, case_id)
);
CREATE INDEX ix_reconciliation_case_created ON evidence_reconciliation_runs(case_id, created_at);

CREATE TABLE evidence_review_decisions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    target_type VARCHAR(32) NOT NULL,
    target_id UUID NOT NULL,
    reconciliation_run_id UUID NULL,
    duplicate_candidate_id UUID NULL,
    decision_code VARCHAR(40) NOT NULL,
    reason TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    reviewed_by VARCHAR(160) NOT NULL,
    reviewer_role VARCHAR(40) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_review_target_type CHECK (target_type IN ('RECONCILIATION_RUN','TRANSACTION_DUPLICATE')),
    CONSTRAINT ck_evidence_review_reason CHECK (length(trim(reason)) >= 8),
    CONSTRAINT ck_evidence_review_target_link CHECK (
        (target_type = 'RECONCILIATION_RUN' AND reconciliation_run_id IS NOT NULL
            AND duplicate_candidate_id IS NULL AND target_id = reconciliation_run_id)
        OR
        (target_type = 'TRANSACTION_DUPLICATE' AND duplicate_candidate_id IS NOT NULL
            AND reconciliation_run_id IS NULL AND target_id = duplicate_candidate_id)
    ),
    CONSTRAINT ck_evidence_review_decision_code CHECK (
        (target_type = 'RECONCILIATION_RUN' AND decision_code IN
            ('CONFIRMED_MATCH','CONFIRMED_VARIANCE','REJECTED','NEEDS_MORE_EVIDENCE'))
        OR
        (target_type = 'TRANSACTION_DUPLICATE' AND decision_code IN
            ('CONFIRMED_DUPLICATE','NOT_DUPLICATE','NEEDS_MORE_EVIDENCE'))
    ),
    CONSTRAINT fk_evidence_review_reconciliation_case
        FOREIGN KEY(reconciliation_run_id, case_id)
        REFERENCES evidence_reconciliation_runs(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_evidence_review_duplicate_case
        FOREIGN KEY(duplicate_candidate_id, case_id)
        REFERENCES transaction_duplicate_candidates(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_evidence_review_target_created ON evidence_review_decisions(target_type, target_id, created_at);
CREATE INDEX ix_evidence_review_case_created ON evidence_review_decisions(case_id, created_at);

-- Preserve ledger semantics at the database boundary. Retention/purge must be a governed
-- procedure (not an application UPDATE/DELETE) and should be recorded outside these ledgers.
CREATE OR REPLACE FUNCTION reject_evidence_ledger_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only evidence ledger table % does not allow %', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_evidence_manifest_append_only
    BEFORE UPDATE OR DELETE ON evidence_manifest_entries
    FOR EACH ROW EXECUTE FUNCTION reject_evidence_ledger_mutation();
CREATE TRIGGER trg_duplicate_candidate_append_only
    BEFORE UPDATE OR DELETE ON transaction_duplicate_candidates
    FOR EACH ROW EXECUTE FUNCTION reject_evidence_ledger_mutation();
CREATE TRIGGER trg_reconciliation_run_append_only
    BEFORE UPDATE OR DELETE ON evidence_reconciliation_runs
    FOR EACH ROW EXECUTE FUNCTION reject_evidence_ledger_mutation();
CREATE TRIGGER trg_evidence_review_append_only
    BEFORE UPDATE OR DELETE ON evidence_review_decisions
    FOR EACH ROW EXECUTE FUNCTION reject_evidence_ledger_mutation();

COMMENT ON TABLE evidence_manifest_entries IS
    'Append-only per-case SHA-256 hash chain recording receipt metadata. Does not establish document authenticity.';
COMMENT ON TABLE evidence_reconciliation_runs IS
    'Immutable arithmetic comparison snapshot between selected PDF statement fields and CSV rows; Maker review required.';
COMMENT ON TABLE transaction_duplicate_candidates IS
    'Immutable exact-match candidate pairs. Review history is stored in evidence_review_decisions.';
COMMENT ON TABLE evidence_review_decisions IS
    'Append-only DATA-AI record of Maker review input. Camunda task ownership/completion and bank authorization remain external.';
