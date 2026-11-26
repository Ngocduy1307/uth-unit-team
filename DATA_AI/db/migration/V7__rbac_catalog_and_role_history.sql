SET search_path TO data_ai;

-- DATA-AI keeps a permission catalogue/mirror for contracts and audit visibility.
-- Authentication and authoritative authorization remain in Spring Boot / SSO.
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY,
    permission_code VARCHAR(100) NOT NULL UNIQUE,
    resource VARCHAR(80) NOT NULL,
    action VARCHAR(40) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_permission_resource_action UNIQUE(resource, action)
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id UUID NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS staff_role_assignment_history (
    id UUID PRIMARY KEY,
    staff_user_id UUID NOT NULL REFERENCES staff_users(id) ON DELETE RESTRICT,
    role_id UUID NOT NULL REFERENCES access_roles(id) ON DELETE RESTRICT,
    action VARCHAR(20) NOT NULL CHECK (action IN ('ASSIGNED', 'REVOKED')),
    changed_by_external_id VARCHAR(160),
    reason TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_staff_role_history_staff_changed
    ON staff_role_assignment_history(staff_user_id, changed_at DESC);

INSERT INTO access_roles(id, role_code, role_name, description) VALUES
 ('a0000000-0000-4000-8000-000000000008','BANK_POLICY_OWNER','Bank Policy Owner','Owns bank-approved policy versions and effective dates; does not perform credit approval')
ON CONFLICT(role_code) DO NOTHING;

INSERT INTO permissions(id, permission_code, resource, action, description) VALUES
 ('b0000000-0000-4000-8000-000000000001','CUSTOMER_VIEW','CUSTOMER','VIEW','View customer records within authorized bank/case scope'),
 ('b0000000-0000-4000-8000-000000000002','CUSTOMER_UPDATE','CUSTOMER','UPDATE','Update customer declarations within authorized scope'),
 ('b0000000-0000-4000-8000-000000000003','APPLICATION_VIEW','APPLICATION','VIEW','View loan application metadata'),
 ('b0000000-0000-4000-8000-000000000004','DOCUMENT_UPLOAD','DOCUMENT','UPLOAD','Upload evidence documents'),
 ('b0000000-0000-4000-8000-000000000005','DOCUMENT_REVIEW','DOCUMENT','REVIEW','Review extracted document fields and evidence anchors'),
 ('b0000000-0000-4000-8000-000000000006','MAKER_SUBMIT','REVIEW','SUBMIT','Submit a Maker review package for independent checking'),
 ('b0000000-0000-4000-8000-000000000007','CHECKER_REVIEW','REVIEW','CHECK','Perform independent Checker review'),
 ('b0000000-0000-4000-8000-000000000008','STAFF_MANAGE','STAFF','MANAGE','Manage staff identities within bank scope'),
 ('b0000000-0000-4000-8000-000000000009','ROLE_ASSIGN','ROLE','ASSIGN','Assign or revoke roles under Backend policy'),
 ('b0000000-0000-4000-8000-000000000010','FORM_MANAGE','FORM','MANAGE','Manage bank-scoped form configuration'),
 ('b0000000-0000-4000-8000-000000000011','AUDIT_VIEW','AUDIT','VIEW','View scoped audit records'),
 ('b0000000-0000-4000-8000-000000000012','DATA_EXPORT','DATA','EXPORT','Export authorized data'),
 ('b0000000-0000-4000-8000-000000000013','POLICY_MANAGE','POLICY','MANAGE','Manage bank policy versions and effective dates'),
 ('b0000000-0000-4000-8000-000000000014','SOURCE_MAPPING_MANAGE','SOURCE_MAPPING','MANAGE','Maintain approved source inventory and field mappings')
ON CONFLICT(permission_code) DO NOTHING;

-- Seed only a reference matrix. Backend/SSO remains authoritative and may impose finer scope.
INSERT INTO role_permissions(role_id, permission_id)
SELECT r.id, p.id
FROM access_roles r
JOIN permissions p ON
 (r.role_code = 'CUSTOMER' AND p.permission_code IN ('CUSTOMER_VIEW','CUSTOMER_UPDATE','APPLICATION_VIEW','DOCUMENT_UPLOAD')) OR
 (r.role_code = 'MAKER' AND p.permission_code IN ('CUSTOMER_VIEW','APPLICATION_VIEW','DOCUMENT_REVIEW','MAKER_SUBMIT')) OR
 (r.role_code = 'CHECKER' AND p.permission_code IN ('CUSTOMER_VIEW','APPLICATION_VIEW','DOCUMENT_REVIEW','CHECKER_REVIEW')) OR
 (r.role_code = 'BANK_ADMIN' AND p.permission_code IN ('STAFF_MANAGE','ROLE_ASSIGN','FORM_MANAGE','AUDIT_VIEW')) OR
 (r.role_code = 'BANK_POLICY_OWNER' AND p.permission_code IN ('POLICY_MANAGE')) OR
 (r.role_code = 'DATA_AI_STAFF' AND p.permission_code IN ('DOCUMENT_REVIEW','SOURCE_MAPPING_MANAGE','DATA_EXPORT','AUDIT_VIEW')) OR
 (r.role_code = 'SYSTEM_ADMIN' AND p.permission_code IN ('STAFF_MANAGE','ROLE_ASSIGN','FORM_MANAGE','AUDIT_VIEW','DATA_EXPORT','SOURCE_MAPPING_MANAGE'))
ON CONFLICT DO NOTHING;

COMMENT ON TABLE permissions IS 'Permission catalogue for shared contracts; not a substitute for Backend/SSO authorization.';
COMMENT ON TABLE role_permissions IS 'Reference role-to-permission matrix; enforce scope and segregation in Backend.';
COMMENT ON TABLE staff_role_assignment_history IS 'Append-only history of role mirror changes received from Backend/SSO.';

-- Role assignment history is append-only at the database layer.
CREATE OR REPLACE FUNCTION data_ai.reject_role_history_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'staff_role_assignment_history is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_role_history_no_mutation ON staff_role_assignment_history;
CREATE TRIGGER trg_role_history_no_mutation
BEFORE UPDATE OR DELETE ON staff_role_assignment_history
FOR EACH ROW EXECUTE FUNCTION data_ai.reject_role_history_mutation();
