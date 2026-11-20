-- Applicant declarations needed for salaried VND consumer-loan affordability evidence.
-- These are declarations/evidence records only; no credit decision or affordability calculation.
CREATE TABLE data_ai.customer_household_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES data_ai.customer_profiles(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL REFERENCES data_ai.cases(id) ON DELETE CASCADE,
    household_size SMALLINT,
    dependents_count SMALLINT,
    housing_status VARCHAR(30), -- OWNED, RENTED, WITH_FAMILY, OTHER, UNKNOWN
    residence_since DATE,
    household_notes TEXT,
    declaration_status VARCHAR(24) NOT NULL DEFAULT 'DECLARED',
    declared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_household_size CHECK (household_size IS NULL OR household_size BETWEEN 1 AND 30),
    CONSTRAINT ck_household_dependents CHECK (dependents_count IS NULL OR dependents_count BETWEEN 0 AND 30)
);
CREATE INDEX ix_household_case ON data_ai.customer_household_profiles(case_id);

CREATE TABLE data_ai.customer_expense_declarations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES data_ai.cases(id) ON DELETE CASCADE,
    expense_category VARCHAR(40) NOT NULL, -- HOUSING, UTILITIES, FOOD, EDUCATION, HEALTHCARE, TRANSPORT, OTHER
    amount_vnd NUMERIC(18,2),
    frequency VARCHAR(20) NOT NULL DEFAULT 'MONTHLY',
    description TEXT,
    source_type VARCHAR(24) NOT NULL DEFAULT 'CUSTOMER_DECLARED',
    review_status VARCHAR(24) NOT NULL DEFAULT 'PENDING_REVIEW',
    reviewed_by VARCHAR(120),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_expense_amount CHECK (amount_vnd IS NULL OR amount_vnd >= 0)
);
CREATE INDEX ix_expense_case ON data_ai.customer_expense_declarations(case_id);

CREATE TABLE data_ai.customer_liability_declarations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES data_ai.cases(id) ON DELETE CASCADE,
    liability_type VARCHAR(40) NOT NULL, -- INSTALLMENT_LOAN, CREDIT_CARD, OVERDRAFT, INFORMAL_DEBT, GUARANTEE, OTHER
    creditor_name VARCHAR(200),
    account_ref_last4 VARCHAR(4),
    outstanding_balance_vnd NUMERIC(18,2),
    monthly_payment_vnd NUMERIC(18,2),
    due_day SMALLINT,
    start_date DATE,
    expected_end_date DATE,
    is_overdue BOOLEAN,
    overdue_amount_vnd NUMERIC(18,2),
    source_type VARCHAR(24) NOT NULL DEFAULT 'CUSTOMER_DECLARED',
    review_status VARCHAR(24) NOT NULL DEFAULT 'PENDING_REVIEW',
    reviewed_by VARCHAR(120),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_liability_balance CHECK (outstanding_balance_vnd IS NULL OR outstanding_balance_vnd >= 0),
    CONSTRAINT ck_liability_payment CHECK (monthly_payment_vnd IS NULL OR monthly_payment_vnd >= 0),
    CONSTRAINT ck_liability_due_day CHECK (due_day IS NULL OR due_day BETWEEN 1 AND 31),
    CONSTRAINT ck_liability_last4 CHECK (account_ref_last4 IS NULL OR account_ref_last4 ~ '^[0-9]{4}$')
);
CREATE INDEX ix_liability_case ON data_ai.customer_liability_declarations(case_id);

CREATE TABLE data_ai.customer_salary_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES data_ai.cases(id) ON DELETE CASCADE,
    bank_name VARCHAR(160) NOT NULL,
    bank_code VARCHAR(30),
    account_holder_name VARCHAR(200),
    account_number_last4 VARCHAR(4),
    currency CHAR(3) NOT NULL DEFAULT 'VND',
    statement_start DATE,
    statement_end DATE,
    ownership_verification_status VARCHAR(24) NOT NULL DEFAULT 'UNVERIFIED',
    verified_by VARCHAR(120),
    verified_at TIMESTAMPTZ,
    evidence_document_id UUID REFERENCES data_ai.documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_salary_account_last4 CHECK (account_number_last4 IS NULL OR account_number_last4 ~ '^[0-9]{4}$'),
    CONSTRAINT ck_salary_account_currency CHECK (currency = 'VND'),
    CONSTRAINT ck_salary_statement_dates CHECK (statement_end IS NULL OR statement_start IS NULL OR statement_end >= statement_start)
);
CREATE INDEX ix_salary_account_case ON data_ai.customer_salary_accounts(case_id);

CREATE TABLE data_ai.customer_declaration_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES data_ai.cases(id) ON DELETE CASCADE,
    section_code VARCHAR(40) NOT NULL,
    revision_no INTEGER NOT NULL,
    payload JSONB NOT NULL,
    submitted_by VARCHAR(120) NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id UUID REFERENCES data_ai.customer_declaration_revisions(id) ON DELETE SET NULL,
    UNIQUE(case_id, section_code, revision_no)
);
CREATE INDEX ix_declaration_revision_case ON data_ai.customer_declaration_revisions(case_id, section_code, revision_no DESC);

COMMENT ON TABLE data_ai.customer_expense_declarations IS 'Customer-declared expenses; must be reviewed by bank staff before business calculation.';
COMMENT ON TABLE data_ai.customer_liability_declarations IS 'Customer-declared liabilities; not a consolidated or verified debt register.';
COMMENT ON TABLE data_ai.customer_salary_accounts IS 'At most three salary accounts per borrower/case; ownership and statement period require staff verification.';
COMMENT ON TABLE data_ai.customer_declaration_revisions IS 'Append-only snapshots for customer declaration changes and auditability.';
