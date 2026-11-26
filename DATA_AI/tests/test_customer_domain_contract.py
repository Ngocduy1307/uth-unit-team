from pathlib import Path
from app.main import app
from app import models


def test_customer_staff_admin_tables_are_mapped():
    expected = {
        "customer_profiles", "customer_addresses", "customer_employments", "loan_applications",
        "staff_users", "access_roles", "staff_user_roles", "management_audit_logs",
        "bank_organizations", "bank_branches", "form_definitions", "form_field_definitions",
        "permissions", "role_permissions", "staff_role_assignment_history",
    }
    assert expected.issubset(set(models.Base.metadata.tables))


def test_customer_and_admin_routes_are_in_openapi():
    paths = app.openapi()["paths"]
    assert "/api/v1/customers" in paths
    assert "/api/v1/customers/{customer_id}/applications" in paths
    assert "/api/v1/internal/staff-sync" in paths
    assert "/api/v1/admin/forms/{form_code}" in paths
    assert "/api/v1/admin/exports/excel" in paths
    assert "/api/v1/admin/access-control/catalog" in paths
    assert "/api/v1/admin/staff/{staff_id}/role-history" in paths


def test_flyway_v4_contains_customer_and_staff_tables():
    migration = Path("db/migration/V4__customer_staff_and_application_domain.sql").read_text()
    for table in ("customer_profiles", "customer_addresses", "customer_employments", "loan_applications",
                  "staff_users", "access_roles", "staff_user_roles", "management_audit_logs",
                  "form_definitions", "form_field_definitions"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration


def test_form_value_validation_handles_required_and_numeric_rules():
    from types import SimpleNamespace
    from app.main import _validate_form_values
    fields = [
        SimpleNamespace(field_key="name", is_required=True, data_type="text", validation_json={"max_length": 10}, options_json=[]),
        SimpleNamespace(field_key="income", is_required=True, data_type="number", validation_json={"minimum": 1}, options_json=[]),
    ]
    assert _validate_form_values(fields, {"name": "An", "income": "25000000"}) == []
    assert _validate_form_values(fields, {"name": "A very long name", "income": "0"}) == ["income", "name"]


def test_customer_input_rejects_invalid_identity_suffix_and_requires_consent_reference():
    import pytest
    from pydantic import ValidationError
    from app.schemas import CustomerCreate, LoanApplicationCreate
    with pytest.raises(ValidationError):
        CustomerCreate(customer_code="C001", full_name="Demo Customer", phone="0900000000", identity_last4="12A")
    with pytest.raises(ValidationError):
        LoanApplicationCreate(external_case_id="CASE-1", bank_id="DEMO-BANK", requested_amount=1000000,
            requested_term_months=12, loan_purpose="Test")


def test_every_orm_table_has_a_flyway_create_table_statement():
    import re
    sql = "\n".join(p.read_text() for p in sorted(Path("db/migration").glob("V*.sql")))
    migrated = {name.split(".")[-1] for name in re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+((?:[a-zA-Z_][\w]*\.)?[a-zA-Z_][\w]*)", sql, re.I)}
    assert set(models.Base.metadata.tables).issubset(migrated)


def test_data_quality_and_lineage_routes_are_exposed():
    paths = app.openapi()["paths"]
    assert "/api/v1/cases/{case_id}/quality-issues" in paths
    assert "/api/v1/cases/{case_id}/pipeline-runs" in paths
    assert "/api/v1/admin/source-inventory" in paths
    assert "/api/v1/admin/field-mappings" in paths


def test_mvp_loan_term_is_limited_to_six_to_thirty_six_months():
    import pytest
    from pydantic import ValidationError
    from app.schemas import LoanApplicationCreate

    base = dict(external_case_id="CASE-TERM", bank_id="DEMO-BANK", requested_amount=1000000,
                loan_purpose="Chi tiêu cá nhân", consent_reference="CONSENT-1")
    for term in (6, 12, 36):
        assert LoanApplicationCreate(**base, requested_term_months=term).requested_term_months == term
    for term in (1, 5, 37, 360):
        with pytest.raises(ValidationError):
            LoanApplicationCreate(**base, requested_term_months=term)


def test_customer_form_omits_nonessential_personal_questions():
    form = Path("examples/frontend/CustomerApplicationForm.tsx").read_text()
    for removed_field in ("gender", "maritalStatus", "dependentsCount", "identityLast4", "preferredContactMethod"):
        assert removed_field not in form
    for required_field in ("fullName", "dateOfBirth", "phone", "employerName", "monthlyIncome",
                           "requestedAmount", "requestedTermMonths", "loanPurpose", "consent"):
        assert required_field in form


def test_customer_form_and_submission_default_to_v1_1():
    from app.schemas import LoanApplicationCreate, ApplicantSubmissionIn
    assert LoanApplicationCreate(external_case_id="C", bank_id="B", requested_amount=1000,
        requested_term_months=12, loan_purpose="test", consent_reference="CONSENT").form_version == "1.1"
    assert ApplicantSubmissionIn(applicant_ref="A", form_data={}, consent_reference="CONSENT-1").form_version == "1.1"


def test_v7_migration_contains_permission_catalog_and_role_history():
    migration = Path("db/migration/V7__rbac_catalog_and_role_history.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS permissions" in migration
    assert "CREATE TABLE IF NOT EXISTS role_permissions" in migration
    assert "CREATE TABLE IF NOT EXISTS staff_role_assignment_history" in migration
    assert "BANK_POLICY_OWNER" in migration


def test_applicant_submission_requires_consent_reference():
    import pytest
    from pydantic import ValidationError
    from app.schemas import ApplicantSubmissionIn
    with pytest.raises(ValidationError):
        ApplicantSubmissionIn(applicant_ref="A", form_data={})
    assert ApplicantSubmissionIn(applicant_ref="A", form_data={}, consent_reference="CONSENT-1").form_version == "1.1"


def test_internal_token_fails_closed_outside_development(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.main import require_internal_token
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "internal_service_token", "")
    import asyncio
    from starlette.requests import Request
    request = Request({"type": "http", "method": "GET", "path": "/health",
                      "headers": [], "query_string": b""})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_internal_token(request=request))
    assert exc.value.status_code == 503


def test_v1_1_snapshot_is_allowlisted_not_full_legacy_profile():
    source = Path("app/main.py").read_text()
    assert '"gender": customer.gender' not in source
    assert '"identity_last4": customer.identity_last4' not in source
    assert '"marital_status": customer.marital_status' not in source
    assert '"dependents_count": customer.dependents_count' not in source


def test_case_scope_rejects_cross_bank_access():
    import pytest
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.main import _assert_case_bank_scope
    case = SimpleNamespace(bank_id="BANK-A")
    with pytest.raises(HTTPException) as exc:
        _assert_case_bank_scope(case, "staff-1", "MAKER", "BANK-B")
    assert exc.value.status_code == 404
    _assert_case_bank_scope(case, "svc-1", "DATA_AI_SERVICE", "BANK-A")


def test_production_requires_signed_assertion_configuration(monkeypatch):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.main import require_internal_token
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "internal_service_token", "a-separate-internal-token")
    monkeypatch.setattr(settings, "service_assertion_keys", "")
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/cases",\
                       "headers": [], "query_string": b""})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_internal_token(request=request, x_internal_service_token="a-separate-internal-token"))
    assert exc.value.status_code == 503
