SET search_path TO data_ai;

-- Organization and access-control domain. Authentication remains owned by Backend/SSO.
CREATE TABLE IF NOT EXISTS bank_organizations (
  id UUID PRIMARY KEY,
  bank_code VARCHAR(80) NOT NULL UNIQUE,
  bank_name VARCHAR(200) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bank_branches (
  id UUID PRIMARY KEY,
  bank_id UUID NOT NULL REFERENCES bank_organizations(id) ON DELETE RESTRICT,
  branch_code VARCHAR(80) NOT NULL,
  branch_name VARCHAR(200) NOT NULL,
  address TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_bank_branch_code UNIQUE(bank_id, branch_code)
);

CREATE TABLE IF NOT EXISTS staff_users (
  id UUID PRIMARY KEY,
  bank_id UUID REFERENCES bank_organizations(id) ON DELETE RESTRICT,
  branch_id UUID REFERENCES bank_branches(id) ON DELETE SET NULL,
  employee_code VARCHAR(80) NOT NULL UNIQUE,
  full_name VARCHAR(200) NOT NULL,
  email VARCHAR(254) NOT NULL UNIQUE,
  phone VARCHAR(30),
  staff_type VARCHAR(30) NOT NULL DEFAULT 'BANK_STAFF',
  status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
  external_identity_id VARCHAR(160) UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS access_roles (
  id UUID PRIMARY KEY,
  role_code VARCHAR(60) NOT NULL UNIQUE,
  role_name VARCHAR(120) NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staff_user_roles (
  staff_user_id UUID NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES access_roles(id) ON DELETE RESTRICT,
  assigned_by UUID REFERENCES staff_users(id) ON DELETE SET NULL,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(staff_user_id, role_id)
);

CREATE TABLE IF NOT EXISTS customer_profiles (
  id UUID PRIMARY KEY,
  bank_id UUID REFERENCES bank_organizations(id) ON DELETE RESTRICT,
  customer_code VARCHAR(100) NOT NULL UNIQUE,
  external_identity_id VARCHAR(160) UNIQUE,
  full_name VARCHAR(200) NOT NULL,
  date_of_birth DATE,
  gender VARCHAR(30),
  nationality VARCHAR(80) NOT NULL DEFAULT 'Vietnamese',
  phone VARCHAR(30) NOT NULL,
  email VARCHAR(254),
  identity_type VARCHAR(40),
  identity_last4 CHAR(4),
  marital_status VARCHAR(30),
  dependents_count SMALLINT NOT NULL DEFAULT 0 CHECK (dependents_count >= 0),
  preferred_contact_method VARCHAR(30),
  customer_status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_customer_profiles_phone ON customer_profiles(phone);
CREATE INDEX IF NOT EXISTS ix_customer_profiles_full_name ON customer_profiles(full_name);

CREATE TABLE IF NOT EXISTS customer_addresses (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
  address_type VARCHAR(30) NOT NULL,
  country_code CHAR(2) NOT NULL DEFAULT 'VN',
  province_code VARCHAR(30),
  province_name VARCHAR(120),
  district_name VARCHAR(120),
  ward_name VARCHAR(120),
  street_address TEXT,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_customer_addresses_customer ON customer_addresses(customer_id);

CREATE TABLE IF NOT EXISTS customer_employments (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
  employment_type VARCHAR(40) NOT NULL,
  employer_name VARCHAR(200),
  employer_tax_code VARCHAR(40),
  job_title VARCHAR(160),
  industry VARCHAR(120),
  work_phone VARCHAR(30),
  work_address TEXT,
  start_date DATE,
  end_date DATE,
  monthly_income_declared NUMERIC(18,2),
  income_currency CHAR(3) NOT NULL DEFAULT 'VND',
  is_current BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_customer_employments_customer ON customer_employments(customer_id);

-- Case links a customer profile to the existing DATA-AI evidence pipeline.
ALTER TABLE cases ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customer_profiles(id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS ix_cases_customer_id ON cases(customer_id);

CREATE TABLE IF NOT EXISTS loan_applications (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL UNIQUE REFERENCES cases(id) ON DELETE CASCADE,
  customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE RESTRICT,
  product_code VARCHAR(80),
  requested_amount NUMERIC(18,2) NOT NULL CHECK (requested_amount > 0),
  requested_term_months SMALLINT NOT NULL CHECK (requested_term_months BETWEEN 1 AND 360),
  loan_purpose VARCHAR(500) NOT NULL,
  preferred_disbursement_account_last4 CHAR(4),
  application_status VARCHAR(40) NOT NULL DEFAULT 'SUBMITTED',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_loan_applications_customer ON loan_applications(customer_id);

-- Configurable form definitions. Values are retained as versioned JSON snapshots in applicant_submissions.
CREATE TABLE IF NOT EXISTS form_definitions (
  id UUID PRIMARY KEY,
  form_code VARCHAR(80) NOT NULL,
  form_name VARCHAR(160) NOT NULL,
  version VARCHAR(40) NOT NULL,
  audience VARCHAR(30) NOT NULL DEFAULT 'CUSTOMER',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  definition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES staff_users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_form_definition_version UNIQUE(form_code, version)
);
CREATE TABLE IF NOT EXISTS form_field_definitions (
  id UUID PRIMARY KEY,
  form_definition_id UUID NOT NULL REFERENCES form_definitions(id) ON DELETE CASCADE,
  field_key VARCHAR(100) NOT NULL,
  field_label VARCHAR(200) NOT NULL,
  data_type VARCHAR(30) NOT NULL,
  is_required BOOLEAN NOT NULL DEFAULT FALSE,
  is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
  display_order INTEGER NOT NULL DEFAULT 0,
  validation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  CONSTRAINT uq_form_field_key UNIQUE(form_definition_id, field_key)
);
CREATE INDEX IF NOT EXISTS ix_form_fields_definition ON form_field_definitions(form_definition_id, display_order);

CREATE TABLE IF NOT EXISTS management_audit_logs (
  id UUID PRIMARY KEY,
  bank_id UUID REFERENCES bank_organizations(id) ON DELETE SET NULL,
  actor_staff_id UUID REFERENCES staff_users(id) ON DELETE SET NULL,
  actor_external_id VARCHAR(160),
  action VARCHAR(100) NOT NULL,
  target_type VARCHAR(80) NOT NULL,
  target_id VARCHAR(160),
  before_data JSONB,
  after_data JSONB,
  ip_address INET,
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_management_audit_actor ON management_audit_logs(actor_staff_id, created_at);
CREATE INDEX IF NOT EXISTS ix_management_audit_target ON management_audit_logs(target_type, target_id);

INSERT INTO access_roles(id, role_code, role_name, description) VALUES
 ('a0000000-0000-4000-8000-000000000001','CUSTOMER','Customer','Customer self-service identity; authentication owned by Backend'),
 ('a0000000-0000-4000-8000-000000000002','BANK_STAFF','Bank Staff','Can review assigned customer cases'),
 ('a0000000-0000-4000-8000-000000000003','DATA_AI_STAFF','Data AI Staff','Can inspect data quality and export authorized data'),
 ('a0000000-0000-4000-8000-000000000004','BANK_ADMIN','Bank Administrator','Can manage staff and bank-scoped configuration'),
 ('a0000000-0000-4000-8000-000000000005','SYSTEM_ADMIN','System Administrator','Can manage platform-level configuration')
ON CONFLICT(role_code) DO NOTHING;

-- Starter customer form definition; administrators can publish later versions without changing code.
INSERT INTO form_definitions(id, form_code, form_name, version, audience, definition_json)
VALUES ('a1000000-0000-4000-8000-000000000001','CUSTOMER_LOAN_APPLICATION','Customer Loan Application','1.0','CUSTOMER',
'{"sections":["personal","contact","address","employment","income","loan_request","consent"]}'::jsonb)
ON CONFLICT(form_code, version) DO NOTHING;

INSERT INTO form_field_definitions(id, form_definition_id, field_key, field_label, data_type, is_required, is_sensitive, display_order, validation_json)
SELECT v.id, f.id, v.field_key, v.field_label, v.data_type, v.is_required, v.is_sensitive, v.display_order, v.validation_json::jsonb
FROM form_definitions f
CROSS JOIN (VALUES
 ('a2000000-0000-4000-8000-000000000001'::uuid,'full_name','Họ và tên','text',TRUE,FALSE,1,'{"max_length":200}'),
 ('a2000000-0000-4000-8000-000000000002'::uuid,'date_of_birth','Ngày sinh','date',TRUE,FALSE,2,'{}'),
 ('a2000000-0000-4000-8000-000000000003'::uuid,'gender','Giới tính','select',FALSE,FALSE,3,'{"options":["MALE","FEMALE","OTHER"]}'),
 ('a2000000-0000-4000-8000-000000000004'::uuid,'phone','Số điện thoại','phone',TRUE,FALSE,4,'{"pattern":"^[0-9+]{9,15}$"}'),
 ('a2000000-0000-4000-8000-000000000005'::uuid,'email','Email','email',FALSE,FALSE,5,'{}'),
 ('a2000000-0000-4000-8000-000000000006'::uuid,'identity_last4','4 số cuối giấy tờ định danh','text',FALSE,TRUE,6,'{"length":4}'),
 ('a2000000-0000-4000-8000-000000000007'::uuid,'marital_status','Tình trạng hôn nhân','select',FALSE,FALSE,7,'{}'),
 ('a2000000-0000-4000-8000-000000000008'::uuid,'dependents_count','Số người phụ thuộc','number',FALSE,FALSE,8,'{"minimum":0,"maximum":30}'),
 ('a2000000-0000-4000-8000-000000000009'::uuid,'street_address','Địa chỉ','textarea',TRUE,FALSE,9,'{"max_length":1000}'),
 ('a2000000-0000-4000-8000-000000000010'::uuid,'province_name','Tỉnh/thành phố','text',TRUE,FALSE,10,'{}'),
 ('a2000000-0000-4000-8000-000000000011'::uuid,'employment_type','Loại hình công việc','select',TRUE,FALSE,11,'{}'),
 ('a2000000-0000-4000-8000-000000000012'::uuid,'employer_name','Tên đơn vị công tác','text',FALSE,FALSE,12,'{}'),
 ('a2000000-0000-4000-8000-000000000013'::uuid,'job_title','Chức danh','text',FALSE,FALSE,13,'{}'),
 ('a2000000-0000-4000-8000-000000000014'::uuid,'monthly_income_declared','Thu nhập hàng tháng tự khai báo','number',TRUE,FALSE,14,'{"minimum":0,"currency":"VND"}'),
 ('a2000000-0000-4000-8000-000000000015'::uuid,'requested_amount','Số tiền đề nghị vay','number',TRUE,FALSE,15,'{"minimum":1,"currency":"VND"}'),
 ('a2000000-0000-4000-8000-000000000016'::uuid,'requested_term_months','Thời hạn đề nghị (tháng)','number',TRUE,FALSE,16,'{"minimum":1,"maximum":360}'),
 ('a2000000-0000-4000-8000-000000000017'::uuid,'loan_purpose','Mục đích vay','textarea',TRUE,FALSE,17,'{"max_length":500}')
) AS v(id,field_key,field_label,data_type,is_required,is_sensitive,display_order,validation_json)
WHERE f.form_code='CUSTOMER_LOAN_APPLICATION' AND f.version='1.0'
ON CONFLICT(form_definition_id, field_key) DO NOTHING;
