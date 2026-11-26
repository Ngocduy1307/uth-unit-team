# DATA-AI V9.0 release notes

## Scope
V9.0 is a first completed improvement pass over the V8 source package. It is deliberately limited to DATA-AI ingestion and document extraction. It does not implement business affordability formulas, credit policy decisions, Camunda orchestration, customer authentication or authoritative RBAC.

## Changes in this pass

1. **Digital PDF extraction first**: PDF pages with a usable embedded text layer are read with PyMuPDF. Tesseract is used only for scanned/sparse pages. This avoids rasterizing every page unnecessarily and preserves the native PDF source geometry.
2. **Explicit source coordinate provenance**: extracted field suggestions now carry `coordinate_space` (`PDF_POINT` or `IMAGE_PIXEL`) and `extraction_method` (`PDF_TEXT_LAYER` or `TESSERACT_OCR`). OCR token rows persist the same metadata. The values describe source geometry and extraction path, not authenticity or correctness.
3. **PDF handling**: encrypted PDFs, empty PDFs, malformed PDFs and over-limit page counts are rejected with controlled validation errors. Image decoding is validated before OCR and EXIF orientation is normalized.
4. **PostgreSQL terminology**: integration and migration guidance now describes the shared database as PostgreSQL, rather than a Neon-specific managed service. The existing Docker Compose stack provisions PostgreSQL 16 and Flyway.
5. **Regression tests**: tests cover digital PDF text-layer preference, encrypted PDF rejection and coordinate provenance.

## Database migration

`db/migration/V9__document_extraction_provenance.sql` is additive and records coordinate/extraction provenance in `extracted_fields`. This was the V9 release snapshot. The V9.2.2 release snapshot added Flyway V10; the later V9.2.3 API Reliability update adds V11. New environments at the current source level must apply V1 through V11 in order. For an existing database, confirm Flyway history and backup first; never edit an already-applied migration. V9 does not delete or rewrite existing evidence rows.

## Verified locally

- Python unit tests: **31 passed**.
- The tests run without requiring a live PostgreSQL server. This environment did not provide Docker or `psql`, so Flyway execution against PostgreSQL 16 has **not** been verified in this pass.

## Remaining blockers before real customer evidence

- Malware scanning and parser sandboxing are not implemented. Do not process real customer financial documents until approved scanning and isolation controls are integrated and tested.
- File/object storage is still local-volume based, not an approved encrypted immutable object store.
- PostgreSQL migration execution, database role separation, backup/restore and tenant isolation/RLS need staging verification with Backend/platform owners.
- Six approved layouts, the 20 critical fields, two bank CSV schemas and independently labeled evaluation data are still required. No Macro-F1, extraction accuracy, coverage or matching precision is claimed.
- Consent lifecycle, data retention/deletion, source rights and operational security approvals remain release gates owned jointly with Backend, bank and security/legal stakeholders.
- The current document classifier and field extraction rules remain provisional suggestions. Maker verification is mandatory.

## DATA-AI boundary
DATA-AI classifies, extracts, normalizes, links source anchors, flags quality issues and suggests candidate matches. It does not decide salary eligibility, calculate DSR/residual, infer credit outcomes or approve/reject an application. Financial calculations and policy decisions remain with the designated Business Logic/Financial Engine.
