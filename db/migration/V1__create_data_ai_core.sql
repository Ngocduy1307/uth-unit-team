CREATE SCHEMA IF NOT EXISTS data_ai;
SET search_path TO data_ai;

CREATE TABLE cases (
 id UUID PRIMARY KEY,
 external_case_id VARCHAR(100) NOT NULL UNIQUE,
 bank_id VARCHAR(100) NOT NULL,
 analysis_date TIMESTAMPTZ NULL,
 status VARCHAR(40) NOT NULL DEFAULT 'DRAFT',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_cases_external_case_id ON cases(external_case_id);
CREATE INDEX ix_cases_bank_id ON cases(bank_id);

CREATE TABLE documents (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 original_filename VARCHAR(255) NOT NULL,
 stored_path TEXT NOT NULL,
 mime_type VARCHAR(100) NOT NULL,
 file_size INTEGER NOT NULL CHECK (file_size > 0),
 sha256 VARCHAR(64) NOT NULL,
 document_type VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
 layout_code VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
 evidence_status VARCHAR(30) NOT NULL DEFAULT 'RECEIVED',
 processing_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
 page_count INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT uq_document_case_hash UNIQUE(case_id, sha256)
);
CREATE INDEX ix_documents_case_id ON documents(case_id);
CREATE INDEX ix_documents_sha256 ON documents(sha256);

CREATE TABLE extracted_fields (
 id UUID PRIMARY KEY,
 document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 field_name VARCHAR(100) NOT NULL,
 raw_value TEXT NULL,
 normalized_value JSONB NULL,
 confidence NUMERIC(5,4) NOT NULL DEFAULT 0 CHECK(confidence >= 0 AND confidence <= 1),
 page_number INTEGER NULL,
 bbox JSONB NULL,
 source_line INTEGER NULL,
 review_status VARCHAR(30) NOT NULL DEFAULT 'NEEDS_REVIEW',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_extracted_fields_document_id ON extracted_fields(document_id);
CREATE INDEX ix_extracted_fields_field_name ON extracted_fields(field_name);

CREATE TABLE transactions (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
 source_row INTEGER NOT NULL,
 transaction_date VARCHAR(30) NULL,
 description TEXT NOT NULL DEFAULT '',
 amount_vnd NUMERIC(18,2) NULL,
 direction VARCHAR(10) NOT NULL DEFAULT 'UNKNOWN',
 category VARCHAR(40) NOT NULL DEFAULT 'unknown',
 classification_confidence NUMERIC(5,4) NOT NULL DEFAULT 0,
 is_income_eligible BOOLEAN NOT NULL DEFAULT FALSE,
 review_status VARCHAR(30) NOT NULL DEFAULT 'NEEDS_REVIEW',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT uq_transaction_source_row UNIQUE(case_id, document_id, source_row)
);
CREATE INDEX ix_transactions_case_id ON transactions(case_id);
CREATE INDEX ix_transactions_document_id ON transactions(document_id);
CREATE INDEX ix_transactions_case_date ON transactions(case_id, transaction_date);

CREATE TABLE processing_results (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
 pipeline_version VARCHAR(40) NOT NULL DEFAULT '1.0.0',
 result_status VARCHAR(30) NOT NULL,
 summary JSONB NOT NULL DEFAULT '{}'::jsonb,
 error_message TEXT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_processing_results_case_id ON processing_results(case_id);
CREATE INDEX ix_processing_results_document_id ON processing_results(document_id);

CREATE TABLE audit_events (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 actor VARCHAR(100) NOT NULL DEFAULT 'data-ai-service',
 action VARCHAR(100) NOT NULL,
 entity_type VARCHAR(50) NOT NULL,
 entity_id VARCHAR(100) NOT NULL,
 details JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_audit_events_case_id ON audit_events(case_id);

