-- V8: production hardening for the existing shared DATA-AI schema.
-- Additive only: preserves V1-V7 objects and existing rows.
-- IMPORTANT: review the preflight report before applying to the target PostgreSQL database.
SET search_path TO data_ai;

-- ---------------------------------------------------------------------------
-- 1. Resolve the legacy text bank identifier on cases without breaking V1 APIs.
-- cases.bank_id remains the legacy external code. New FK-based joins use
-- bank_organization_id. Populate it only after bank-code reconciliation.
-- ---------------------------------------------------------------------------
ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS bank_organization_id UUID;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cases_bank_organization') THEN
        ALTER TABLE cases ADD CONSTRAINT fk_cases_bank_organization
            FOREIGN KEY (bank_organization_id) REFERENCES bank_organizations(id)
            ON DELETE RESTRICT NOT VALID;
    END IF;
END $$;

-- Composite candidate keys permit database-level consistency across tenant,
-- customer, case and application references.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_profiles_id_bank
    ON customer_profiles(id, bank_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cases_id_customer
    ON cases(id, customer_id);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_cases_customer_bank_scope') THEN
        ALTER TABLE cases ADD CONSTRAINT fk_cases_customer_bank_scope
            FOREIGN KEY (customer_id, bank_organization_id)
            REFERENCES customer_profiles(id, bank_id)
            MATCH SIMPLE ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_loan_app_case_customer_consistency') THEN
        ALTER TABLE loan_applications ADD CONSTRAINT fk_loan_app_case_customer_consistency
            FOREIGN KEY (case_id, customer_id)
            REFERENCES cases(id, customer_id)
            MATCH SIMPLE ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_household_case_customer_consistency') THEN
        ALTER TABLE customer_household_profiles ADD CONSTRAINT fk_household_case_customer_consistency
            FOREIGN KEY (case_id, customer_id)
            REFERENCES cases(id, customer_id)
            MATCH SIMPLE ON DELETE RESTRICT NOT VALID;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Consent evidence. This records events, not authentication or legal advice.
-- The Backend must verify identity, notice content/version and lawful purpose.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consent_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL,
    customer_id UUID NOT NULL,
    consent_reference VARCHAR(160) NOT NULL,
    purpose_code VARCHAR(80) NOT NULL,
    notice_version VARCHAR(60) NOT NULL,
    consent_status VARCHAR(20) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    captured_by VARCHAR(160) NOT NULL,
    capture_channel VARCHAR(40) NOT NULL,
    evidence_uri TEXT,
    evidence_sha256 CHAR(64),
    language_code VARCHAR(10) NOT NULL DEFAULT 'vi',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_consent_status CHECK (consent_status IN ('GRANTED','WITHDRAWN','DENIED','EXPIRED')),
    CONSTRAINT ck_consent_sha256 CHECK (evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CONSTRAINT uq_consent_reference_purpose_event UNIQUE(consent_reference, purpose_code, captured_at),
    CONSTRAINT fk_consent_case_customer FOREIGN KEY(case_id, customer_id)
        REFERENCES cases(id, customer_id) MATCH SIMPLE ON DELETE RESTRICT NOT VALID
);
CREATE INDEX IF NOT EXISTS ix_consent_case_purpose_time
    ON consent_events(case_id, purpose_code, captured_at DESC);
CREATE INDEX IF NOT EXISTS ix_consent_reference ON consent_events(consent_reference);

-- ---------------------------------------------------------------------------
-- 3. Declaration request idempotency and section snapshot provenance.
-- Nullable keys keep historical V4/V5 data compatible. New API writes should
-- always provide client_request_id and persist a complete section snapshot.
-- ---------------------------------------------------------------------------
ALTER TABLE customer_expense_declarations
    ADD COLUMN IF NOT EXISTS client_request_id UUID,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE customer_liability_declarations
    ADD COLUMN IF NOT EXISTS client_request_id UUID,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE customer_salary_accounts
    ADD COLUMN IF NOT EXISTS client_request_id UUID,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE customer_household_profiles
    ADD COLUMN IF NOT EXISTS client_request_id UUID,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_case_request
    ON customer_expense_declarations(case_id, client_request_id) WHERE client_request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_liability_case_request
    ON customer_liability_declarations(case_id, client_request_id) WHERE client_request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_salary_account_case_request
    ON customer_salary_accounts(case_id, client_request_id) WHERE client_request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_household_case_request
    ON customer_household_profiles(case_id, client_request_id) WHERE client_request_id IS NOT NULL;

ALTER TABLE customer_declaration_revisions
    ADD COLUMN IF NOT EXISTS customer_id UUID,
    ADD COLUMN IF NOT EXISTS client_request_id UUID,
    ADD COLUMN IF NOT EXISTS payload_sha256 CHAR(64),
    ADD COLUMN IF NOT EXISTS source_channel VARCHAR(40) NOT NULL DEFAULT 'BACKEND';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_declaration_revision_case_customer') THEN
        ALTER TABLE customer_declaration_revisions ADD CONSTRAINT fk_declaration_revision_case_customer
            FOREIGN KEY (case_id, customer_id) REFERENCES cases(id, customer_id)
            MATCH SIMPLE ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_declaration_revision_hash') THEN
        ALTER TABLE customer_declaration_revisions ADD CONSTRAINT ck_declaration_revision_hash
            CHECK (payload_sha256 IS NULL OR payload_sha256 ~ '^[0-9a-fA-F]{64}$') NOT VALID;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_declaration_revision_request
    ON customer_declaration_revisions(case_id, section_code, client_request_id)
    WHERE client_request_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. Enforce maximum three salary accounts per case, safely under concurrency.
-- Uses a transaction-scoped advisory lock per case to serialize competing
-- inserts. This is a structural rule, not proof of account ownership.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_max_three_salary_accounts()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_case_id UUID;
    v_count INTEGER;
BEGIN
    v_case_id := NEW.case_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(v_case_id::text, 8108));
    SELECT COUNT(*) INTO v_count
      FROM customer_salary_accounts
     WHERE case_id = v_case_id
       AND (TG_OP = 'INSERT' OR id <> NEW.id);
    IF v_count >= 3 THEN
        RAISE EXCEPTION 'A case may have at most three salary accounts'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_max_three_salary_accounts';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_max_three_salary_accounts ON customer_salary_accounts;
CREATE TRIGGER trg_max_three_salary_accounts
BEFORE INSERT OR UPDATE OF case_id ON customer_salary_accounts
FOR EACH ROW EXECUTE FUNCTION enforce_max_three_salary_accounts();

-- ---------------------------------------------------------------------------
-- 5. Document security/retention metadata. The actual file bytes remain in an
-- approved private object store, never in PostgreSQL or a public web directory.
-- ---------------------------------------------------------------------------
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS detected_mime_type VARCHAR(150),
    ADD COLUMN IF NOT EXISTS malware_scan_status VARCHAR(24) NOT NULL DEFAULT 'NOT_SCANNED',
    ADD COLUMN IF NOT EXISTS malware_scanned_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS malware_scan_engine VARCHAR(100),
    ADD COLUMN IF NOT EXISTS storage_provider VARCHAR(40),
    ADD COLUMN IF NOT EXISTS storage_object_key TEXT,
    ADD COLUMN IF NOT EXISTS encryption_key_reference VARCHAR(160),
    ADD COLUMN IF NOT EXISTS retention_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_malware_scan_status') THEN
        ALTER TABLE documents ADD CONSTRAINT ck_documents_malware_scan_status
            CHECK (malware_scan_status IN ('NOT_SCANNED','PENDING','CLEAN','INFECTED','ERROR','EXEMPT')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_retention_order') THEN
        ALTER TABLE documents ADD CONSTRAINT ck_documents_retention_order
            CHECK (retention_until IS NULL OR retention_until >= created_at) NOT VALID;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_documents_case_security
    ON documents(case_id, malware_scan_status, processing_status);
CREATE INDEX IF NOT EXISTS ix_documents_retention
    ON documents(retention_until) WHERE deleted_at IS NULL AND legal_hold = FALSE;

CREATE TABLE IF NOT EXISTS document_security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    event_type VARCHAR(40) NOT NULL,
    scan_status VARCHAR(24),
    engine_name VARCHAR(100),
    engine_version VARCHAR(80),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_by VARCHAR(160) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_document_security_events_document_time
    ON document_security_events(document_id, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- 6. Make payroll extraction traceable to exact OCR fields where available.
-- These nullable references preserve legacy evidence and allow partial anchors.
-- ---------------------------------------------------------------------------
ALTER TABLE payroll_evidence
    ADD COLUMN IF NOT EXISTS gross_amount_field_id UUID,
    ADD COLUMN IF NOT EXISTS net_amount_field_id UUID,
    ADD COLUMN IF NOT EXISTS payment_date_field_id UUID,
    ADD COLUMN IF NOT EXISTS pay_period_start_field_id UUID,
    ADD COLUMN IF NOT EXISTS pay_period_end_field_id UUID,
    ADD COLUMN IF NOT EXISTS extraction_version VARCHAR(60),
    ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(160),
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payroll_gross_field') THEN
        ALTER TABLE payroll_evidence ADD CONSTRAINT fk_payroll_gross_field
            FOREIGN KEY (gross_amount_field_id) REFERENCES extracted_fields(id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payroll_net_field') THEN
        ALTER TABLE payroll_evidence ADD CONSTRAINT fk_payroll_net_field
            FOREIGN KEY (net_amount_field_id) REFERENCES extracted_fields(id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payroll_payment_date_field') THEN
        ALTER TABLE payroll_evidence ADD CONSTRAINT fk_payroll_payment_date_field
            FOREIGN KEY (payment_date_field_id) REFERENCES extracted_fields(id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payroll_period_start_field') THEN
        ALTER TABLE payroll_evidence ADD CONSTRAINT fk_payroll_period_start_field
            FOREIGN KEY (pay_period_start_field_id) REFERENCES extracted_fields(id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payroll_period_end_field') THEN
        ALTER TABLE payroll_evidence ADD CONSTRAINT fk_payroll_period_end_field
            FOREIGN KEY (pay_period_end_field_id) REFERENCES extracted_fields(id) ON DELETE RESTRICT NOT VALID;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_payroll_evidence_source_fields
    ON payroll_evidence(gross_amount_field_id, net_amount_field_id);

-- ---------------------------------------------------------------------------
-- 7. Append-only evidence/event history. Corrections are new events/revisions.
-- Privileged DB owners can still bypass triggers; restrict owner credentials.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reject_append_only_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; create a compensating event/revision', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS trg_consent_events_append_only ON consent_events;
CREATE TRIGGER trg_consent_events_append_only
BEFORE UPDATE OR DELETE ON consent_events
FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
DROP TRIGGER IF EXISTS trg_declaration_revisions_append_only ON customer_declaration_revisions;
CREATE TRIGGER trg_declaration_revisions_append_only
BEFORE UPDATE OR DELETE ON customer_declaration_revisions
FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
DROP TRIGGER IF EXISTS trg_document_security_events_append_only ON document_security_events;
CREATE TRIGGER trg_document_security_events_append_only
BEFORE UPDATE OR DELETE ON document_security_events
FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
CREATE TRIGGER trg_audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();

-- ---------------------------------------------------------------------------
-- 8. Supporting indexes for case-centric retrieval and review queues.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_cases_bank_org_customer_created
    ON cases(bank_organization_id, customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_expenses_case_review_created
    ON customer_expense_declarations(case_id, review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_liabilities_case_review_created
    ON customer_liability_declarations(case_id, review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_salary_accounts_case_verification
    ON customer_salary_accounts(case_id, ownership_verification_status);
CREATE INDEX IF NOT EXISTS ix_consent_latest_case_purpose
    ON consent_events(case_id, purpose_code, captured_at DESC);

COMMENT ON COLUMN cases.bank_id IS 'Legacy external bank code retained for backward compatibility; use bank_organization_id for FK-based joins.';
COMMENT ON COLUMN cases.bank_organization_id IS 'Nullable normalized FK to bank_organizations; backfill only after verified bank-code mapping.';
COMMENT ON TABLE consent_events IS 'Append-only consent event evidence. Backend/Legal own identity, notice and lawful-basis validation.';
COMMENT ON TABLE document_security_events IS 'Append-only malware/security scan history for private document storage.';
COMMENT ON COLUMN documents.storage_object_key IS 'Opaque private object-store key; never a public URL or local filesystem path.';
COMMENT ON TABLE customer_declaration_revisions IS 'Append-only section snapshots. Corrections create a new revision; do not overwrite history.';
COMMENT ON TABLE payroll_evidence IS 'Evidence extracted from documents; source-field FKs link back to exact extracted_fields when available.';
