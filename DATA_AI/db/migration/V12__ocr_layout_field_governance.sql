-- V12: make OCR suggestions auditable and explicitly abstain when unsupported.
-- This migration adds metadata only; it does not claim approved bank layouts/fields.
SET search_path TO data_ai;

ALTER TABLE extracted_fields
    ADD COLUMN IF NOT EXISTS confidence_basis VARCHAR(48),
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(24) NOT NULL DEFAULT 'NOT_ASSESSED',
    ADD COLUMN IF NOT EXISTS extraction_decision VARCHAR(16) NOT NULL DEFAULT 'ABSTAIN',
    ADD COLUMN IF NOT EXISTS abstain_reason TEXT,
    ADD COLUMN IF NOT EXISTS extraction_rule_version VARCHAR(40);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_extracted_fields_validation_status'
          AND conrelid = 'data_ai.extracted_fields'::regclass
    ) THEN
        ALTER TABLE extracted_fields
            ADD CONSTRAINT ck_extracted_fields_validation_status
            CHECK (validation_status IN ('NOT_ASSESSED', 'VALID', 'FORMAT_UNCHECKED', 'INVALID_FORMAT')) NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_extracted_fields_extraction_decision'
          AND conrelid = 'data_ai.extracted_fields'::regclass
    ) THEN
        ALTER TABLE extracted_fields
            ADD CONSTRAINT ck_extracted_fields_extraction_decision
            CHECK (extraction_decision IN ('SUGGEST', 'ABSTAIN')) NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_extracted_fields_decision_review
    ON extracted_fields (document_id, extraction_decision, review_status);

COMMENT ON COLUMN extracted_fields.confidence_basis IS
    'Meaning of confidence field. Native PDF text and OCR values are uncalibrated and must not be interpreted as correctness probabilities.';
COMMENT ON COLUMN extracted_fields.validation_status IS
    'Normalization/format check only; VALID is not evidence authenticity or maker approval.';
COMMENT ON COLUMN extracted_fields.extraction_decision IS
    'SUGGEST is still reviewable only; ABSTAIN means automatic extraction must not be relied upon.';
COMMENT ON COLUMN extracted_fields.abstain_reason IS
    'Machine-readable comma-separated abstention reason codes for Maker review routing.';
