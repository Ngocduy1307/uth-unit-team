CREATE TABLE IF NOT EXISTS dossiers (
    id VARCHAR(36) PRIMARY KEY,
    application_id VARCHAR(64) NOT NULL UNIQUE,
    applicant_id VARCHAR(64) NOT NULL,
    applicant_name VARCHAR(255) NOT NULL,
    bank_code VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    maker_id VARCHAR(64),
    checker_id VARCHAR(64),
    analysis_date DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dossiers_applicant_id ON dossiers(applicant_id);
CREATE INDEX IF NOT EXISTS idx_dossiers_status ON dossiers(status);

CREATE TABLE IF NOT EXISTS evidence_records (
    id VARCHAR(36) PRIMARY KEY,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    storage_path VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'RECEIVED',
    uploaded_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_dossier_id ON evidence_records(dossier_id);
CREATE INDEX IF NOT EXISTS idx_evidence_file_hash ON evidence_records(file_hash);

CREATE TABLE IF NOT EXISTS outbox_events (
    id VARCHAR(36) PRIMARY KEY,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_outbox_status_created_at ON outbox_events(status, created_at);
