# DATA_AI V9.1 ERD package

The ERD is split by bounded data domain to keep each diagram readable. These diagrams are generated from SQLAlchemy ORM metadata and show mapped foreign-key relationships; Flyway SQL remains authoritative for triggers, partial indexes, `NOT VALID` constraints and other database-only objects.

1. `ERD_V9_1_domain_1_customer_case.png/.svg`: bank, customer, case, application and customer declarations.
2. `ERD_V9_1_domain_2_document_ocr.png/.svg`: document intake, security events, consent, OCR fields and pipeline tracking.
3. `ERD_V9_1_domain_3_income_quality.png/.svg`: transactions, payroll evidence, income ledger, matching and quality findings.
4. `ERD_V9_1_domain_4_staff_rbac.png/.svg`: staff, roles, permissions, assignment history and management audit.
5. `ERD_V9_1_domain_5_source_export_forms.png/.svg`: source inventory, field mappings, export jobs and configurable forms.

`ERD_V9_1.mmd/.png/.svg` provide the complete overview. The complete view is intentionally dense; use the domain diagrams for review.
