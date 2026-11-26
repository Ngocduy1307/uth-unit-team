-- V9: persist the coordinate system and extraction path for every source anchor.
-- Additive migration. Apply only after V8 has been reviewed and installed.
SET search_path TO data_ai;

ALTER TABLE extracted_fields
    ADD COLUMN IF NOT EXISTS coordinate_space VARCHAR(24),
    ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(32);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_extracted_fields_coordinate_space'
          AND conrelid = 'data_ai.extracted_fields'::regclass
    ) THEN
        ALTER TABLE extracted_fields
            ADD CONSTRAINT ck_extracted_fields_coordinate_space
            CHECK (coordinate_space IS NULL OR coordinate_space IN ('PDF_POINT', 'IMAGE_PIXEL', 'CSV_ROW'))
            NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_extracted_fields_extraction_method'
          AND conrelid = 'data_ai.extracted_fields'::regclass
    ) THEN
        ALTER TABLE extracted_fields
            ADD CONSTRAINT ck_extracted_fields_extraction_method
            CHECK (extraction_method IS NULL OR extraction_method IN ('PDF_TEXT_LAYER', 'TESSERACT_OCR', 'CSV_IMPORT', 'MANUAL'))
            NOT VALID;
    END IF;
END $$;

COMMENT ON COLUMN extracted_fields.coordinate_space IS
    'Coordinate units for bbox: PDF_POINT for native PDF text, IMAGE_PIXEL for raster OCR, CSV_ROW for tabular source.';
COMMENT ON COLUMN extracted_fields.extraction_method IS
    'Provenance of the extracted value; this records method, not authenticity or correctness.';
