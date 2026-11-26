-- V16: Camunda 8 correlation boundary, transactional outbox/inbox,
-- Awaiting Evidence/resubmission, governed reopen, G3/G4 and hashed export packages.
-- Camunda owns BPMN tasks/timers. Backend/SSO owns identity/assignment/grants.
-- DATA-AI records evidence/workflow correlation; it does not make credit decisions.
SET search_path TO data_ai;

INSERT INTO access_roles(id, role_code, role_name, description) VALUES
 ('a0000000-0000-4000-8000-000000000010','WORKFLOW_ORCHESTRATOR','Workflow Orchestrator','Dedicated signed service identity for Camunda workflow callbacks and outbox delivery; no human task permissions'),
 ('a0000000-0000-4000-8000-000000000011','RELEASE_AUTHORITY','Release Authority','Backend/SSO-validated release authority for recording G4 Operational gate references'),
 ('a0000000-0000-4000-8000-000000000012','BUSINESS_ENGINE','Business Engine','Dedicated signed service identity that records external policy/override application receipts')
ON CONFLICT(role_code) DO NOTHING;

INSERT INTO permissions(id, permission_code, resource, action, description) VALUES
 ('b0000000-0000-4000-8000-000000000018','WORKFLOW_BINDING_MANAGE','WORKFLOW_BINDING','MANAGE','Register and inspect Camunda process correlation for a bank-scoped case'),
 ('b0000000-0000-4000-8000-000000000019','WORKFLOW_EVENT_RECEIVE','WORKFLOW_EVENT','RECEIVE','Receive idempotent Camunda callbacks and process-sequence events'),
 ('b0000000-0000-4000-8000-000000000020','WORKFLOW_OUTBOX_DELIVER','WORKFLOW_OUTBOX','DELIVER','Claim and acknowledge transactional outbox messages for Camunda/Backend delivery'),
 ('b0000000-0000-4000-8000-000000000021','CASE_EVIDENCE_REQUEST','CASE_EVIDENCE','REQUEST','Request missing evidence and record controlled evidence resubmission'),
 ('b0000000-0000-4000-8000-000000000022','CASE_WORKFLOW_REOPEN','CASE_WORKFLOW','REOPEN','Reopen a confirmed evidence snapshot after a governed policy/product/evidence change'),
 ('b0000000-0000-4000-8000-000000000023','CASE_RELEASE_GATE_RECORD','CASE_RELEASE_GATE','RECORD','Record externally validated G3/G4 release gate references'),
 ('b0000000-0000-4000-8000-000000000024','CASE_EXPORT_PACKAGE_CREATE','CASE_EXPORT_PACKAGE','CREATE','Generate a hashed JSON/CSV/PDF DATA-AI evidence package'),
 ('b0000000-0000-4000-8000-000000000025','OVERRIDE_APPLICATION_RECEIPT_WRITE','OVERRIDE_APPLICATION_RECEIPT','WRITE','Record Business Engine proof that a Named Authority-approved override was applied externally')
ON CONFLICT(permission_code) DO NOTHING;

INSERT INTO role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM access_roles r JOIN permissions p ON
    (r.role_code = 'WORKFLOW_ORCHESTRATOR' AND p.permission_code IN
        ('WORKFLOW_BINDING_MANAGE','WORKFLOW_EVENT_RECEIVE','WORKFLOW_OUTBOX_DELIVER')) OR
    (r.role_code = 'RELEASE_AUTHORITY' AND p.permission_code = 'CASE_RELEASE_GATE_RECORD') OR
    (r.role_code = 'BUSINESS_ENGINE' AND p.permission_code = 'OVERRIDE_APPLICATION_RECEIPT_WRITE') OR
    (r.role_code IN ('MAKER','CHECKER') AND p.permission_code IN
        ('CASE_EVIDENCE_REQUEST','CASE_WORKFLOW_REOPEN','CASE_EXPORT_PACKAGE_CREATE')) OR
    (r.role_code = 'BANK_POLICY_OWNER' AND p.permission_code IN
        ('CASE_WORKFLOW_REOPEN','CASE_RELEASE_GATE_RECORD','CASE_EXPORT_PACKAGE_CREATE'))
ON CONFLICT DO NOTHING;

ALTER TABLE case_audit_entries DROP CONSTRAINT IF EXISTS ck_case_audit_actor_role;
ALTER TABLE case_audit_entries ADD CONSTRAINT ck_case_audit_actor_role
    CHECK (actor_role IN ('MAKER','CHECKER','NAMED_AUTHORITY','BANK_POLICY_OWNER','BUSINESS_ENGINE','LEGACY'));

CREATE TABLE case_workflow_bindings (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bank_id VARCHAR(100) NOT NULL,
    engine_name VARCHAR(32) NOT NULL DEFAULT 'CAMUNDA_8',
    process_definition_key VARCHAR(160) NOT NULL,
    process_instance_id VARCHAR(160) NOT NULL UNIQUE,
    business_key VARCHAR(160) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_workflow_binding_engine CHECK (engine_name = 'CAMUNDA_8'),
    CONSTRAINT ck_workflow_binding_status CHECK (status IN ('ACTIVE','COMPLETED','CANCELLED')),
    CONSTRAINT ck_workflow_binding_identifiers CHECK (length(trim(process_definition_key)) > 0 AND length(trim(process_instance_id)) > 0 AND length(trim(business_key)) > 0),
    CONSTRAINT uq_workflow_binding_id_case UNIQUE(id, case_id)
);
CREATE UNIQUE INDEX uq_workflow_binding_active_case ON case_workflow_bindings(case_id) WHERE status = 'ACTIVE';
CREATE INDEX ix_workflow_binding_case_created ON case_workflow_bindings(case_id, created_at);

CREATE TABLE workflow_outbox_events (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    binding_id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    correlation_id UUID NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_until TIMESTAMPTZ NULL,
    claimed_by VARCHAR(120) NULL,
    delivered_at TIMESTAMPTZ NULL,
    last_error_code VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_workflow_outbox_event_type CHECK (event_type ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    CONSTRAINT ck_workflow_outbox_status CHECK (status IN ('PENDING','IN_FLIGHT','DELIVERED','DEAD_LETTER')),
    CONSTRAINT ck_workflow_outbox_attempts CHECK (attempts BETWEEN 0 AND 8),
    CONSTRAINT ck_workflow_outbox_lease_state CHECK
       ((status = 'IN_FLIGHT' AND claimed_by IS NOT NULL AND locked_until IS NOT NULL) OR
        (status IN ('PENDING','DELIVERED','DEAD_LETTER') AND claimed_by IS NULL AND locked_until IS NULL)),
    CONSTRAINT ck_workflow_outbox_payload_hash CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_workflow_outbox_idem_key CHECK (length(trim(idempotency_key)) >= 8),
    CONSTRAINT ck_workflow_outbox_delivered_at CHECK ((status = 'DELIVERED' AND delivered_at IS NOT NULL) OR status <> 'DELIVERED'),
    CONSTRAINT uq_workflow_outbox_case_idem UNIQUE(case_id, idempotency_key),
    CONSTRAINT fk_workflow_outbox_binding_case FOREIGN KEY(binding_id, case_id)
        REFERENCES case_workflow_bindings(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_workflow_outbox_claim ON workflow_outbox_events(status, available_at, created_at);
CREATE INDEX ix_workflow_outbox_case_created ON workflow_outbox_events(case_id, created_at);

CREATE TABLE workflow_inbox_events (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    binding_id UUID NOT NULL,
    external_event_id VARCHAR(160) NOT NULL UNIQUE,
    process_sequence BIGINT NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_sha256 VARCHAR(64) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_workflow_inbox_sequence CHECK (process_sequence > 0),
    CONSTRAINT ck_workflow_inbox_event_type CHECK (event_type ~ '^[A-Z][A-Z0-9_]{2,63}$'),
    CONSTRAINT ck_workflow_inbox_payload_hash CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_workflow_inbox_binding_sequence UNIQUE(binding_id, process_sequence),
    CONSTRAINT fk_workflow_inbox_binding_case FOREIGN KEY(binding_id, case_id)
        REFERENCES case_workflow_bindings(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_workflow_inbox_case_received ON workflow_inbox_events(case_id, received_at);

CREATE TABLE case_evidence_requests (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    bank_id VARCHAR(100) NOT NULL,
    binding_id UUID NOT NULL,
    request_no INTEGER NOT NULL,
    required_item_codes JSONB NOT NULL,
    reason TEXT NOT NULL,
    requested_by VARCHAR(160) NOT NULL,
    based_on_version_id UUID NULL,
    due_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'AWAITING_EVIDENCE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_case_evidence_request_no CHECK (request_no > 0),
    CONSTRAINT ck_case_evidence_required_items CHECK (jsonb_typeof(required_item_codes) = 'array' AND jsonb_array_length(required_item_codes) > 0),
    CONSTRAINT ck_case_evidence_request_reason CHECK (length(trim(reason)) >= 12 AND length(trim(requested_by)) > 0),
    CONSTRAINT ck_case_evidence_request_status CHECK (status IN ('AWAITING_EVIDENCE','RECEIVED','EXPIRED','CANCELLED')),
    CONSTRAINT ck_case_evidence_request_resolution CHECK
       ((status = 'AWAITING_EVIDENCE' AND resolved_at IS NULL) OR
        (status IN ('RECEIVED','EXPIRED','CANCELLED') AND resolved_at IS NOT NULL)),
    CONSTRAINT uq_case_evidence_request_no UNIQUE(case_id, request_no),
    CONSTRAINT uq_case_evidence_request_id_case UNIQUE(id, case_id),
    CONSTRAINT fk_case_evidence_request_binding_case FOREIGN KEY(binding_id, case_id)
        REFERENCES case_workflow_bindings(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_case_evidence_request_version_case FOREIGN KEY(based_on_version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_evidence_request_case_status ON case_evidence_requests(case_id, status, created_at);

CREATE TABLE case_resubmissions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    evidence_request_id UUID NOT NULL,
    based_on_version_id UUID NULL,
    received_document_ids JSONB NOT NULL,
    impact_list JSONB NOT NULL,
    impact_sha256 VARCHAR(64) NOT NULL,
    requested_new_version_no INTEGER NOT NULL,
    created_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_resubmission_documents CHECK (jsonb_typeof(received_document_ids) = 'array' AND jsonb_array_length(received_document_ids) > 0),
    CONSTRAINT ck_case_resubmission_impact_object CHECK (jsonb_typeof(impact_list) = 'object'),
    CONSTRAINT ck_case_resubmission_impact_hash CHECK (impact_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_resubmission_next_version CHECK (requested_new_version_no > 0 AND length(trim(created_by)) > 0),
    CONSTRAINT uq_case_resubmission_request UNIQUE(evidence_request_id),
    CONSTRAINT fk_case_resubmission_request_case FOREIGN KEY(evidence_request_id, case_id)
        REFERENCES case_evidence_requests(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_case_resubmission_version_case FOREIGN KEY(based_on_version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_resubmission_case_created ON case_resubmissions(case_id, created_at);

CREATE TABLE case_workflow_reopens (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    based_on_version_id UUID NOT NULL,
    new_version_id UUID NULL,
    reason_code VARCHAR(40) NOT NULL,
    reason TEXT NOT NULL,
    policy_reference VARCHAR(160) NULL,
    policy_version VARCHAR(80) NULL,
    product_code VARCHAR(100) NULL,
    product_version VARCHAR(80) NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    requested_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    consumed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_case_workflow_reopen_reason_code CHECK (reason_code IN ('EVIDENCE_UPDATED','POLICY_VERSION_CHANGED','PRODUCT_VERSION_CHANGED','EXTERNAL_REVIEW_REOPEN')),
    CONSTRAINT ck_case_workflow_reopen_status CHECK (status IN ('OPEN','CONSUMED','CANCELLED')),
    CONSTRAINT ck_case_workflow_reopen_completion CHECK
       ((status = 'OPEN' AND new_version_id IS NULL AND consumed_at IS NULL) OR
        (status = 'CONSUMED' AND new_version_id IS NOT NULL AND consumed_at IS NOT NULL) OR
        (status = 'CANCELLED' AND new_version_id IS NULL AND consumed_at IS NULL)),
    CONSTRAINT ck_case_workflow_reopen_reason CHECK (length(trim(reason)) >= 12 AND length(trim(requested_by)) > 0),
    CONSTRAINT ck_case_workflow_reopen_external_version CHECK
       ((reason_code <> 'POLICY_VERSION_CHANGED' OR (policy_reference IS NOT NULL AND policy_version IS NOT NULL)) AND
        (reason_code <> 'PRODUCT_VERSION_CHANGED' OR (product_code IS NOT NULL AND product_version IS NOT NULL))),
    CONSTRAINT fk_case_workflow_reopen_base_version_case FOREIGN KEY(based_on_version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_case_workflow_reopen_new_version_case FOREIGN KEY(new_version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX uq_case_workflow_reopen_open_case ON case_workflow_reopens(case_id) WHERE status = 'OPEN';
CREATE INDEX ix_case_workflow_reopen_case_created ON case_workflow_reopens(case_id, created_at);

CREATE TABLE case_workflow_release_gates (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    gate_code VARCHAR(24) NOT NULL,
    actor_id VARCHAR(160) NOT NULL,
    actor_role VARCHAR(40) NOT NULL,
    external_gate_reference VARCHAR(160) NOT NULL,
    product_code VARCHAR(100) NOT NULL,
    product_version VARCHAR(80) NOT NULL,
    policy_reference VARCHAR(160) NOT NULL,
    policy_version VARCHAR(80) NOT NULL,
    snapshot_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_workflow_release_gate_code CHECK (gate_code IN ('G3_SHADOW','G4_OPERATIONAL')),
    CONSTRAINT ck_case_workflow_release_gate_actor_ref CHECK (length(trim(actor_id)) > 0 AND length(trim(external_gate_reference)) > 0),
    CONSTRAINT ck_case_workflow_release_gate_versions CHECK (length(trim(product_code)) > 0 AND length(trim(product_version)) > 0 AND length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0),
    CONSTRAINT ck_case_workflow_release_gate_hash CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_workflow_release_actor_role CHECK
       ((gate_code = 'G3_SHADOW' AND actor_role IN ('BANK_POLICY_OWNER','RELEASE_AUTHORITY')) OR
        (gate_code = 'G4_OPERATIONAL' AND actor_role = 'RELEASE_AUTHORITY')),
    CONSTRAINT uq_case_workflow_release_gate_version UNIQUE(case_id, version_id, gate_code),
    CONSTRAINT fk_case_workflow_release_gate_version_case FOREIGN KEY(version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_workflow_release_case_created ON case_workflow_release_gates(case_id, created_at);

CREATE TABLE case_workflow_export_packages (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    package_kind VARCHAR(32) NOT NULL DEFAULT 'DATA_AI_EVIDENCE_PACKAGE',
    package_path TEXT NOT NULL,
    package_sha256 VARCHAR(64) NOT NULL,
    package_manifest JSONB NOT NULL,
    snapshot_sha256 VARCHAR(64) NOT NULL,
    requested_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_workflow_export_kind CHECK (package_kind = 'DATA_AI_EVIDENCE_PACKAGE'),
    CONSTRAINT ck_case_workflow_export_hashes CHECK (package_sha256 ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_workflow_export_path_actor CHECK (length(trim(package_path)) > 0 AND length(trim(requested_by)) > 0),
    CONSTRAINT fk_case_workflow_export_version_case FOREIGN KEY(version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_workflow_export_case_created ON case_workflow_export_packages(case_id, created_at);

CREATE TABLE case_override_application_receipts (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    request_id UUID NOT NULL,
    bank_id VARCHAR(100) NOT NULL,
    external_application_reference VARCHAR(160) NOT NULL UNIQUE,
    applied_proposal_sha256 VARCHAR(64) NOT NULL,
    applied_version_sha256 VARCHAR(64) NOT NULL,
    policy_reference VARCHAR(160) NOT NULL,
    policy_version VARCHAR(80) NOT NULL,
    applied_by VARCHAR(160) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_override_application_receipt_hashes CHECK (applied_proposal_sha256 ~ '^[0-9a-f]{64}$' AND applied_version_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_override_application_receipt_actor_ref CHECK (length(trim(external_application_reference)) > 0 AND length(trim(applied_by)) > 0),
    CONSTRAINT ck_override_application_receipt_policy CHECK (length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0),
    CONSTRAINT uq_override_application_receipt_request UNIQUE(request_id),
    CONSTRAINT fk_override_application_receipt_request_case FOREIGN KEY(request_id, case_id)
        REFERENCES case_override_requests(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_override_application_receipt_case_received ON case_override_application_receipts(case_id, received_at);

CREATE OR REPLACE FUNCTION validate_override_application_receipt()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_bank_id VARCHAR(100);
    v_proposal_sha256 VARCHAR(64);
    v_snapshot_sha256 VARCHAR(64);
    v_policy_reference VARCHAR(160);
    v_policy_version VARCHAR(80);
    v_valid_until TIMESTAMPTZ;
BEGIN
    SELECT r.bank_id, r.proposal_sha256, v.snapshot_sha256, r.policy_reference, r.policy_version
      INTO v_bank_id, v_proposal_sha256, v_snapshot_sha256, v_policy_reference, v_policy_version
      FROM case_override_requests r
      JOIN case_analysis_versions v ON v.id = r.version_id AND v.case_id = r.case_id
     WHERE r.id = NEW.request_id AND r.case_id = NEW.case_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'override application receipt request/version not found' USING ERRCODE = '23503';
    END IF;
    IF NEW.bank_id IS DISTINCT FROM v_bank_id OR
       NEW.applied_proposal_sha256 IS DISTINCT FROM v_proposal_sha256 OR
       NEW.applied_version_sha256 IS DISTINCT FROM v_snapshot_sha256 OR
       NEW.policy_reference IS DISTINCT FROM v_policy_reference OR
       NEW.policy_version IS DISTINCT FROM v_policy_version THEN
        RAISE EXCEPTION 'override application receipt does not match case/proposal/version/policy' USING ERRCODE = '23514';
    END IF;
    SELECT valid_until INTO v_valid_until FROM case_override_events
     WHERE request_id = NEW.request_id AND case_id = NEW.case_id
       AND event_type = 'APPROVED' AND proposal_sha256 = v_proposal_sha256;
    IF NOT FOUND OR v_valid_until <= CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'override application receipt requires an active matching Named Authority approval' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_override_application_receipt_validate BEFORE INSERT ON case_override_application_receipts
    FOR EACH ROW EXECUTE FUNCTION validate_override_application_receipt();

-- Camunda callbacks are append-only. Outbox data payload/hash is immutable while delivery metadata is mutable.
CREATE OR REPLACE FUNCTION reject_workflow_history_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'workflow history table % is append-only', TG_TABLE_NAME
        USING ERRCODE = '55000', CONSTRAINT = 'ck_workflow_history_append_only';
END;
$$;
CREATE TRIGGER trg_workflow_inbox_append_only BEFORE UPDATE OR DELETE ON workflow_inbox_events
    FOR EACH ROW EXECUTE FUNCTION reject_workflow_history_mutation();
CREATE TRIGGER trg_case_resubmission_append_only BEFORE UPDATE OR DELETE ON case_resubmissions
    FOR EACH ROW EXECUTE FUNCTION reject_workflow_history_mutation();
CREATE TRIGGER trg_case_release_gate_append_only BEFORE UPDATE OR DELETE ON case_workflow_release_gates
    FOR EACH ROW EXECUTE FUNCTION reject_workflow_history_mutation();
CREATE TRIGGER trg_case_export_package_append_only BEFORE UPDATE OR DELETE ON case_workflow_export_packages
    FOR EACH ROW EXECUTE FUNCTION reject_workflow_history_mutation();
CREATE TRIGGER trg_override_application_receipt_append_only BEFORE UPDATE OR DELETE ON case_override_application_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_workflow_history_mutation();

CREATE OR REPLACE FUNCTION guard_workflow_binding_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workflow bindings cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF ROW(NEW.id, NEW.case_id, NEW.bank_id, NEW.engine_name, NEW.process_definition_key,
           NEW.process_instance_id, NEW.business_key, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id, OLD.case_id, OLD.bank_id, OLD.engine_name, OLD.process_definition_key,
           OLD.process_instance_id, OLD.business_key, OLD.created_at) THEN
        RAISE EXCEPTION 'workflow binding correlation fields are immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'ACTIVE' AND NEW.status IN ('COMPLETED','CANCELLED')) THEN
        RAISE EXCEPTION 'invalid workflow binding state transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_workflow_binding_guard BEFORE UPDATE OR DELETE ON case_workflow_bindings
    FOR EACH ROW EXECUTE FUNCTION guard_workflow_binding_mutation();

CREATE OR REPLACE FUNCTION guard_workflow_outbox_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workflow outbox rows cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF ROW(NEW.id, NEW.case_id, NEW.binding_id, NEW.event_type, NEW.idempotency_key,
           NEW.correlation_id, NEW.payload, NEW.payload_sha256, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id, OLD.case_id, OLD.binding_id, OLD.event_type, OLD.idempotency_key,
           OLD.correlation_id, OLD.payload, OLD.payload_sha256, OLD.created_at) THEN
        RAISE EXCEPTION 'workflow outbox event content is immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'PENDING' AND NEW.status = 'IN_FLIGHT') OR
        (OLD.status = 'PENDING' AND NEW.status = 'DEAD_LETTER' AND NEW.attempts >= 8) OR
        (OLD.status = 'IN_FLIGHT' AND NEW.status IN ('IN_FLIGHT','DELIVERED','PENDING','DEAD_LETTER'))
    ) THEN
        RAISE EXCEPTION 'invalid workflow outbox state transition' USING ERRCODE = '23514';
    END IF;
    IF NEW.attempts < OLD.attempts OR NEW.attempts > OLD.attempts + 1 THEN
        RAISE EXCEPTION 'workflow outbox attempt counter must increase by at most one' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_workflow_outbox_guard BEFORE UPDATE OR DELETE ON workflow_outbox_events
    FOR EACH ROW EXECUTE FUNCTION guard_workflow_outbox_mutation();

CREATE OR REPLACE FUNCTION guard_case_evidence_request_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'evidence requests cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF ROW(NEW.id, NEW.case_id, NEW.bank_id, NEW.binding_id, NEW.request_no, NEW.required_item_codes,
           NEW.reason, NEW.requested_by, NEW.based_on_version_id, NEW.due_at, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id, OLD.case_id, OLD.bank_id, OLD.binding_id, OLD.request_no, OLD.required_item_codes,
           OLD.reason, OLD.requested_by, OLD.based_on_version_id, OLD.due_at, OLD.created_at) THEN
        RAISE EXCEPTION 'evidence request details are immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT
       (OLD.status = 'AWAITING_EVIDENCE' AND NEW.status IN ('RECEIVED','EXPIRED','CANCELLED')) THEN
        RAISE EXCEPTION 'invalid evidence request state transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_evidence_request_guard BEFORE UPDATE OR DELETE ON case_evidence_requests
    FOR EACH ROW EXECUTE FUNCTION guard_case_evidence_request_mutation();

CREATE OR REPLACE FUNCTION guard_case_workflow_reopen_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workflow reopen records cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF ROW(NEW.id, NEW.case_id, NEW.based_on_version_id, NEW.reason_code, NEW.reason,
           NEW.policy_reference, NEW.policy_version, NEW.product_code, NEW.product_version,
           NEW.evidence_refs, NEW.requested_by, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id, OLD.case_id, OLD.based_on_version_id, OLD.reason_code, OLD.reason,
           OLD.policy_reference, OLD.policy_version, OLD.product_code, OLD.product_version,
           OLD.evidence_refs, OLD.requested_by, OLD.created_at) THEN
        RAISE EXCEPTION 'workflow reopen decision details are immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'OPEN' AND NEW.status IN ('CONSUMED','CANCELLED')) THEN
        RAISE EXCEPTION 'invalid workflow reopen state transition' USING ERRCODE = '23514';
    END IF;
    IF NEW.new_version_id IS DISTINCT FROM OLD.new_version_id AND NOT
       (OLD.status = 'OPEN' AND NEW.status = 'CONSUMED' AND NEW.new_version_id IS NOT NULL) THEN
        RAISE EXCEPTION 'reopen may only link its consumed successor version' USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'CONSUMED' AND NOT EXISTS (
        SELECT 1 FROM case_analysis_versions v
         WHERE v.id = NEW.new_version_id AND v.case_id = OLD.case_id
           AND v.based_on_version_id = OLD.based_on_version_id
    ) THEN
        RAISE EXCEPTION 'consumed reopen must link a direct successor of its based-on version' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_workflow_reopen_guard BEFORE UPDATE OR DELETE ON case_workflow_reopens
    FOR EACH ROW EXECUTE FUNCTION guard_case_workflow_reopen_mutation();

CREATE OR REPLACE FUNCTION validate_case_workflow_reopen_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_latest_version_id UUID;
    v_checker_confirmed BOOLEAN;
    v_returned BOOLEAN;
BEGIN
    PERFORM 1 FROM cases WHERE id = NEW.case_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case not found for workflow reopen' USING ERRCODE = '23503';
    END IF;
    SELECT id INTO v_latest_version_id FROM case_analysis_versions
     WHERE case_id = NEW.case_id ORDER BY version_no DESC LIMIT 1;
    IF v_latest_version_id IS NULL OR NEW.based_on_version_id IS DISTINCT FROM v_latest_version_id THEN
        RAISE EXCEPTION 'workflow reopen must reference the latest analysis version' USING ERRCODE = '23514';
    END IF;
    SELECT EXISTS(SELECT 1 FROM case_governance_events WHERE version_id = v_latest_version_id AND event_type = 'CHECKER_CONFIRMED'),
           EXISTS(SELECT 1 FROM case_governance_events WHERE version_id = v_latest_version_id AND event_type = 'RETURNED_TO_MAKER')
      INTO v_checker_confirmed, v_returned;
    IF NOT v_checker_confirmed OR v_returned THEN
        RAISE EXCEPTION 'workflow reopen requires a currently Checker-confirmed version' USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> 'OPEN' OR NEW.new_version_id IS NOT NULL OR NEW.consumed_at IS NOT NULL THEN
        RAISE EXCEPTION 'workflow reopen must start in OPEN state without successor link' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_workflow_reopen_insert_validate BEFORE INSERT ON case_workflow_reopens
    FOR EACH ROW EXECUTE FUNCTION validate_case_workflow_reopen_insert();

-- Extend the V14 immutable-version sequence gate: a new version may follow a
-- Checker-confirmed version only when an explicit OPEN reopen record exists.
CREATE OR REPLACE FUNCTION enforce_case_analysis_version_sequence()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_latest_id UUID;
    v_latest_no INTEGER;
    v_returned BOOLEAN;
    v_reopen BOOLEAN;
BEGIN
    PERFORM 1 FROM cases WHERE id = NEW.case_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case not found for analysis version' USING ERRCODE = '23503';
    END IF;
    SELECT id, version_no INTO v_latest_id, v_latest_no
      FROM case_analysis_versions WHERE case_id = NEW.case_id ORDER BY version_no DESC LIMIT 1;
    IF COALESCE(v_latest_no, 0) + 1 <> NEW.version_no THEN
        RAISE EXCEPTION 'analysis version must increment sequentially' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_sequential';
    END IF;
    IF NEW.based_on_version_id IS DISTINCT FROM v_latest_id THEN
        RAISE EXCEPTION 'analysis version parent must reference latest version' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_parent_latest';
    END IF;
    IF v_latest_id IS NOT NULL THEN
        SELECT EXISTS (SELECT 1 FROM case_governance_events WHERE version_id = v_latest_id AND event_type = 'RETURNED_TO_MAKER') INTO v_returned;
        SELECT EXISTS (SELECT 1 FROM case_workflow_reopens WHERE case_id = NEW.case_id AND based_on_version_id = v_latest_id AND status = 'OPEN') INTO v_reopen;
        IF NOT v_returned AND NOT v_reopen THEN
            RAISE EXCEPTION 'a new version requires Checker return or an explicit open workflow reopen' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_requires_return_or_reopen';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- Extend V14 DB-level input freeze so a governed OPEN reopen is the only extra
-- route (besides Checker RETURN) that permits evidence/source changes.
CREATE OR REPLACE FUNCTION guard_case_data_when_frozen()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_case_id UUID;
    v_document_id UUID;
    v_latest_version_id UUID;
    v_is_frozen BOOLEAN;
BEGIN
    IF TG_TABLE_NAME = 'cases' AND TG_OP = 'INSERT' THEN
        RETURN NEW;
    ELSIF TG_TABLE_NAME = 'cases' THEN
        IF TG_OP = 'DELETE' THEN v_case_id := OLD.id; ELSE v_case_id := NEW.id; END IF;
    ELSIF TG_TABLE_NAME = 'extracted_fields' THEN
        IF TG_OP = 'UPDATE' AND OLD.document_id IS DISTINCT FROM NEW.document_id THEN
            RAISE EXCEPTION 'moving extracted fields between documents is prohibited' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_no_extracted_field_reparent';
        END IF;
        IF TG_OP = 'DELETE' THEN v_document_id := OLD.document_id; ELSE v_document_id := NEW.document_id; END IF;
        SELECT case_id INTO v_case_id FROM documents WHERE id = v_document_id;
    ELSIF TG_TABLE_NAME = 'document_security_events' THEN
        IF TG_OP = 'DELETE' THEN v_document_id := OLD.document_id; ELSE v_document_id := NEW.document_id; END IF;
        SELECT case_id INTO v_case_id FROM documents WHERE id = v_document_id;
    ELSE
        IF TG_OP = 'DELETE' THEN v_case_id := OLD.case_id; ELSE v_case_id := NEW.case_id; END IF;
        IF TG_OP = 'UPDATE' AND OLD.case_id IS DISTINCT FROM NEW.case_id THEN
            RAISE EXCEPTION 'moving case-owned rows between cases is prohibited' USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_no_reparent';
        END IF;
    END IF;
    IF v_case_id IS NULL THEN
        RAISE EXCEPTION 'cannot resolve case ownership for %', TG_TABLE_NAME USING ERRCODE = '23503';
    END IF;
    PERFORM 1 FROM cases WHERE id = v_case_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case not found for protected row' USING ERRCODE = '23503';
    END IF;
    SELECT id INTO v_latest_version_id FROM case_analysis_versions WHERE case_id = v_case_id ORDER BY version_no DESC LIMIT 1;
    IF v_latest_version_id IS NULL THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;
    SELECT EXISTS(
        SELECT 1 FROM case_governance_events e
         WHERE e.version_id = v_latest_version_id AND e.event_type IN ('FROZEN','CHECKER_CONFIRMED')
           AND NOT EXISTS (SELECT 1 FROM case_governance_events r WHERE r.version_id = v_latest_version_id AND r.event_type = 'RETURNED_TO_MAKER')
           AND NOT EXISTS (SELECT 1 FROM case_workflow_reopens w WHERE w.case_id = v_case_id AND w.based_on_version_id = v_latest_version_id AND w.status = 'OPEN')
    ) INTO v_is_frozen;
    IF v_is_frozen THEN
        RAISE EXCEPTION 'case inputs are frozen; Checker return or an explicit workflow reopen is required' USING ERRCODE = '55000', CONSTRAINT = 'ck_case_data_frozen';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;

COMMENT ON TABLE workflow_outbox_events IS 'Transactional outbox. Delivery workers claim with SKIP LOCKED and ack/retry; payload hashes are immutable.';
COMMENT ON TABLE workflow_inbox_events IS 'Append-only Camunda callback ledger with event ID and process-sequence deduplication.';
COMMENT ON TABLE case_resubmissions IS 'Immutable evidence receipt and impact list. Maker Freeze creates the next immutable analysis version after review.';
COMMENT ON TABLE case_workflow_release_gates IS 'Records externally validated G3/G4 references; DATA-AI does not make the release decision.';
COMMENT ON TABLE case_workflow_export_packages IS 'Hashed JSON/CSV/PDF evidence package; not a credit decision or DSR calculation.';
COMMENT ON TABLE case_override_application_receipts IS 'Signed Business Engine receipt that an approved proposal was applied externally; DATA-AI only records the receipt.';
