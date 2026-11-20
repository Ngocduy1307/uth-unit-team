ALTER TABLE dossiers
    ADD COLUMN IF NOT EXISTS loan_product VARCHAR(64),
    ADD COLUMN IF NOT EXISTS requested_amount NUMERIC(18, 2),
    ADD COLUMN IF NOT EXISTS requested_tenor_months INT,
    ADD COLUMN IF NOT EXISTS proposed_interest_rate NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS monthly_declared_living_expense NUMERIC(18, 2);

ALTER TABLE evidence_records
    ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS mime_type VARCHAR(128),
    ADD COLUMN IF NOT EXISTS ocr_status VARCHAR(32) DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS ocr_processed_at TIMESTAMP WITH TIME ZONE;

CREATE TABLE IF NOT EXISTS statement_accounts (
    id VARCHAR(36) PRIMARY KEY,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    bank_name VARCHAR(128) NOT NULL,
    bank_code VARCHAR(32) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    account_holder_name VARCHAR(255) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    statement_from_date DATE,
    statement_to_date DATE,
    total_credit_amount NUMERIC(18, 2) DEFAULT 0,
    total_debit_amount NUMERIC(18, 2) DEFAULT 0,
    is_holder_matched BOOLEAN DEFAULT FALSE,
    match_confidence NUMERIC(5, 2),
    is_verified BOOLEAN DEFAULT FALSE,
    verified_by VARCHAR(64),
    verified_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_statement_accounts_dossier_bank_acc UNIQUE (dossier_id, bank_code, account_number)
);

CREATE INDEX IF NOT EXISTS idx_statement_accounts_dossier_id ON statement_accounts(dossier_id);
CREATE INDEX IF NOT EXISTS idx_statement_accounts_account_number ON statement_accounts(account_number);

CREATE TABLE IF NOT EXISTS transaction_ledger (
    id VARCHAR(36) PRIMARY KEY,
    account_id VARCHAR(36) NOT NULL REFERENCES statement_accounts(id) ON DELETE CASCADE,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    transaction_date DATE NOT NULL,
    booking_date DATE,
    amount NUMERIC(18, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    direction VARCHAR(10) NOT NULL,
    running_balance NUMERIC(18, 2),
    description TEXT NOT NULL,
    classification VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    confidence_score NUMERIC(5, 2),
    is_recurring_salary BOOLEAN DEFAULT FALSE,
    source_page INT,
    source_row INT,
    is_accepted BOOLEAN NOT NULL DEFAULT TRUE,
    exclusion_reason VARCHAR(255),
    adjusted_amount NUMERIC(18, 2),
    adjusted_by VARCHAR(64),
    adjusted_at TIMESTAMP WITH TIME ZONE,
    adjustment_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trans_ledger_account_id ON transaction_ledger(account_id);
CREATE INDEX IF NOT EXISTS idx_trans_ledger_dossier_id ON transaction_ledger(dossier_id);
CREATE INDEX IF NOT EXISTS idx_trans_ledger_date ON transaction_ledger(dossier_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_trans_ledger_classification ON transaction_ledger(dossier_id, classification);

CREATE TABLE IF NOT EXISTS obligations (
    id VARCHAR(36) PRIMARY KEY,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    institution_name VARCHAR(255) NOT NULL,
    obligation_type VARCHAR(32) NOT NULL,
    monthly_payment NUMERIC(18, 2) NOT NULL,
    total_balance NUMERIC(18, 2) NOT NULL DEFAULT 0,
    remaining_tenor_months INT,
    interest_rate NUMERIC(5, 2),
    source VARCHAR(32) NOT NULL DEFAULT 'DECLARED',
    is_duplicated BOOLEAN NOT NULL DEFAULT FALSE,
    is_included_in_dti BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obligations_dossier_id ON obligations(dossier_id);
CREATE INDEX IF NOT EXISTS idx_obligations_source ON obligations(dossier_id, source);

CREATE TABLE IF NOT EXISTS affordability_snapshots (
    id VARCHAR(36) PRIMARY KEY,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    snapshot_version INT NOT NULL DEFAULT 1,
    formula_version VARCHAR(32) NOT NULL DEFAULT 'V1',
    eligible_net_income NUMERIC(18, 2) NOT NULL,
    declared_living_expenses NUMERIC(18, 2) NOT NULL,
    floor_living_expenses NUMERIC(18, 2) NOT NULL,
    effective_living_expenses NUMERIC(18, 2) NOT NULL,
    existing_debt_service NUMERIC(18, 2) NOT NULL,
    proposed_loan_amount NUMERIC(18, 2) NOT NULL,
    proposed_loan_tenor_months INT NOT NULL,
    proposed_interest_rate NUMERIC(5, 2) NOT NULL,
    proposed_loan_payment NUMERIC(18, 2) NOT NULL,
    baseline_residual NUMERIC(18, 2) NOT NULL,
    baseline_dti NUMERIC(5, 4) NOT NULL,
    stress1_residual NUMERIC(18, 2) NOT NULL,
    stress1_dti NUMERIC(5, 4) NOT NULL,
    stress2_residual NUMERIC(18, 2) NOT NULL,
    stress2_dti NUMERIC(5, 4) NOT NULL,
    max_dti_limit NUMERIC(5, 4) NOT NULL DEFAULT 0.5000,
    min_residual_limit NUMERIC(18, 2) NOT NULL DEFAULT 5000000.00,
    policy_status VARCHAR(32) NOT NULL,
    policy_notes TEXT,
    calculated_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_snapshots_dossier_version UNIQUE (dossier_id, snapshot_version)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_dossier_id ON affordability_snapshots(dossier_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_policy_status ON affordability_snapshots(policy_status);

CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    dossier_id VARCHAR(36) NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    entity_name VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    field_name VARCHAR(64),
    old_value TEXT,
    new_value TEXT,
    actor_id VARCHAR(64) NOT NULL,
    actor_role VARCHAR(32) NOT NULL,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_dossier_id ON audit_logs(dossier_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_name, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
