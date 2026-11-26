from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app import models
from app.data_handoff import validate_declaration_payload, canonical_bytes, sha256_json
from app.main import app
from app.schemas import BusinessEngineReceiptIn, ScopeConsentAttestationIn

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migration" / "V18__data_ai_workflow_input_handoff.sql"


def test_v100_declaration_validation_preserves_vnd_nulls_and_leading_zeroes():
    salary_accounts = validate_declaration_payload("SALARY_ACCOUNTS", {
        "accounts": [{
            "bank_name": "Bank VN", "bank_code": "B001", "account_holder_name": "Applicant",
            "account_number_last4": "0042", "currency": "VND",
            "statement_start": "2026-05-01", "statement_end": "2026-10-31",
            "evidence_document_id": str(uuid4()),
        }]
    })
    assert salary_accounts["accounts"][0]["account_number_last4"] == "0042"
    expense = validate_declaration_payload("EXPENSES", {"answer": "HAS_ITEMS", "items": [
        {"category": "RENT", "amount_vnd": None, "frequency": "MONTHLY"}
    ]})
    assert expense["items"][0]["amount_vnd"] is None
    assert expense["items"][0]["amount_vnd"] != "0"


def test_v100_scope_does_not_expand_to_self_employment_cash_salary_or_full_account_number():
    with pytest.raises(ValueError, match="Only SALARIED"):
        validate_declaration_payload("EMPLOYMENT", {
            "employment_type": "SELF_EMPLOYED", "currency": "VND", "income_basis": "NET", "is_current": True
        })
    with pytest.raises(ValueError, match="Only VND"):
        validate_declaration_payload("EMPLOYMENT", {
            "employment_type": "SALARIED", "currency": "USD", "income_basis": "NET", "is_current": True
        })
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_declaration_payload("SALARY_ACCOUNTS", {"accounts": [{"account_number": "001234567890"}]})


def test_v100_scope_attestation_requires_timezone_and_fixed_scope():
    payload = ScopeConsentAttestationIn(
        scope_code="VN_UNSECURED_SALARIED_VND", scope_status="IN_SCOPE", consent_status="GRANTED",
        consent_reference="consent-01", purpose_code="CREDIT_ASSESSMENT", notice_version="notice-1",
        backend_decision_reference="backend-decision-01", attested_at=datetime.now(timezone.utc),
    )
    assert payload.scope_status == "IN_SCOPE"
    with pytest.raises(ValidationError):
        ScopeConsentAttestationIn(
            scope_code="OTHER", scope_status="IN_SCOPE", consent_status="GRANTED",
            consent_reference="consent-01", purpose_code="CREDIT_ASSESSMENT", notice_version="notice-1",
            backend_decision_reference="backend-decision-01", attested_at=datetime.now(timezone.utc),
        )


def test_v100_business_engine_receipt_requires_three_hash_bound_scenarios():
    payload = BusinessEngineReceiptIn(
        bundle_id=uuid4(), schedule_reference_id=uuid4(), input_bundle_sha256="a" * 64,
        calculation_reference="calc-ref-01", calculation_version="calc-v1",
        policy_reference="policy-ref-01", policy_version="policy-v1",
        product_code="VN_CASH_LOAN", product_version="prod-v1",
        product_sha256="b" * 64, policy_sha256="c" * 64,
        result_status="COMPLETED",
        scenario_references={"BASELINE": "base-01", "STRESS_1": "stress-01", "STRESS_2": "stress-02"},
        output_sha256="d" * 64, received_at=datetime.now(timezone.utc),
    )
    assert set(payload.scenario_references) == {"BASELINE", "STRESS_1", "STRESS_2"}
    assert payload.schedule_reference_id is not None
    with pytest.raises(ValidationError):
        BusinessEngineReceiptIn(
            bundle_id=uuid4(), schedule_reference_id=uuid4(), input_bundle_sha256="a" * 64,
            calculation_reference="calc-ref-02", calculation_version="calc-v1",
            policy_reference="policy-ref-01", policy_version="policy-v1",
            product_code="VN_CASH_LOAN", product_version="prod-v1",
            product_sha256="b" * 64, policy_sha256="c" * 64,
            result_status="COMPLETED", scenario_references={"BASELINE": "base-01"},
            output_sha256="d" * 64, received_at=datetime.now(timezone.utc),
        )


def test_v100_v18_models_compile_with_postgresql_dialect_and_have_expected_constraints():
    expected = {
        "case_scope_consent_attestations",
        "case_input_declaration_revisions",
        "case_input_declaration_evidence_links",
        "case_input_review_decisions",
        "case_financial_input_bundles",
        "case_proposed_schedule_references",
        "case_business_engine_receipts",
    }
    for name in expected:
        table = models.Base.metadata.tables[name]
        sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        if name in {"case_input_declaration_revisions", "case_input_review_decisions",
                    "case_financial_input_bundles", "case_business_engine_receipts"}:
            assert "JSONB" in sql
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    receipt = models.Base.metadata.tables["case_business_engine_receipts"]
    assert any(fk.name == "fk_business_engine_receipt_schedule_case" for fk in receipt.foreign_key_constraints)
    sql = MIGRATION.read_text(encoding="utf-8")
    for token in [
        "CREATE TABLE case_scope_consent_attestations",
        "CREATE TABLE case_input_declaration_revisions",
        "CREATE TABLE case_input_declaration_evidence_links",
        "CREATE TABLE case_input_review_decisions",
        "CREATE TABLE case_financial_input_bundles",
        "CREATE TABLE case_proposed_schedule_references",
        "CREATE TABLE case_business_engine_receipts",
        "CREATE OR REPLACE FUNCTION deny_v18_append_only_mutation",
        "case_scope_consent_attestations",
        "case_business_engine_receipts",
        "fk_business_engine_receipt_schedule_case",
        "uq_proposed_schedule_id_case",
        "DATA_AI_SERVICE",
        "CASE_INPUT_MAKER_REVIEW",
        "PROPOSED_SCHEDULE_REFERENCE_CREATE",
        "BUSINESS_ENGINE_RECEIPT_CREATE",
    ]:
        assert token in sql


def test_v100_financial_input_contract_preserves_external_calculation_authority():
    from app.data_handoff import build_financial_input_payload
    source = Path(build_financial_input_payload.__code__.co_filename).read_text(encoding="utf-8")
    assert "repayment_schedule" in source
    assert "residual" in source
    assert "DSR" in source
    assert "credit_decision" in source
    assert '"missing_values_remain_null": True' in source
    assert '"missing_months_are_not_zero": True' in source


def test_v100_routes_publish_data_ai_to_backend_and_financial_engine_contracts():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/cases/{case_id}/scope-consent-attestations",
        "/api/v1/cases/{case_id}/declarations/{section_code}/revisions",
        "/api/v1/cases/{case_id}/declarations",
        "/api/v1/cases/{case_id}/input-reviews",
        "/api/v1/cases/{case_id}/data-readiness",
        "/api/v1/cases/{case_id}/financial-input-bundles",
        "/api/v1/cases/{case_id}/financial-input-bundles/{bundle_id}",
        "/api/v1/cases/{case_id}/proposed-schedule-references",
        "/api/v1/cases/{case_id}/business-engine-receipts",
    }
    assert expected.issubset(paths)
    for path in expected:
        for operation in paths[path].values():
            headers = {p["name"].lower() for p in operation.get("parameters", []) if p.get("in") == "header"}
            assert {"x-internal-service-token", "x-service-assertion"}.issubset(headers)


def test_v100_retry_and_export_guards_bind_receipt_to_latest_external_result():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "Backend decision reference was already used with different attestation content" in source
    assert "client_request_id was already used with different declaration or evidence" in source
    assert "Calculation reference was already used with a different receipt payload" in source
    assert 'order_by(models.CaseBusinessEngineReceipt.received_at.desc()' in source
    assert 'engine_receipt.result_status != "COMPLETED"' in source
    assert "schedule_reference_id=schedule.id if schedule else None" in source
    assert "idempotent_replay" in source


def test_v100_readiness_requires_each_month_income_ledger_and_maker_review():
    source = Path(__import__("app.data_handoff", fromlist=["evaluate_data_readiness"]).__file__).read_text(encoding="utf-8")
    for token in [
        "OBSERVED_INCOME_LEDGER_MISSING",
        "INCOME_LEDGER_REQUIRES_MAKER_REVIEW",
        "missing_observed_income_ledger_months",
        "income_ledger_maker_review_pending_months",
        "workflow_route_hint",
        "CAMUNDA_BANK_DMN_NOT_DATA_AI",
    ]:
        assert token in source


def test_v100_maker_review_requires_matching_source_documents():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for token in [
        "Payroll-to-bank match is missing a same-case source document",
        "Transaction has no source statement document",
        "Maker review must cite every source document linked to the reviewed OCR, payroll, transaction or ledger target",
        "required_source_document_ids.issubset(submitted_document_ids)",
    ]:
        assert token in source


def test_v100_readiness_contract_can_report_missing_analysis_date_without_fake_months():
    schema = json.loads((ROOT / "contracts" / "data-ai-readiness-v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["window_months"]["minItems"] == 0
    assert schema["properties"]["window_months"]["maxItems"] == 6
    # An absent analysis date is a blocker, not a synthetic six-month range.
    assert "ANALYSIS_DATE_MISSING" in (ROOT / "app" / "data_handoff.py").read_text(encoding="utf-8")


def test_v100_completed_financial_receipt_must_bind_exact_schedule_reference():
    with pytest.raises(ValidationError, match="exact proposed schedule reference"):
        BusinessEngineReceiptIn(
            bundle_id=uuid4(), input_bundle_sha256="a" * 64,
            calculation_reference="calc-no-schedule", calculation_version="calc-v1",
            policy_reference="policy-ref", policy_version="policy-v1",
            product_code="VN_CASH_LOAN", product_version="prod-v1",
            product_sha256="b" * 64, policy_sha256="c" * 64,
            result_status="COMPLETED",
            scenario_references={"BASELINE": "base", "STRESS_1": "s1", "STRESS_2": "s2"},
            output_sha256="d" * 64, received_at=datetime.now(timezone.utc),
        )


def test_v100_income_ledger_maker_review_supports_pay_period_end_source_anchor():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "models.PayrollEvidence.pay_period_end >= target.period_month" in source
    assert "models.PayrollEvidence.payment_date.is_(None)" in source
    assert "related_payroll" in source and "related_transactions" in source


def test_v100_full_sqlalchemy_metadata_compiles_for_postgresql_dialect():
    compiled_tables = 0
    compiled_indexes = 0
    for table in models.Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=postgresql.dialect()))
        compiled_tables += 1
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            compiled_indexes += 1
    assert compiled_tables >= 64
    assert compiled_indexes >= 80


def test_v100_financial_handoff_omits_free_text_and_staff_identity_from_reviews():
    source = (ROOT / "app" / "data_handoff.py").read_text(encoding="utf-8")
    start = source.index("# Share decision outcomes")
    end = source.index('    return {', start)
    payload_review_code = source[start:end]
    assert '"reason": r.reason' not in payload_review_code
    assert '"reviewed_by": r.reviewed_by' not in payload_review_code
    assert '"evidence_refs": _json_value(r.evidence_refs)' in payload_review_code


def test_v100_financial_bundle_analysis_date_is_calendar_date_not_timestamp():
    source = (ROOT / "app" / "data_handoff.py").read_text(encoding="utf-8")
    assert 'case.analysis_date.date() if isinstance(case.analysis_date, datetime)' in source
    schema = json.loads((ROOT / "contracts" / "data-ai-financial-input-v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["analysis_date"]["format"] == "date"


def test_v100_financial_input_contract_limits_review_payload_to_decisions_and_anchors():
    schema = json.loads((ROOT / "contracts" / "data-ai-financial-input-v1.schema.json").read_text(encoding="utf-8"))
    maker_item = schema["properties"]["maker_input_reviews"]["items"]
    evidence_item = schema["properties"]["evidence_review_decisions"]["items"]
    assert maker_item["additionalProperties"] is False
    assert evidence_item["additionalProperties"] is False
    assert "reason" not in maker_item["properties"] and "reviewed_by" not in maker_item["properties"]
    assert "reason" not in evidence_item["properties"] and "reviewed_by" not in evidence_item["properties"]
    assert "evidence_refs" in evidence_item["properties"]
