-- V15: hash-chained case audit ledger and non-executing Named Authority approval records.
-- Backend/SSO validates grants and assignment; DATA-AI records approvals but does not execute overrides or complete Camunda tasks.
SET search_path TO data_ai;

INSERT INTO access_roles(id, role_code, role_name, description) VALUES
 ('a0000000-0000-4000-8000-000000000009','NAMED_AUTHORITY','Named Authority','Bank-designated authority for scoped Override and Policy Exception approval; grant validity and limits are enforced by Backend/SSO')
ON CONFLICT(role_code) DO NOTHING;

INSERT INTO permissions(id, permission_code, resource, action, description) VALUES
 ('b0000000-0000-4000-8000-000000000015','OVERRIDE_APPROVE','OVERRIDE','APPROVE','Approve or reject a case-scoped Override proposal under a Backend-validated named authority grant'),
 ('b0000000-0000-4000-8000-000000000016','POLICY_EXCEPTION_APPROVE','POLICY_EXCEPTION','APPROVE','Approve or reject a policy exception proposal under a Backend-validated named authority grant'),
 ('b0000000-0000-4000-8000-000000000017','CASE_GOVERNANCE_AUDIT_VIEW','CASE_GOVERNANCE_AUDIT','VIEW','Read and verify scoped case governance audit entries')
ON CONFLICT(permission_code) DO NOTHING;

INSERT INTO role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM access_roles r JOIN permissions p ON
 (r.role_code = 'NAMED_AUTHORITY' AND p.permission_code IN ('OVERRIDE_APPROVE','POLICY_EXCEPTION_APPROVE','CASE_GOVERNANCE_AUDIT_VIEW')) OR
 (r.role_code IN ('MAKER','CHECKER','BANK_POLICY_OWNER') AND p.permission_code = 'CASE_GOVERNANCE_AUDIT_VIEW')
ON CONFLICT DO NOTHING;

CREATE TABLE case_audit_entries (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bank_id VARCHAR(100) NOT NULL,
    sequence_no BIGINT NOT NULL,
    actor_id VARCHAR(160) NOT NULL,
    actor_role VARCHAR(40) NOT NULL,
    action_code VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(160) NOT NULL,
    version_id UUID NULL,
    request_id UUID NULL,
    reason TEXT NULL,
    before_sha256 VARCHAR(64) NULL,
    after_sha256 VARCHAR(64) NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    previous_entry_sha256 VARCHAR(64) NOT NULL,
    entry_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_audit_sequence_positive CHECK (sequence_no > 0),
    CONSTRAINT ck_case_audit_actor_nonblank CHECK (length(trim(actor_id)) > 0),
    CONSTRAINT ck_case_audit_actor_role CHECK (actor_role IN ('MAKER','CHECKER','NAMED_AUTHORITY','BANK_POLICY_OWNER','LEGACY')),
    CONSTRAINT ck_case_audit_action_code CHECK (action_code ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    CONSTRAINT ck_case_audit_entity_reference CHECK (length(trim(entity_type)) > 0 AND length(trim(entity_id)) > 0),
    CONSTRAINT ck_case_audit_previous_hash CHECK (previous_entry_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_audit_entry_hash CHECK (entry_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_audit_before_hash CHECK (before_sha256 IS NULL OR before_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_audit_after_hash CHECK (after_sha256 IS NULL OR after_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_case_audit_case_sequence UNIQUE(case_id, sequence_no),
    CONSTRAINT fk_case_audit_version_case FOREIGN KEY(version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_audit_case_created ON case_audit_entries(case_id, created_at);
CREATE INDEX ix_case_audit_case_action ON case_audit_entries(case_id, action_code, sequence_no);

CREATE OR REPLACE FUNCTION enforce_case_audit_append()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_bank_id VARCHAR(100);
    v_latest_sequence BIGINT;
    v_latest_hash VARCHAR(64);
BEGIN
    SELECT bank_id INTO v_bank_id FROM cases WHERE id = NEW.case_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case not found for audit append' USING ERRCODE = '23503';
    END IF;
    IF NEW.bank_id IS DISTINCT FROM v_bank_id THEN
        RAISE EXCEPTION 'audit bank scope must match case' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_audit_bank_scope';
    END IF;
    SELECT sequence_no, entry_sha256 INTO v_latest_sequence, v_latest_hash
      FROM case_audit_entries WHERE case_id = NEW.case_id ORDER BY sequence_no DESC LIMIT 1;
    IF NEW.sequence_no <> COALESCE(v_latest_sequence, 0) + 1 THEN
        RAISE EXCEPTION 'audit sequence must increment by one' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_audit_sequential';
    END IF;
    IF NEW.previous_entry_sha256 IS DISTINCT FROM COALESCE(v_latest_hash, repeat('0', 64)) THEN
        RAISE EXCEPTION 'audit previous hash must reference the current case audit head'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_audit_previous_head';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_audit_append
    BEFORE INSERT ON case_audit_entries FOR EACH ROW EXECUTE FUNCTION enforce_case_audit_append();

CREATE TABLE case_override_requests (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    bank_id VARCHAR(100) NOT NULL,
    request_kind VARCHAR(24) NOT NULL,
    exception_code VARCHAR(80) NOT NULL,
    policy_reference VARCHAR(160) NOT NULL,
    policy_version VARCHAR(80) NOT NULL,
    requested_by VARCHAR(160) NOT NULL,
    reason TEXT NOT NULL,
    requested_change JSONB NOT NULL,
    impact_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL,
    version_sha256 VARCHAR(64) NOT NULL,
    proposal_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_override_request_kind CHECK (request_kind IN ('OVERRIDE','POLICY_EXCEPTION')),
    CONSTRAINT ck_case_override_exception_code CHECK (exception_code ~ '^[A-Z][A-Z0-9_]{1,79}$'),
    CONSTRAINT ck_case_override_policy_reference CHECK (length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0),
    CONSTRAINT ck_case_override_request_reason CHECK (length(trim(requested_by)) > 0 AND length(trim(reason)) >= 12),
    CONSTRAINT ck_case_override_change_object CHECK (jsonb_typeof(requested_change) = 'object' AND requested_change <> '{}'::jsonb),
    CONSTRAINT ck_case_override_impact_object CHECK (jsonb_typeof(impact_summary) = 'object'),
    CONSTRAINT ck_case_override_evidence_refs CHECK (CASE WHEN jsonb_typeof(evidence_refs) = 'array' THEN jsonb_array_length(evidence_refs) > 0 ELSE FALSE END),
    CONSTRAINT ck_case_override_version_hash CHECK (version_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_override_proposal_hash CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_case_override_request_id_case UNIQUE(id, case_id),
    CONSTRAINT uq_case_override_version_proposal UNIQUE(case_id, version_id, proposal_sha256),
    CONSTRAINT fk_case_override_request_version_case FOREIGN KEY(version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_override_case_created ON case_override_requests(case_id, created_at);
CREATE INDEX ix_case_override_version_created ON case_override_requests(version_id, created_at);

CREATE OR REPLACE FUNCTION validate_case_override_request()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_bank_id VARCHAR(100);
    v_created_by VARCHAR(160);
    v_version_hash VARCHAR(64);
    v_frozen BOOLEAN;
    v_returned BOOLEAN;
    v_superseded BOOLEAN;
BEGIN
    SELECT bank_id INTO v_bank_id FROM cases WHERE id = NEW.case_id FOR UPDATE;
    IF NOT FOUND OR NEW.bank_id IS DISTINCT FROM v_bank_id THEN
        RAISE EXCEPTION 'override request case/bank scope mismatch' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_bank_scope';
    END IF;
    SELECT created_by, snapshot_sha256 INTO v_created_by, v_version_hash
      FROM case_analysis_versions WHERE id = NEW.version_id AND case_id = NEW.case_id;
    IF NOT FOUND OR NEW.requested_by IS DISTINCT FROM v_created_by OR NEW.version_sha256 IS DISTINCT FROM v_version_hash THEN
        RAISE EXCEPTION 'only the Maker may propose against the exact linked version hash'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_maker_version';
    END IF;
    SELECT EXISTS(SELECT 1 FROM case_governance_events WHERE version_id = NEW.version_id AND event_type = 'FROZEN'),
           EXISTS(SELECT 1 FROM case_governance_events WHERE version_id = NEW.version_id AND event_type = 'RETURNED_TO_MAKER'),
           EXISTS(SELECT 1 FROM case_governance_events WHERE version_id = NEW.version_id AND event_type = 'VERSION_SUPERSEDED')
      INTO v_frozen, v_returned, v_superseded;
    IF NOT v_frozen OR v_returned OR v_superseded THEN
        RAISE EXCEPTION 'override request requires a current frozen version'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_version_state';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_override_request_validate
    BEFORE INSERT ON case_override_requests FOR EACH ROW EXECUTE FUNCTION validate_case_override_request();

-- Evidence references are database-validated as well as application-validated;
-- they must resolve to records owned by this same case.
CREATE OR REPLACE FUNCTION validate_case_override_evidence_refs()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_ref_text TEXT;
    v_ref UUID;
    v_found BOOLEAN;
BEGIN
    FOR v_ref_text IN SELECT jsonb_array_elements_text(NEW.evidence_refs)
    LOOP
        BEGIN
            v_ref := v_ref_text::UUID;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'override evidence reference is not a UUID'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_evidence_uuid';
        END;
        SELECT (
            EXISTS(SELECT 1 FROM documents WHERE id = v_ref AND case_id = NEW.case_id) OR
            EXISTS(SELECT 1 FROM transactions WHERE id = v_ref AND case_id = NEW.case_id) OR
            EXISTS(SELECT 1 FROM evidence_manifest_entries WHERE id = v_ref AND case_id = NEW.case_id) OR
            EXISTS(SELECT 1 FROM evidence_reconciliation_runs WHERE id = v_ref AND case_id = NEW.case_id) OR
            EXISTS(SELECT 1 FROM transaction_duplicate_candidates WHERE id = v_ref AND case_id = NEW.case_id) OR
            EXISTS(SELECT 1 FROM evidence_review_decisions WHERE id = v_ref AND case_id = NEW.case_id) OR
            EXISTS(SELECT 1 FROM extracted_fields ef JOIN documents d ON d.id = ef.document_id
                    WHERE ef.id = v_ref AND d.case_id = NEW.case_id)
        ) INTO v_found;
        IF NOT v_found THEN
            RAISE EXCEPTION 'override evidence reference is unknown or belongs to another case'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_evidence_same_case';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_override_evidence_same_case
    BEFORE INSERT ON case_override_requests FOR EACH ROW EXECUTE FUNCTION validate_case_override_evidence_refs();

CREATE TABLE case_override_events (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    request_id UUID NOT NULL,
    event_type VARCHAR(20) NOT NULL,
    actor_id VARCHAR(160) NOT NULL,
    actor_role VARCHAR(40) NOT NULL,
    reason TEXT NOT NULL,
    authority_grant_ref VARCHAR(160) NULL,
    authority_scope_ref VARCHAR(160) NULL,
    valid_until TIMESTAMPTZ NULL,
    proposal_sha256 VARCHAR(64) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_override_event_type CHECK (event_type IN ('REQUESTED','APPROVED','REJECTED','WITHDRAWN')),
    CONSTRAINT ck_case_override_event_role CHECK (
        (event_type IN ('REQUESTED','WITHDRAWN') AND actor_role = 'MAKER') OR
        (event_type IN ('APPROVED','REJECTED') AND actor_role = 'NAMED_AUTHORITY')),
    CONSTRAINT ck_case_override_event_reason CHECK (length(trim(actor_id)) > 0 AND length(trim(reason)) >= 12),
    CONSTRAINT ck_case_override_event_hash CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_override_authority_refs CHECK (event_type NOT IN ('APPROVED','REJECTED') OR
        (authority_grant_ref IS NOT NULL AND length(trim(authority_grant_ref)) > 0 AND
         authority_scope_ref IS NOT NULL AND length(trim(authority_scope_ref)) > 0)),
    CONSTRAINT ck_case_override_valid_until CHECK
        ((event_type = 'APPROVED' AND valid_until IS NOT NULL) OR (event_type <> 'APPROVED' AND valid_until IS NULL)),
    CONSTRAINT fk_case_override_event_request_case FOREIGN KEY(request_id, case_id)
        REFERENCES case_override_requests(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_override_event_request_created ON case_override_events(request_id, created_at);
CREATE UNIQUE INDEX uq_case_override_requested_per_request
    ON case_override_events(request_id) WHERE event_type = 'REQUESTED';
CREATE UNIQUE INDEX uq_case_override_terminal_per_request
    ON case_override_events(request_id) WHERE event_type IN ('APPROVED','REJECTED','WITHDRAWN');

CREATE OR REPLACE FUNCTION validate_case_override_event()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_requested_by VARCHAR(160);
    v_version_id UUID;
    v_proposal_sha256 VARCHAR(64);
    v_checker_id VARCHAR(160);
    v_has_request BOOLEAN;
    v_has_terminal BOOLEAN;
    v_has_checker_confirmation BOOLEAN;
BEGIN
    PERFORM 1 FROM cases WHERE id = NEW.case_id FOR UPDATE;
    SELECT requested_by, version_id, proposal_sha256
      INTO v_requested_by, v_version_id, v_proposal_sha256
      FROM case_override_requests WHERE id = NEW.request_id AND case_id = NEW.case_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'override request not found in case' USING ERRCODE = '23503';
    END IF;
    IF NEW.proposal_sha256 IS DISTINCT FROM v_proposal_sha256 THEN
        RAISE EXCEPTION 'override event must bind to the exact Maker proposal hash'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_event_proposal_hash';
    END IF;
    SELECT EXISTS(SELECT 1 FROM case_override_events WHERE request_id = NEW.request_id AND event_type = 'REQUESTED'),
           EXISTS(SELECT 1 FROM case_override_events WHERE request_id = NEW.request_id AND event_type IN ('APPROVED','REJECTED','WITHDRAWN'))
      INTO v_has_request, v_has_terminal;

    IF NEW.event_type = 'REQUESTED' THEN
        IF NEW.actor_role <> 'MAKER' OR NEW.actor_id IS DISTINCT FROM v_requested_by OR v_has_request THEN
            RAISE EXCEPTION 'REQUESTED must be appended once by the proposing Maker'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_requested_actor';
        END IF;
    ELSE
        IF NOT v_has_request OR v_has_terminal THEN
            RAISE EXCEPTION 'override event requires one open request and no prior terminal decision'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_event_transition';
        END IF;
        IF NEW.event_type IN ('APPROVED','REJECTED') THEN
            SELECT actor_id INTO v_checker_id FROM case_governance_events
             WHERE version_id = v_version_id AND event_type = 'CHECKER_CONFIRMED' LIMIT 1;
            v_has_checker_confirmation := FOUND;
            IF NEW.actor_role <> 'NAMED_AUTHORITY' OR NEW.actor_id IN (v_requested_by, v_checker_id)
               OR NOT v_has_checker_confirmation THEN
                RAISE EXCEPTION 'Named Authority must be independent and version must be Checker-confirmed'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_authority_independence';
            END IF;
            IF NEW.event_type = 'APPROVED' AND NEW.valid_until <= CURRENT_TIMESTAMP THEN
                RAISE EXCEPTION 'authority approval must not already be expired'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_approval_expiry';
            END IF;
        ELSIF NEW.event_type = 'WITHDRAWN' THEN
            IF NEW.actor_role <> 'MAKER' OR NEW.actor_id IS DISTINCT FROM v_requested_by THEN
                RAISE EXCEPTION 'only the proposing Maker may withdraw a pending request'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_case_override_withdraw_actor';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_override_event_validate
    BEFORE INSERT ON case_override_events FOR EACH ROW EXECUTE FUNCTION validate_case_override_event();

CREATE OR REPLACE FUNCTION reject_case_v15_ledger_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; corrections require a new version/event', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;
CREATE TRIGGER trg_case_audit_entry_immutable
    BEFORE UPDATE OR DELETE ON case_audit_entries FOR EACH ROW EXECUTE FUNCTION reject_case_v15_ledger_mutation();
CREATE TRIGGER trg_case_override_request_immutable
    BEFORE UPDATE OR DELETE ON case_override_requests FOR EACH ROW EXECUTE FUNCTION reject_case_v15_ledger_mutation();
CREATE TRIGGER trg_case_override_event_immutable
    BEFORE UPDATE OR DELETE ON case_override_events FOR EACH ROW EXECUTE FUNCTION reject_case_v15_ledger_mutation();

COMMENT ON TABLE case_audit_entries IS 'Append-only case-scoped hash chain. Hash verification detects payload/ordering tampering; no external signature anchor is claimed.';
COMMENT ON TABLE case_override_requests IS 'Immutable Maker proposal bound to one V14 snapshot hash and same-case evidence references. Not executed by DATA-AI.';
COMMENT ON TABLE case_override_events IS 'Append-only Maker/Named Authority decisions. Named Authority grant/scope must be validated by Backend/SSO.';
