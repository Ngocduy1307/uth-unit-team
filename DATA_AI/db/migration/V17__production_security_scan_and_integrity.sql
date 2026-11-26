-- V9.5.2 Production security hardening for Workflow(3).
-- Adds byte-bound malware scan attestations and enforces that OCR/review cannot
-- trust an unverified or extension-only file type.
SET search_path TO data_ai;

ALTER TABLE document_security_events
    ADD COLUMN IF NOT EXISTS scanned_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS attestation_version VARCHAR(32) NOT NULL DEFAULT 'LEGACY_UNVERIFIED';

-- The workflow has an explicit accepted/quarantined branch. EXEMPT is retained
-- only for legacy history; new or modified rows cannot bypass malware scanning.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_no_new_scan_exempt_v17') THEN
        ALTER TABLE documents ADD CONSTRAINT ck_documents_no_new_scan_exempt_v17
            CHECK (malware_scan_status <> 'EXEMPT') NOT VALID;
    END IF;
END $$;

-- Preserve historical scan rows but explicitly mark them as legacy/unverified.
UPDATE document_security_events e
   SET scanned_sha256 = d.sha256
  FROM documents d
 WHERE d.id = e.document_id
   AND e.scanned_sha256 IS NULL
   AND e.event_type IN ('SCAN_COMPLETED', 'SCAN_INFECTED')
   AND e.scan_status IN ('CLEAN', 'INFECTED')
   AND d.sha256 ~ '^[0-9a-fA-F]{64}$';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_doc_security_scan_attestation_v17') THEN
        ALTER TABLE document_security_events
            ADD CONSTRAINT ck_doc_security_scan_attestation_v17 CHECK (
                attestation_version <> 'V1_CLAMAV' OR (
                    event_type IN ('SCAN_COMPLETED', 'SCAN_INFECTED')
                    AND scan_status IN ('CLEAN', 'INFECTED')
                    AND scanned_sha256 ~ '^[0-9a-f]{64}$'
                    AND engine_name = 'ClamAV'
                    AND length(coalesce(engine_version, '')) > 0
                    AND recorded_by <> ''
                )
            ) NOT VALID;
    END IF;
END $$;
ALTER TABLE document_security_events VALIDATE CONSTRAINT ck_doc_security_scan_attestation_v17;

CREATE INDEX IF NOT EXISTS ix_document_security_scan_attestation
    ON document_security_events(document_id, scanned_sha256, occurred_at DESC)
    WHERE attestation_version = 'V1_CLAMAV';

CREATE OR REPLACE FUNCTION validate_document_scan_attestation_v17()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_document_sha256 VARCHAR(64);
BEGIN
    IF NEW.attestation_version = 'V1_CLAMAV' THEN
        IF NEW.event_type NOT IN ('SCAN_COMPLETED', 'SCAN_INFECTED') THEN
            RAISE EXCEPTION 'ClamAV attestation must be a scan completion event'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_doc_security_scan_attestation_v17';
        END IF;
        SELECT sha256 INTO v_document_sha256 FROM documents WHERE id = NEW.document_id FOR UPDATE;
        IF v_document_sha256 IS NULL OR NEW.scanned_sha256 IS DISTINCT FROM v_document_sha256 THEN
            RAISE EXCEPTION 'scan attestation hash does not match the stored document'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_doc_security_scan_attestation_v17';
        END IF;
        IF (NEW.scan_status = 'CLEAN' AND NEW.event_type <> 'SCAN_COMPLETED') OR
           (NEW.scan_status = 'INFECTED' AND NEW.event_type <> 'SCAN_INFECTED') THEN
            RAISE EXCEPTION 'scan event type and verdict do not match'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_doc_security_scan_attestation_v17';
        END IF;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_validate_document_scan_attestation_v17 ON document_security_events;
CREATE TRIGGER trg_validate_document_scan_attestation_v17
    BEFORE INSERT OR UPDATE ON document_security_events
    FOR EACH ROW EXECUTE FUNCTION validate_document_scan_attestation_v17();

CREATE OR REPLACE FUNCTION guard_document_scan_status_v17()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.malware_scan_status IS DISTINCT FROM OLD.malware_scan_status
       AND NEW.malware_scan_status IN ('CLEAN', 'INFECTED') THEN
        IF NOT EXISTS (
            SELECT 1 FROM document_security_events e
             WHERE e.document_id = NEW.id
               AND e.scanned_sha256 = NEW.sha256
               AND e.attestation_version = 'V1_CLAMAV'
               AND e.engine_name = 'ClamAV'
               AND e.engine_version IS NOT NULL
               AND ((NEW.malware_scan_status = 'CLEAN' AND e.scan_status = 'CLEAN' AND e.event_type = 'SCAN_COMPLETED')
                 OR (NEW.malware_scan_status = 'INFECTED' AND e.scan_status = 'INFECTED' AND e.event_type = 'SCAN_INFECTED'))
        ) THEN
            RAISE EXCEPTION 'document scan state requires a matching byte-bound ClamAV attestation'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_documents_scan_state_attested_v17';
        END IF;
    END IF;
    IF OLD.malware_scan_status IN ('CLEAN', 'INFECTED')
       AND NEW.malware_scan_status IS DISTINCT FROM OLD.malware_scan_status THEN
        RAISE EXCEPTION 'a completed scan verdict is immutable; upload a new document version instead'
            USING ERRCODE = '55000', CONSTRAINT = 'ck_documents_scan_verdict_immutable_v17';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_guard_document_scan_status_v17 ON documents;
CREATE TRIGGER trg_guard_document_scan_status_v17
    BEFORE UPDATE OF malware_scan_status ON documents
    FOR EACH ROW EXECUTE FUNCTION guard_document_scan_status_v17();

CREATE OR REPLACE FUNCTION deny_document_security_event_mutation_v17()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'document security events are append-only'
        USING ERRCODE = '55000', CONSTRAINT = 'ck_document_security_events_append_only_v17';
END $$;
DROP TRIGGER IF EXISTS trg_document_security_events_append_only_v17 ON document_security_events;
CREATE TRIGGER trg_document_security_events_append_only_v17
    BEFORE UPDATE OR DELETE ON document_security_events
    FOR EACH ROW EXECUTE FUNCTION deny_document_security_event_mutation_v17();

COMMENT ON COLUMN document_security_events.scanned_sha256 IS
    'Exact document SHA-256 scanned by the named engine; required for V1_CLAMAV attestations.';
COMMENT ON COLUMN document_security_events.attestation_version IS
    'V1_CLAMAV is the only production-trusted scanner attestation; legacy rows remain LEGACY_UNVERIFIED.';
COMMENT ON FUNCTION guard_document_scan_status_v17() IS
    'A document cannot be marked CLEAN/INFECTED without a matching append-only ClamAV attestation.';
