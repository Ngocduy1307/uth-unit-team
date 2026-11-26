-- V14: immutable DATA-AI evidence/input snapshots and Maker–Checker technical review.
-- Backend/SSO remains authoritative for identity, roles and task assignment.
-- Camunda remains authoritative for workflow orchestration. This is not a credit decision; it is not an authoritative I/E/D result.
SET search_path TO data_ai;

CREATE TABLE case_analysis_versions (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    version_no INTEGER NOT NULL,
    based_on_version_id UUID NULL,
    snapshot_schema_version VARCHAR(40) NOT NULL DEFAULT 'V9.4.1.1',
    snapshot_sha256 VARCHAR(64) NOT NULL,
    snapshot_data JSONB NOT NULL,
    readiness JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(160) NOT NULL,
    created_by_role VARCHAR(40) NOT NULL DEFAULT 'MAKER',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_analysis_version_positive CHECK (version_no > 0),
    CONSTRAINT ck_case_analysis_version_creator_role CHECK (created_by_role = 'MAKER'),
    CONSTRAINT ck_case_analysis_version_creator_nonblank CHECK (length(trim(created_by)) > 0),
    CONSTRAINT ck_case_analysis_version_sha256 CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_case_analysis_version_snapshot_object CHECK (jsonb_typeof(snapshot_data) = 'object'),
    CONSTRAINT ck_case_analysis_version_readiness_object CHECK (jsonb_typeof(readiness) = 'object'),
    CONSTRAINT uq_case_analysis_version_case_no UNIQUE(case_id, version_no),
    CONSTRAINT uq_case_analysis_version_id_case UNIQUE(id, case_id),
    CONSTRAINT fk_case_analysis_version_parent_case
        FOREIGN KEY(based_on_version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_analysis_version_case_created
    ON case_analysis_versions(case_id, created_at DESC);

CREATE TABLE case_governance_events (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(160) NOT NULL,
    actor_role VARCHAR(40) NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_case_governance_event_type CHECK (event_type IN (
        'FROZEN','CHECKER_CONFIRMED','RETURNED_TO_MAKER','VERSION_SUPERSEDED')),
    CONSTRAINT ck_case_governance_actor_role CHECK (actor_role IN ('MAKER','CHECKER')),
    CONSTRAINT ck_case_governance_actor_nonblank CHECK (length(trim(actor_id)) > 0),
    CONSTRAINT ck_case_governance_reason CHECK (length(trim(reason)) >= 8),
    CONSTRAINT ck_case_governance_event_role CHECK (
        (event_type IN ('FROZEN','VERSION_SUPERSEDED') AND actor_role = 'MAKER') OR
        (event_type IN ('CHECKER_CONFIRMED','RETURNED_TO_MAKER') AND actor_role = 'CHECKER')),
    CONSTRAINT fk_case_governance_event_version_case
        FOREIGN KEY(version_id, case_id)
        REFERENCES case_analysis_versions(id, case_id) ON DELETE RESTRICT
);
CREATE INDEX ix_case_governance_case_created
    ON case_governance_events(case_id, created_at DESC);
CREATE INDEX ix_case_governance_version_created
    ON case_governance_events(version_id, created_at DESC);
CREATE UNIQUE INDEX uq_case_governance_frozen_per_version
    ON case_governance_events(version_id) WHERE event_type = 'FROZEN';
CREATE UNIQUE INDEX uq_case_governance_checker_decision_per_version
    ON case_governance_events(version_id)
    WHERE event_type IN ('CHECKER_CONFIRMED','RETURNED_TO_MAKER');
CREATE UNIQUE INDEX uq_case_governance_superseded_per_version
    ON case_governance_events(version_id) WHERE event_type = 'VERSION_SUPERSEDED';

-- Force strict, sequential version numbers and parent linkage under a case-row lock.
CREATE OR REPLACE FUNCTION enforce_case_analysis_version_sequence()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_latest_id UUID;
    v_latest_no INTEGER;
BEGIN
    PERFORM 1 FROM cases WHERE id = NEW.case_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case not found for analysis version' USING ERRCODE = '23503';
    END IF;
    SELECT id, version_no INTO v_latest_id, v_latest_no
      FROM case_analysis_versions
     WHERE case_id = NEW.case_id
     ORDER BY version_no DESC LIMIT 1;
    IF COALESCE(v_latest_no, 0) + 1 <> NEW.version_no THEN
        RAISE EXCEPTION 'analysis version must increment sequentially'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_sequential';
    END IF;
    IF NEW.based_on_version_id IS DISTINCT FROM v_latest_id THEN
        RAISE EXCEPTION 'analysis version parent must reference latest version'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_parent_latest';
    END IF;
    IF v_latest_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM case_governance_events
         WHERE version_id = v_latest_id AND event_type = 'RETURNED_TO_MAKER'
    ) THEN
        RAISE EXCEPTION 'a new version requires the previous version to be returned to Maker'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_requires_return';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_analysis_version_sequence
    BEFORE INSERT ON case_analysis_versions
    FOR EACH ROW EXECUTE FUNCTION enforce_case_analysis_version_sequence();

-- A version cannot commit without its corresponding FROZEN event, even when
-- a caller bypasses the application service and writes directly to PostgreSQL.
CREATE OR REPLACE FUNCTION require_case_analysis_version_frozen_event()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM case_governance_events
                    WHERE version_id = NEW.id AND event_type = 'FROZEN') THEN
        RAISE EXCEPTION 'analysis version must have a FROZEN governance event before commit'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_case_analysis_version_requires_frozen_event';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER trg_case_analysis_version_requires_frozen_event
    AFTER INSERT ON case_analysis_versions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_case_analysis_version_frozen_event();

-- Freeze/review events are validated independently of the HTTP layer.
CREATE OR REPLACE FUNCTION validate_case_governance_transition()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_created_by VARCHAR(160);
    v_ready BOOLEAN;
    v_has_freeze BOOLEAN;
    v_has_decision BOOLEAN;
    v_has_return BOOLEAN;
BEGIN
    PERFORM 1 FROM cases WHERE id = NEW.case_id FOR UPDATE;
    SELECT created_by, COALESCE((readiness->>'review_ready')::boolean, FALSE)
      INTO v_created_by, v_ready
      FROM case_analysis_versions
     WHERE id = NEW.version_id AND case_id = NEW.case_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'analysis version not found in case' USING ERRCODE = '23503';
    END IF;

    SELECT EXISTS(SELECT 1 FROM case_governance_events
                   WHERE version_id = NEW.version_id AND event_type = 'FROZEN') INTO v_has_freeze;
    SELECT EXISTS(SELECT 1 FROM case_governance_events
                   WHERE version_id = NEW.version_id
                     AND event_type IN ('CHECKER_CONFIRMED','RETURNED_TO_MAKER')) INTO v_has_decision;
    SELECT EXISTS(SELECT 1 FROM case_governance_events
                   WHERE version_id = NEW.version_id AND event_type = 'RETURNED_TO_MAKER') INTO v_has_return;

    IF NEW.event_type = 'FROZEN' THEN
        IF NEW.actor_role <> 'MAKER' OR NEW.actor_id <> v_created_by OR v_has_freeze THEN
            RAISE EXCEPTION 'freeze event must be created once by the version Maker'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_freeze_actor';
        END IF;
    ELSIF NEW.event_type IN ('CHECKER_CONFIRMED','RETURNED_TO_MAKER') THEN
        IF NEW.actor_role <> 'CHECKER' OR NEW.actor_id = v_created_by OR NOT v_has_freeze OR v_has_decision THEN
            RAISE EXCEPTION 'Checker must independently decide a frozen Maker version once'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_checker_independence';
        END IF;
        IF NEW.event_type = 'CHECKER_CONFIRMED' AND NOT v_ready THEN
            RAISE EXCEPTION 'version has unresolved technical readiness blockers'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_checker_readiness';
        END IF;
    ELSIF NEW.event_type = 'VERSION_SUPERSEDED' THEN
        IF NEW.actor_role <> 'MAKER' OR NOT v_has_return THEN
            RAISE EXCEPTION 'only a returned version can be superseded by a Maker'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_supersede_returned';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_case_governance_validate_transition
    BEFORE INSERT ON case_governance_events
    FOR EACH ROW EXECUTE FUNCTION validate_case_governance_transition();

-- Immutable snapshot and event ledgers; corrections require a new version/event.
CREATE OR REPLACE FUNCTION reject_case_governance_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; create a new analysis version or governance event', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;
CREATE TRIGGER trg_case_analysis_version_immutable
    BEFORE UPDATE OR DELETE ON case_analysis_versions
    FOR EACH ROW EXECUTE FUNCTION reject_case_governance_mutation();
CREATE TRIGGER trg_case_governance_event_immutable
    BEFORE UPDATE OR DELETE ON case_governance_events
    FOR EACH ROW EXECUTE FUNCTION reject_case_governance_mutation();

-- A frozen/confirmed DATA-AI snapshot locks all case-owned inputs at the DB boundary.
-- RETURNED_TO_MAKER is the only state that re-enables source mutations.
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
            RAISE EXCEPTION 'moving extracted fields between documents is prohibited'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_no_extracted_field_reparent';
        END IF;
        IF TG_OP = 'DELETE' THEN v_document_id := OLD.document_id; ELSE v_document_id := NEW.document_id; END IF;
        SELECT case_id INTO v_case_id FROM documents WHERE id = v_document_id;
    ELSIF TG_TABLE_NAME = 'document_security_events' THEN
        IF TG_OP = 'DELETE' THEN v_document_id := OLD.document_id; ELSE v_document_id := NEW.document_id; END IF;
        SELECT case_id INTO v_case_id FROM documents WHERE id = v_document_id;
    ELSE
        IF TG_OP = 'DELETE' THEN v_case_id := OLD.case_id; ELSE v_case_id := NEW.case_id; END IF;
        IF TG_OP = 'UPDATE' AND OLD.case_id IS DISTINCT FROM NEW.case_id THEN
            RAISE EXCEPTION 'moving case-owned rows between cases is prohibited'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_case_governance_no_reparent';
        END IF;
    END IF;

    IF v_case_id IS NULL THEN
        RAISE EXCEPTION 'cannot resolve case ownership for %', TG_TABLE_NAME USING ERRCODE = '23503';
    END IF;
    PERFORM 1 FROM cases WHERE id = v_case_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'case not found for protected row' USING ERRCODE = '23503';
    END IF;

    SELECT id INTO v_latest_version_id FROM case_analysis_versions
     WHERE case_id = v_case_id ORDER BY version_no DESC LIMIT 1;
    IF v_latest_version_id IS NULL THEN
        IF TG_TABLE_NAME = 'cases' AND TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;

    SELECT EXISTS(
        SELECT 1 FROM case_governance_events e
         WHERE e.version_id = v_latest_version_id AND e.event_type IN ('FROZEN','CHECKER_CONFIRMED')
           AND NOT EXISTS (SELECT 1 FROM case_governance_events r
                            WHERE r.version_id = v_latest_version_id AND r.event_type = 'RETURNED_TO_MAKER')
    ) INTO v_is_frozen;
    IF v_is_frozen THEN
        RAISE EXCEPTION 'case inputs are frozen; Checker must return the version to Maker before edits'
            USING ERRCODE = '55000', CONSTRAINT = 'ck_case_data_frozen';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;

DO $$
DECLARE
    t TEXT;
    protected_tables TEXT[] := ARRAY[
        'cases','documents','extracted_fields','transactions','processing_results',
        'applicant_submissions','data_quality_issues','payroll_evidence','income_ledger_months',
        'earning_match_candidates','loan_applications','pipeline_runs','customer_household_profiles',
        'customer_expense_declarations','customer_liability_declarations','customer_salary_accounts',
        'customer_declaration_revisions','consent_events','evidence_manifest_entries',
        'transaction_duplicate_candidates','evidence_reconciliation_runs','evidence_review_decisions',
        'document_security_events'
    ];
BEGIN
    FOREACH t IN ARRAY protected_tables LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON data_ai.%I FOR EACH ROW EXECUTE FUNCTION data_ai.guard_case_data_when_frozen()',
                       'trg_guard_frozen_' || t, t);
    END LOOP;
END $$;

COMMENT ON TABLE case_analysis_versions IS
    'Immutable DATA-AI evidence/input snapshot for a Maker/Checker technical review cycle; not a credit decision or authoritative I/E/D result.';
COMMENT ON TABLE case_governance_events IS
    'Append-only Maker/Checker technical governance record. Backend/SSO owns identity/assignment; Camunda owns User Tasks and process state.';
COMMENT ON FUNCTION guard_case_data_when_frozen() IS
    'Blocks case-owned source mutations while the latest DATA-AI version is frozen or Checker-confirmed; RETURNED_TO_MAKER permits edits.';
