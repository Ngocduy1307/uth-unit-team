"""Regression tests for ORM coverage of V8/V9 PostgreSQL migration columns."""
from app import models


def _columns(table_name: str) -> set[str]:
    return set(models.Base.metadata.tables[table_name].columns.keys())


def test_v8_document_security_columns_are_mapped():
    assert {
        "detected_mime_type", "malware_scan_status", "malware_scanned_at",
        "malware_scan_engine", "storage_provider", "storage_object_key",
        "encryption_key_reference", "retention_until", "legal_hold", "deleted_at",
    } <= _columns("documents")


def test_v8_case_bank_organization_reference_is_mapped():
    assert "bank_organization_id" in _columns("cases")


def test_v8_payroll_extraction_provenance_is_mapped():
    assert {
        "gross_amount_field_id", "net_amount_field_id", "payment_date_field_id",
        "pay_period_start_field_id", "pay_period_end_field_id", "extraction_version",
        "reviewed_by", "reviewed_at",
    } <= _columns("payroll_evidence")


def test_v8_append_only_event_tables_are_mapped():
    assert "consent_events" in models.Base.metadata.tables
    assert "document_security_events" in models.Base.metadata.tables


def test_v8_declaration_idempotency_columns_are_mapped():
    for table in (
        "customer_household_profiles", "customer_expense_declarations",
        "customer_liability_declarations", "customer_salary_accounts",
    ):
        assert {"client_request_id", "updated_at"} <= _columns(table)


def test_v8_declaration_revision_provenance_is_mapped():
    assert {
        "customer_id", "client_request_id", "payload_sha256", "source_channel",
    } <= _columns("customer_declaration_revisions")


def test_v9_extraction_coordinate_provenance_is_mapped():
    assert {"coordinate_space", "extraction_method"} <= _columns("extracted_fields")


def test_v8_composite_tenant_constraints_are_represented_in_orm_metadata():
    cases = models.Base.metadata.tables["cases"]
    assert any(
        {column.name for column in constraint.columns} == {"customer_id", "bank_organization_id"}
        for constraint in cases.foreign_key_constraints
    )
    assert any(index.name == "uq_cases_id_customer" and index.unique for index in cases.indexes)
    assert any(index.name == "uq_customer_profiles_id_bank" and index.unique
               for index in models.Base.metadata.tables["customer_profiles"].indexes)


def test_v9_2_2_service_assertion_nonce_table_is_in_orm_metadata():
    assert "service_assertion_nonces" in models.Base.metadata.tables
    nonce = models.Base.metadata.tables["service_assertion_nonces"]
    assert {"nonce", "key_id", "expires_at", "created_at"}.issubset(set(nonce.columns.keys()))
