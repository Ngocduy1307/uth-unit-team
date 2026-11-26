-- Version 1.1 customer intake: minimal fields aligned to the salaried VND unsecured-loan MVP.
-- Safe additive migration: retain all existing columns, tables and submitted snapshots.
SET search_path TO data_ai;

ALTER TABLE customer_employments
    ADD COLUMN IF NOT EXISTS income_basis VARCHAR(8);

-- Do not represent an uncollected household value as zero dependents.
ALTER TABLE customer_profiles ALTER COLUMN dependents_count DROP DEFAULT;
ALTER TABLE customer_profiles ALTER COLUMN dependents_count DROP NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_customer_employment_income_basis'
          AND conrelid = 'data_ai.customer_employments'::regclass
    ) THEN
        ALTER TABLE customer_employments
            ADD CONSTRAINT ck_customer_employment_income_basis
            CHECK (income_basis IS NULL OR income_basis IN ('NET', 'GROSS')) NOT VALID;
    END IF;
END $$;

-- Enforce MVP term limits for new/changed records without invalidating any legacy rows.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_loan_application_term_mvp'
          AND conrelid = 'data_ai.loan_applications'::regclass
    ) THEN
        ALTER TABLE loan_applications
            ADD CONSTRAINT ck_loan_application_term_mvp
            CHECK (requested_term_months BETWEEN 6 AND 36) NOT VALID;
    END IF;
END $$;

-- Role catalogue only. Authentication and authoritative permissions remain in Backend/SSO.
INSERT INTO access_roles(id, role_code, role_name, description) VALUES
 ('a0000000-0000-4000-8000-000000000006','MAKER','Maker','Prepares evidence and analysis; cannot check own work'),
 ('a0000000-0000-4000-8000-000000000007','CHECKER','Checker','Independently reviews Maker work; cannot approve own preparation')
ON CONFLICT(role_code) DO NOTHING;

-- Publish a new form version; never mutate historical version 1.0 or its submissions.
UPDATE form_definitions
SET is_active = FALSE
WHERE form_code = 'CUSTOMER_LOAN_APPLICATION' AND is_active = TRUE;

INSERT INTO form_definitions(id, form_code, form_name, version, audience, is_active, definition_json)
VALUES (
 'a1000000-0000-4000-8000-000000000002',
 'CUSTOMER_LOAN_APPLICATION',
 'Customer Loan Application',
 '1.1',
 'CUSTOMER',
 TRUE,
 '{"sections":["identity_contact","address","salaried_employment","loan_request","consent"],"scope":"VN_UNSECURED_SALARIED_VND","term_months":{"min":6,"max":36}}'::jsonb
)
ON CONFLICT(form_code, version) DO NOTHING;

INSERT INTO form_field_definitions(
 id, form_definition_id, field_key, field_label, data_type,
 is_required, is_sensitive, display_order, validation_json, options_json, is_active
)
SELECT v.id, f.id, v.field_key, v.field_label, v.data_type,
       v.is_required, v.is_sensitive, v.display_order,
       v.validation_json::jsonb, v.options_json::jsonb, TRUE
FROM form_definitions f
CROSS JOIN (VALUES
 ('a2100000-0000-4000-8000-000000000001'::uuid,'full_name','Họ và tên theo giấy tờ','text',TRUE,FALSE,1,'{"max_length":200}','[]'),
 ('a2100000-0000-4000-8000-000000000002'::uuid,'date_of_birth','Ngày sinh','date',TRUE,FALSE,2,'{}','[]'),
 ('a2100000-0000-4000-8000-000000000003'::uuid,'phone','Số điện thoại','phone',TRUE,FALSE,3,'{"pattern":"^[0-9+]{9,15}$"}','[]'),
 ('a2100000-0000-4000-8000-000000000004'::uuid,'email','Email','email',FALSE,FALSE,4,'{"max_length":254}','[]'),
 ('a2100000-0000-4000-8000-000000000005'::uuid,'residency_declaration','Xác nhận cư trú tại Việt Nam','checkbox',TRUE,FALSE,5,'{}','[]'),
 ('a2100000-0000-4000-8000-000000000006'::uuid,'province_name','Tỉnh/thành phố','text',TRUE,FALSE,6,'{"max_length":120}','[]'),
 ('a2100000-0000-4000-8000-000000000007'::uuid,'ward_name','Phường/xã','text',TRUE,FALSE,7,'{"max_length":120}','[]'),
 ('a2100000-0000-4000-8000-000000000008'::uuid,'street_address','Số nhà, tên đường','textarea',FALSE,FALSE,8,'{"max_length":1000}','[]'),
 ('a2100000-0000-4000-8000-000000000009'::uuid,'employment_type','Loại hình công việc','select',TRUE,FALSE,9,'{}','["SALARIED"]'),
 ('a2100000-0000-4000-8000-000000000010'::uuid,'employer_name','Tên đơn vị công tác','text',TRUE,FALSE,10,'{"max_length":200}','[]'),
 ('a2100000-0000-4000-8000-000000000011'::uuid,'job_title','Chức danh','text',FALSE,FALSE,11,'{"max_length":160}','[]'),
 ('a2100000-0000-4000-8000-000000000012'::uuid,'monthly_income_declared','Thu nhập hàng tháng khai báo (VND)','number',TRUE,FALSE,12,'{"minimum":1,"currency":"VND"}','[]'),
 ('a2100000-0000-4000-8000-000000000013'::uuid,'income_basis','Loại thu nhập khai báo','select',TRUE,FALSE,13,'{}','["NET","GROSS"]'),
 ('a2100000-0000-4000-8000-000000000014'::uuid,'salary_paid_to_bank','Xác nhận nhận lương qua tài khoản','checkbox',TRUE,FALSE,14,'{}','[]'),
 ('a2100000-0000-4000-8000-000000000015'::uuid,'requested_amount','Số tiền đề nghị vay (VND)','number',TRUE,FALSE,15,'{"minimum":1,"currency":"VND"}','[]'),
 ('a2100000-0000-4000-8000-000000000016'::uuid,'requested_term_months','Thời hạn đề nghị (tháng)','number',TRUE,FALSE,16,'{"minimum":6,"maximum":36}','[]'),
 ('a2100000-0000-4000-8000-000000000017'::uuid,'loan_purpose','Mục đích vay','textarea',TRUE,FALSE,17,'{"max_length":500}','[]'),
 ('a2100000-0000-4000-8000-000000000018'::uuid,'consent','Đồng ý xử lý dữ liệu','checkbox',TRUE,FALSE,18,'{}','[]')
) AS v(id,field_key,field_label,data_type,is_required,is_sensitive,display_order,validation_json,options_json)
WHERE f.form_code='CUSTOMER_LOAN_APPLICATION' AND f.version='1.1'
ON CONFLICT(form_definition_id, field_key) DO NOTHING;

COMMENT ON COLUMN customer_employments.income_basis IS
'Customer-declared basis only: NET or GROSS. Not an accepted-income decision.';
