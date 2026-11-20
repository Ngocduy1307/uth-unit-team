SET search_path TO data_ai;

-- Registry is intentionally configurable. Do not invent bank-approved layouts or CSV schemas.
CREATE TABLE source_inventory (
 id UUID PRIMARY KEY,
 source_code VARCHAR(80) NOT NULL UNIQUE,
 source_name VARCHAR(200) NOT NULL,
 source_type VARCHAR(40) NOT NULL,
 schema_version VARCHAR(40) NOT NULL,
 approval_status VARCHAR(30) NOT NULL DEFAULT 'PENDING_APPROVAL',
 config JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE field_mapping_registry (
 id UUID PRIMARY KEY,
 source_code VARCHAR(80) NOT NULL,
 schema_version VARCHAR(40) NOT NULL,
 source_field VARCHAR(150) NOT NULL,
 target_field VARCHAR(100) NOT NULL,
 transform_code VARCHAR(80) NULL,
 is_required BOOLEAN NOT NULL DEFAULT FALSE,
 approval_status VARCHAR(30) NOT NULL DEFAULT 'PENDING_APPROVAL',
 UNIQUE(source_code, schema_version, source_field, target_field)
);

CREATE TABLE payroll_evidence (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
 pay_period_start DATE NULL,
 pay_period_end DATE NULL,
 payment_date DATE NULL,
 gross_amount NUMERIC(18,2) NULL,
 net_amount NUMERIC(18,2) NULL,
 currency CHAR(3) NOT NULL DEFAULT 'VND',
 evidence_status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
 source_anchor JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_payroll_evidence_case_id ON payroll_evidence(case_id);

CREATE TABLE earning_match_candidates (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 payroll_evidence_id UUID NOT NULL REFERENCES payroll_evidence(id) ON DELETE CASCADE,
 transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
 similarity_score NUMERIC(6,5) NOT NULL CHECK(similarity_score >= 0 AND similarity_score <= 1),
 match_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
 review_status VARCHAR(30) NOT NULL DEFAULT 'SUGGESTED',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(payroll_evidence_id, transaction_id)
);
CREATE INDEX ix_match_candidates_case_id ON earning_match_candidates(case_id);

CREATE TABLE income_ledger_months (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 period_month DATE NOT NULL,
 observed_amount NUMERIC(18,2) NULL,
 accepted_amount NUMERIC(18,2) NULL,
 excluded_amount NUMERIC(18,2) NULL,
 month_status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
 exclusion_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
 reviewed_by VARCHAR(100) NULL,
 reviewed_at TIMESTAMPTZ NULL,
 UNIQUE(case_id, period_month)
);
CREATE INDEX ix_income_ledger_case_month ON income_ledger_months(case_id, period_month);

CREATE TABLE data_quality_issues (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
 issue_code VARCHAR(80) NOT NULL,
 severity VARCHAR(20) NOT NULL,
 description TEXT NOT NULL,
 source_anchor JSONB NOT NULL DEFAULT '{}'::jsonb,
 issue_status VARCHAR(30) NOT NULL DEFAULT 'OPEN',
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 resolved_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_data_quality_case_id ON data_quality_issues(case_id);

CREATE TABLE pipeline_runs (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 document_id UUID NULL REFERENCES documents(id) ON DELETE SET NULL,
 idempotency_key VARCHAR(150) NOT NULL UNIQUE,
 pipeline_version VARCHAR(40) NOT NULL,
 status VARCHAR(30) NOT NULL,
 started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 completed_at TIMESTAMPTZ NULL,
 metrics JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ix_pipeline_runs_case_id ON pipeline_runs(case_id);

