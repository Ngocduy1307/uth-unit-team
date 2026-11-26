-- V9.1 read-only checks. Run after V1-V9 have been applied to a staging database.
-- Any non-zero issue_count must be reviewed before production sign-off.
SET search_path TO data_ai;

SELECT 'UNVALIDATED_DATA_AI_CONSTRAINTS' AS check_name, count(*) AS issue_count
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'data_ai' AND NOT c.convalidated;

SELECT 'DOCUMENT_WITH_INVALID_SHA256' AS check_name, count(*) AS issue_count
FROM documents
WHERE sha256 IS NULL OR sha256 !~ '^[0-9a-fA-F]{64}$';

SELECT 'DOCUMENT_WITH_UNSAFE_SECURITY_STATE' AS check_name, count(*) AS issue_count
FROM documents
WHERE malware_scan_status NOT IN ('NOT_SCANNED','PENDING','CLEAN','INFECTED','ERROR','EXEMPT');

SELECT 'PAYROLL_FIELD_ANCHOR_CROSS_DOCUMENT' AS check_name, count(*) AS issue_count
FROM payroll_evidence pe
JOIN LATERAL (VALUES
    (pe.gross_amount_field_id), (pe.net_amount_field_id),
    (pe.payment_date_field_id), (pe.pay_period_start_field_id),
    (pe.pay_period_end_field_id)
) AS anchor(field_id) ON anchor.field_id IS NOT NULL
JOIN extracted_fields ef ON ef.id = anchor.field_id
JOIN documents d ON d.id = ef.document_id
WHERE pe.document_id IS NOT NULL AND d.id <> pe.document_id;

SELECT 'DUPLICATE_DECLARATION_REQUEST_IDS' AS check_name, count(*) AS issue_count
FROM (
    SELECT case_id, client_request_id FROM customer_expense_declarations
    WHERE client_request_id IS NOT NULL GROUP BY case_id, client_request_id HAVING count(*) > 1
    UNION ALL
    SELECT case_id, client_request_id FROM customer_liability_declarations
    WHERE client_request_id IS NOT NULL GROUP BY case_id, client_request_id HAVING count(*) > 1
    UNION ALL
    SELECT case_id, client_request_id FROM customer_salary_accounts
    WHERE client_request_id IS NOT NULL GROUP BY case_id, client_request_id HAVING count(*) > 1
    UNION ALL
    SELECT case_id, client_request_id FROM customer_household_profiles
    WHERE client_request_id IS NOT NULL GROUP BY case_id, client_request_id HAVING count(*) > 1
) duplicates;

SELECT 'DOCUMENT_SECURITY_EVENTS_WITHOUT_DOCUMENT' AS check_name, count(*) AS issue_count
FROM document_security_events e LEFT JOIN documents d ON d.id = e.document_id
WHERE d.id IS NULL;

SELECT 'CONSENT_EVENTS_WITH_CASE_CUSTOMER_MISMATCH' AS check_name, count(*) AS issue_count
FROM consent_events ce
JOIN cases c ON c.id = ce.case_id
WHERE c.customer_id IS DISTINCT FROM ce.customer_id;
