-- Run manually BEFORE deploying V8 on staging/production.
-- This file is intentionally not a Flyway migration.
SET search_path TO data_ai;

SELECT 'V7_FLYWAY' AS check_name, version, description, success
FROM flyway_schema_history ORDER BY installed_rank;

SELECT 'CASE_WITHOUT_CUSTOMER' AS check_name, count(*) AS issue_count
FROM cases WHERE customer_id IS NULL;

SELECT 'UNMAPPED_LEGACY_BANK_CODE' AS check_name, count(DISTINCT c.bank_id) AS issue_count
FROM cases c
LEFT JOIN bank_organizations b ON b.bank_code = c.bank_id
WHERE c.bank_organization_id IS NULL AND b.id IS NULL;

SELECT 'CASE_CUSTOMER_BANK_MISMATCH' AS check_name, count(*) AS issue_count
FROM cases c
JOIN customer_profiles cp ON cp.id = c.customer_id
JOIN bank_organizations b ON b.bank_code = c.bank_id
WHERE cp.bank_id IS NOT NULL AND cp.bank_id <> b.id;

SELECT 'LOAN_APPLICATION_CUSTOMER_MISMATCH' AS check_name, count(*) AS issue_count
FROM loan_applications la JOIN cases c ON c.id = la.case_id
WHERE la.customer_id <> c.customer_id;

SELECT 'HOUSEHOLD_CUSTOMER_MISMATCH' AS check_name, count(*) AS issue_count
FROM customer_household_profiles h JOIN cases c ON c.id = h.case_id
WHERE h.customer_id <> c.customer_id;

SELECT 'SALARY_ACCOUNT_OVER_LIMIT' AS check_name, count(*) AS issue_count
FROM (SELECT case_id FROM customer_salary_accounts GROUP BY case_id HAVING count(*) > 3) x;

SELECT 'PAYROLL_FIELD_MISSING_DOCUMENT' AS check_name, count(*) AS issue_count
FROM payroll_evidence pe
JOIN extracted_fields ef ON ef.id IN (
    pe.gross_amount_field_id, pe.net_amount_field_id,
    pe.payment_date_field_id, pe.pay_period_start_field_id,
    pe.pay_period_end_field_id
)
JOIN documents d ON d.id = ef.document_id
WHERE pe.document_id IS NOT NULL AND d.id <> pe.document_id;
