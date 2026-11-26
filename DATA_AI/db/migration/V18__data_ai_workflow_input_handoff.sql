-- V10.0 DATA-AI workflow completion: signed scope/consent attestations,
-- immutable domain declarations/reviews and a hash-bound Financial Engine handoff.
-- DATA-AI stores evidence and references only. Backend owns consent/identity,
-- Camunda owns routing, and Business/Financial Engine owns calculations/policy.
SET search_path TO data_ai;

INSERT INTO access_roles(id, role_code, role_name, description) VALUES
 ('a0000000-0000-4000-8000-000000000010','BACKEND_SCOPE_ATTESTOR','Backend Scope Attestor','Backend/SSO-signed scope and consent attestation ingress'),
 ('a0000000-0000-4000-8000-000000000011','BACKEND_DATA_INGESTOR','Backend Data Ingestor','Versioned applicant declaration ingress from the authoritative Backend'),
 ('a0000000-0000-4000-8000-000000000013','DATA_AI_SERVICE','DATA-AI Service','Dedicated internal service identity for Data-AI workflow handoff operations')
ON CONFLICT (id) DO NOTHING;

INSERT INTO permissions(id, permission_code, resource, action, description) VALUES
 ('b0000000-0000-4000-8000-000000000018','SCOPE_CONSENT_ATTEST','CASE_SCOPE_CONSENT','CREATE','Record Backend-authoritative scope and consent attestation'),
 ('b0000000-0000-4000-8000-000000000019','APPLICANT_DECLARATION_INGEST','CASE_DECLARATION','CREATE','Ingest immutable versioned applicant declaration payloads'),
 ('b0000000-0000-4000-8000-000000000020','FINANCIAL_INPUT_BUNDLE_CREATE','FINANCIAL_INPUT_BUNDLE','CREATE','Create hash-bound DATA-AI input handoff for the Financial Engine'),
 ('b0000000-0000-4000-8000-000000000021','FINANCIAL_INPUT_BUNDLE_READ','FINANCIAL_INPUT_BUNDLE','READ','Read a scoped DATA-AI input bundle from the Financial Engine'),
 ('b0000000-0000-4000-8000-000000000022','CASE_INPUT_MAKER_REVIEW','CASE_INPUT_REVIEW','CREATE','Record Maker-only evidence anchored input review'),
 ('b0000000-0000-4000-8000-000000000023','PROPOSED_SCHEDULE_REFERENCE_CREATE','PROPOSED_SCHEDULE_REFERENCE','CREATE','Record external Business Engine schedule reference'),
 ('b0000000-0000-4000-8000-000000000024','BUSINESS_ENGINE_RECEIPT_CREATE','BUSINESS_ENGINE_RECEIPT','CREATE','Record external Business Engine calculation receipt'),
 ('b0000000-0000-4000-8000-000000000025','APPLICANT_DECLARATION_READ','CASE_DECLARATION','READ','Read scoped declaration revision metadata')
ON CONFLICT (id) DO NOTHING;

INSERT INTO role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM access_roles r JOIN permissions p ON
 (r.role_code = 'BACKEND_SCOPE_ATTESTOR' AND p.permission_code = 'SCOPE_CONSENT_ATTEST') OR
 (r.role_code = 'BACKEND_DATA_INGESTOR' AND p.permission_code = 'APPLICANT_DECLARATION_INGEST') OR
 (r.role_code = 'DATA_AI_SERVICE' AND p.permission_code = 'FINANCIAL_INPUT_BUNDLE_CREATE') OR
 (r.role_code = 'BUSINESS_ENGINE' AND p.permission_code IN ('FINANCIAL_INPUT_BUNDLE_READ','PROPOSED_SCHEDULE_REFERENCE_CREATE','BUSINESS_ENGINE_RECEIPT_CREATE')) OR
 (r.role_code = 'MAKER' AND p.permission_code = 'CASE_INPUT_MAKER_REVIEW') OR
 (r.role_code IN ('BACKEND_DATA_INGESTOR','MAKER','CHECKER','DATA_AI_SERVICE') AND p.permission_code = 'APPLICANT_DECLARATION_READ')
ON CONFLICT DO NOTHING;

CREATE TABLE case_scope_consent_attestations (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bank_id VARCHAR(100) NOT NULL,
    scope_code VARCHAR(80) NOT NULL,
    scope_status VARCHAR(20) NOT NULL,
    consent_status VARCHAR(20) NOT NULL,
    consent_reference VARCHAR(160) NOT NULL,
    purpose_code VARCHAR(80) NOT NULL,
    notice_version VARCHAR(60) NOT NULL,
    backend_decision_reference VARCHAR(160) NOT NULL,
    attestation_sha256 VARCHAR(64) NOT NULL,
    attested_by VARCHAR(160) NOT NULL,
    attested_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_scope_attestation_scope_status CHECK (scope_status IN ('IN_SCOPE','OUT_OF_SCOPE')),
    CONSTRAINT ck_scope_attestation_consent_status CHECK (consent_status IN ('GRANTED','REVOKED','NOT_GRANTED')),
    CONSTRAINT ck_scope_attestation_product_scope CHECK (scope_code = 'VN_UNSECURED_SALARIED_VND'),
    CONSTRAINT ck_scope_attestation_hash CHECK (attestation_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_scope_attestation_refs CHECK (
        length(trim(consent_reference)) > 0 AND length(trim(purpose_code)) > 0 AND
        length(trim(notice_version)) > 0 AND length(trim(backend_decision_reference)) > 0 AND
        length(trim(attested_by)) > 0
    ),
    CONSTRAINT uq_case_scope_backend_decision UNIQUE(case_id, backend_decision_reference)
);
CREATE INDEX ix_scope_attestation_case_latest
    ON case_scope_consent_attestations(case_id, attested_at DESC, id DESC);

CREATE OR REPLACE FUNCTION validate_case_scope_attestation_bank_v18()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_bank_id VARCHAR(100);
BEGIN
    SELECT bank_id INTO v_bank_id FROM cases WHERE id = NEW.case_id FOR KEY SHARE;
    IF NOT FOUND OR NEW.bank_id IS DISTINCT FROM v_bank_id THEN
        RAISE EXCEPTION 'scope/consent attestation bank must match its case'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_scope_attestation_bank_scope';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_validate_case_scope_attestation_bank_v18
    BEFORE INSERT ON case_scope_consent_attestations
    FOR EACH ROW EXECUTE FUNCTION validate_case_scope_attestation_bank_v18();

CREATE TABLE case_input_declaration_revisions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    customer_id UUID NOT NULL,
    section_code VARCHAR(32) NOT NULL,
    revision_no INTEGER NOT NULL,
    payload JSONB NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    submitted_by VARCHAR(160) NOT NULL,
    source_channel VARCHAR(32) NOT NULL DEFAULT 'BACKEND',
    client_request_id UUID NULL,
    supersedes_revision_id UUID NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_input_declaration_section CHECK (section_code IN ('HOUSEHOLD','EMPLOYMENT','EXPENSES','LIABILITIES','SALARY_ACCOUNTS')),
    CONSTRAINT ck_case_input_declaration_revision_no CHECK (revision_no > 0),
    CONSTRAINT ck_case_input_declaration_payload CHECK (jsonb_typeof(payload) = 'object' AND payload <> '{}'::jsonb),
    CONSTRAINT ck_case_input_declaration_hash CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_input_declaration_actor CHECK (length(trim(submitted_by)) > 0),
    CONSTRAINT uq_case_input_declaration_revision UNIQUE(case_id, section_code, revision_no),
    CONSTRAINT uq_case_input_declaration_id_case UNIQUE(id, case_id),
    CONSTRAINT fk_case_input_declaration_supersedes_case FOREIGN KEY(supersedes_revision_id, case_id)
        REFERENCES case_input_declaration_revisions(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_case_input_declaration_case_customer FOREIGN KEY(case_id, customer_id)
        REFERENCES cases(id, customer_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_input_declaration_latest
    ON case_input_declaration_revisions(case_id, section_code, revision_no DESC);
CREATE UNIQUE INDEX uq_case_input_declaration_client_request
    ON case_input_declaration_revisions(case_id, client_request_id)
    WHERE client_request_id IS NOT NULL;

CREATE TABLE case_input_declaration_evidence_links (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    declaration_revision_id UUID NOT NULL,
    document_id UUID NOT NULL,
    document_sha256 VARCHAR(64) NOT NULL,
    link_purpose VARCHAR(40) NOT NULL DEFAULT 'SUPPORTING_EVIDENCE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_input_declaration_evidence_hash CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_case_input_declaration_evidence UNIQUE(declaration_revision_id, document_id),
    CONSTRAINT fk_case_input_decl_evidence_revision_case FOREIGN KEY(declaration_revision_id, case_id)
        REFERENCES case_input_declaration_revisions(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_case_input_decl_evidence_document_case FOREIGN KEY(document_id, case_id)
        REFERENCES documents(id, case_id) ON DELETE RESTRICT
);

CREATE TABLE case_input_review_decisions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    declaration_revision_id UUID NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id UUID NOT NULL,
    decision_code VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    reviewed_by VARCHAR(160) NOT NULL,
    reviewer_role VARCHAR(24) NOT NULL DEFAULT 'MAKER',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_input_review_target CHECK (target_type IN ('DECLARATION_REVISION','EXTRACTED_FIELD','PAYROLL_EVIDENCE','EARNING_MATCH','TRANSACTION','INCOME_LEDGER')),
    CONSTRAINT ck_case_input_review_decision CHECK (decision_code IN ('CONFIRMED','RETURNED','UNABLE_TO_VERIFY','REJECTED')),
    CONSTRAINT ck_case_input_review_reason_actor CHECK (length(trim(reason)) >= 8 AND length(trim(reviewed_by)) > 0),
    CONSTRAINT ck_case_input_review_role CHECK (reviewer_role = 'MAKER'),
    CONSTRAINT ck_case_input_review_evidence_array CHECK (jsonb_typeof(evidence_refs) = 'array'),
    CONSTRAINT ck_case_input_review_declaration_target CHECK (
        (target_type = 'DECLARATION_REVISION' AND declaration_revision_id = target_id) OR
        (target_type <> 'DECLARATION_REVISION' AND declaration_revision_id IS NULL)
    ),
    CONSTRAINT fk_case_input_review_declaration_case FOREIGN KEY(declaration_revision_id, case_id)
        REFERENCES case_input_declaration_revisions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_input_review_target_latest
    ON case_input_review_decisions(case_id, target_type, target_id, created_at DESC);

CREATE TABLE case_financial_input_bundles (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bundle_no INTEGER NOT NULL,
    readiness_status VARCHAR(32) NOT NULL,
    readiness JSONB NOT NULL,
    bundle_data JSONB NOT NULL,
    bundle_sha256 VARCHAR(64) NOT NULL,
    created_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_financial_input_bundle_no CHECK (bundle_no > 0),
    CONSTRAINT ck_financial_input_bundle_readiness CHECK (readiness_status IN ('READY_FOR_BUSINESS_ENGINE','BLOCKED','INSUFFICIENT_EVIDENCE','NEEDS_MAKER_REVIEW')),
    CONSTRAINT ck_financial_input_bundle_objects CHECK (jsonb_typeof(readiness) = 'object' AND jsonb_typeof(bundle_data) = 'object'),
    CONSTRAINT ck_financial_input_bundle_hash CHECK (bundle_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_financial_input_bundle_actor CHECK (length(trim(created_by)) > 0),
    CONSTRAINT uq_financial_input_bundle_no UNIQUE(case_id, bundle_no),
    CONSTRAINT uq_financial_input_bundle_id_case UNIQUE(id, case_id)
);
CREATE INDEX ix_financial_input_bundle_case_created ON case_financial_input_bundles(case_id, created_at DESC);

CREATE TABLE case_proposed_schedule_references (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bundle_id UUID NOT NULL,
    schedule_reference VARCHAR(160) NOT NULL UNIQUE,
    schedule_sha256 VARCHAR(64) NOT NULL,
    product_code VARCHAR(80) NOT NULL,
    product_version VARCHAR(80) NOT NULL,
    term_months INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    provided_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_proposed_schedule_hash CHECK (schedule_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_proposed_schedule_term CHECK (term_months BETWEEN 6 AND 36),
    CONSTRAINT ck_proposed_schedule_currency CHECK (currency = 'VND'),
    CONSTRAINT ck_proposed_schedule_refs CHECK (length(trim(product_code)) > 0 AND length(trim(product_version)) > 0 AND length(trim(provided_by)) > 0),
    CONSTRAINT uq_proposed_schedule_id_case UNIQUE(id, case_id),
    CONSTRAINT fk_proposed_schedule_bundle_case FOREIGN KEY(bundle_id, case_id)
        REFERENCES case_financial_input_bundles(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_proposed_schedule_case_created ON case_proposed_schedule_references(case_id, created_at DESC);

CREATE TABLE case_business_engine_receipts (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bundle_id UUID NOT NULL,
    schedule_reference_id UUID NULL,
    input_bundle_sha256 VARCHAR(64) NOT NULL,
    calculation_reference VARCHAR(160) NOT NULL UNIQUE,
    calculation_version VARCHAR(80) NOT NULL,
    policy_reference VARCHAR(160) NOT NULL,
    policy_version VARCHAR(80) NOT NULL,
    product_code VARCHAR(80) NOT NULL,
    product_version VARCHAR(80) NOT NULL,
    product_sha256 VARCHAR(64) NOT NULL,
    policy_sha256 VARCHAR(64) NOT NULL,
    result_status VARCHAR(24) NOT NULL,
    scenario_references JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_sha256 VARCHAR(64) NOT NULL,
    received_by VARCHAR(160) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_business_engine_receipt_hashes CHECK (input_bundle_sha256 ~ '^[0-9a-f]{64}$' AND output_sha256 ~ '^[0-9a-f]{64}$' AND product_sha256 ~ '^[0-9a-f]{64}$' AND policy_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_business_engine_receipt_status CHECK (result_status IN ('COMPLETED','HOLD','FAILED')),
    CONSTRAINT ck_business_engine_scenario_object CHECK (jsonb_typeof(scenario_references) = 'object'),
    CONSTRAINT ck_business_engine_completed_scenarios CHECK (
        result_status <> 'COMPLETED' OR
        (schedule_reference_id IS NOT NULL AND scenario_references ? 'BASELINE' AND
         scenario_references ? 'STRESS_1' AND scenario_references ? 'STRESS_2' AND
         (scenario_references - 'BASELINE' - 'STRESS_1' - 'STRESS_2') = '{}'::jsonb)
    ),
    CONSTRAINT ck_business_engine_receipt_refs CHECK (
        length(trim(calculation_reference)) > 0 AND length(trim(calculation_version)) > 0 AND
        length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0 AND
        length(trim(product_code)) > 0 AND length(trim(product_version)) > 0 AND length(trim(received_by)) > 0
    ),
    CONSTRAINT fk_business_engine_receipt_bundle_case FOREIGN KEY(bundle_id, case_id)
        REFERENCES case_financial_input_bundles(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_business_engine_receipt_schedule_case FOREIGN KEY(schedule_reference_id, case_id)
        REFERENCES case_proposed_schedule_references(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_business_engine_receipt_case_received ON case_business_engine_receipts(case_id, received_at DESC);

-- All V18 workflow/input records are immutable; corrections are represented by new rows.
CREATE OR REPLACE FUNCTION deny_v18_append_only_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'V18 workflow handoff records are append-only; insert a superseding record'
        USING ERRCODE = '55000', CONSTRAINT = 'ck_v18_append_only';
END $$;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'case_scope_consent_attestations',
        'case_input_declaration_revisions',
        'case_input_declaration_evidence_links',
        'case_input_review_decisions',
        'case_financial_input_bundles',
        'case_proposed_schedule_references',
        'case_business_engine_receipts'
    ] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION deny_v18_append_only_mutation()',
                       'trg_' || t || '_append_only_v18', t);
    END LOOP;
END $$;

COMMENT ON TABLE case_scope_consent_attestations IS
    'Append-only mirror of Backend/SSO scope and consent decisions; DATA-AI does not legally validate consent.';
COMMENT ON TABLE case_input_declaration_revisions IS
    'Versioned household/employment/expense/liability/salary-account declarations received from Backend; missing values remain NULL.';
COMMENT ON TABLE case_input_review_decisions IS
    'Append-only Maker review of source/input records; does not decide eligible income, DSR or policy outcome.';
COMMENT ON TABLE case_financial_input_bundles IS
    'Hash-bound DATA-AI evidence/input handoff. Financial calculations are performed by a separate authoritative engine.';
COMMENT ON TABLE case_proposed_schedule_references IS
    'Opaque proposed repayment schedule reference and hash supplied by Business Engine; DATA-AI does not calculate or validate the schedule.';
COMMENT ON TABLE case_business_engine_receipts IS
    'Immutable receipt of external calculation, product and policy versions plus scenario references; no credit decision is made by DATA-AI.';
