ALTER TABLE evidence_records
    ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_latest BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS updated_by VARCHAR(64),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_dossier_latest ON evidence_records(dossier_id, is_latest);

CREATE TABLE IF NOT EXISTS evidence_ocr_results (
    id VARCHAR(36) PRIMARY KEY,
    evidence_id VARCHAR(36) NOT NULL REFERENCES evidence_records(id) ON DELETE CASCADE,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    ocr_version INT NOT NULL DEFAULT 1,
    engine_name VARCHAR(64) NOT NULL,
    engine_version VARCHAR(32),
    confidence_score NUMERIC(5, 2),
    raw_payload JSONB NOT NULL,
    extracted_summary JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED',
    error_message TEXT,
    processed_by VARCHAR(64) NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_evidence_ocr_version UNIQUE (evidence_id, ocr_version)
);

CREATE INDEX IF NOT EXISTS idx_ocr_results_evidence_id ON evidence_ocr_results(evidence_id);
CREATE INDEX IF NOT EXISTS idx_ocr_results_dossier_id ON evidence_ocr_results(dossier_id);
CREATE INDEX IF NOT EXISTS idx_ocr_results_status ON evidence_ocr_results(status);
