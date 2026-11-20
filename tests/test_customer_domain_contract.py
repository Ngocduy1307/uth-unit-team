from pathlib import Path
from app.main import app
from app import models


def test_customer_staff_admin_tables_are_mapped():
    expected = {
        "customer_profiles", "customer_addresses", "customer_employments", "loan_applications",
        "staff_users", "access_roles", "staff_user_roles", "management_audit_logs",
        "bank_organizations", "bank_branches", "form_definitions", "form_field_definitions",
    }
    assert expected.issubset(set(models.Base.metadata.tables))


def test_customer_and_admin_routes_are_in_openapi():
    paths = app.openapi()["paths"]
    assert "/api/v1/customers" in paths
    assert "/api/v1/customers/{customer_id}/applications" in paths
    assert "/api/v1/internal/staff-sync" in paths
    assert "/api/v1/admin/forms/{form_code}" in paths
    assert "/api/v1/admin/exports/excel" in paths


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
