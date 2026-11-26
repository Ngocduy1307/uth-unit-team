SET search_path TO data_ai;

-- Customer-entered form snapshots are retained as versioned evidence.
-- The Backend must validate consent/purpose and send only authorized fields.
CREATE TABLE applicant_submissions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    applicant_ref VARCHAR(120) NOT NULL,
    form_version VARCHAR(40) NOT NULL DEFAULT '1',
    form_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    consent_reference VARCHAR(160) NULL,
    submitted_by VARCHAR(120) NOT NULL DEFAULT 'backend',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_applicant_submission_version UNIQUE(case_id, applicant_ref, form_version)
);
CREATE INDEX ix_applicant_submissions_case_id ON applicant_submissions(case_id);
CREATE INDEX ix_applicant_submissions_applicant_ref ON applicant_submissions(applicant_ref);

-- Audit metadata only. Do not store workbook contents or raw applicant data here.
CREATE TABLE export_jobs (
    id UUID PRIMARY KEY,
    bank_id VARCHAR(100) NOT NULL,
    requested_by VARCHAR(120) NOT NULL,
    export_scope VARCHAR(40) NOT NULL DEFAULT 'ALL',
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_export_jobs_bank_id ON export_jobs(bank_id);
CREATE INDEX ix_export_jobs_created_at ON export_jobs(created_at);
