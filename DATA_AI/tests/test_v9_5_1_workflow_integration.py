from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import hashlib
import io
import json
import zipfile

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app import models
from app.main import app
from app.schemas import OverrideApplicationReceiptIn, WorkflowInboxEventIn, WorkflowReopenIn
from app.workflow_integration import (
    build_export_zip, build_resubmission_impact, sanitize_workflow_event_payload,
    sha256_bytes, sha256_json, validate_outbox_transition,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migration" / "V16__camunda_workflow_integration_and_evidence_lifecycle.sql"


def test_v951_inbox_accepts_camunda_string_identifiers_and_large_sequences():
    event = WorkflowInboxEventIn(
        external_event_id="zeebe-job:98127361", process_instance_id="proc-instance-00001",
        process_sequence=5_000_000_000, event_type="TASK_COMPLETED",
        payload={"task_id": "task-001", "task_type": "MAKER_REVIEW"},
    )
    assert event.external_event_id == "zeebe-job:98127361"
    assert event.process_sequence == 5_000_000_000


def test_v951_inbox_rejects_payloads_without_finite_json_and_missing_expiry_reference():
    with pytest.raises(ValidationError):
        WorkflowInboxEventIn(
            external_event_id="event-00000001", process_instance_id="process-0000001",
            process_sequence=1, event_type="TASK_ASSIGNED", payload={"not_finite": float("nan")},
        )
    with pytest.raises(ValidationError):
        WorkflowInboxEventIn(
            external_event_id="event-00000002", process_instance_id="process-0000001",
            process_sequence=1, event_type="EVIDENCE_EXPIRED", payload={},
        )


def test_v951_payload_sanitizer_keeps_routing_metadata_only_and_rejects_nested_values():
    payload = sanitize_workflow_event_payload({
        "task_id": "  task-001 ", "reason_code": "EVIDENCE_RECEIVED",
        "impact_sha256": "a" * 64, "applicant_name": "Sensitive Person",
        "account_number": "123456789", "raw_variables": {"salary": 123},
    })
    assert payload == {"task_id": "task-001", "reason_code": "EVIDENCE_RECEIVED", "impact_sha256": "a" * 64}
    with pytest.raises(ValueError, match="unsupported type"):
        sanitize_workflow_event_payload({"document_id": ["not-a-scalar"]})


def test_v951_resubmission_impact_is_explicit_about_recalculation_and_not_decision():
    impact = build_resubmission_impact(
        case_id="case-01", request_id="request-01", document_ids=["doc-b", "doc-a"],
        base_version_id="version-02", next_version_no=3, field_count=14,
        transaction_count=92, manifest_sequence_numbers=[9, 8],
    )
    assert impact["received_document_ids"] == ["doc-a", "doc-b"]
    assert impact["manifest_sequence_numbers"] == [8, 9]
    assert impact["affected_existing_field_count"] == 14
    assert impact["affected_existing_transaction_count"] == 92
    assert impact["recalculation_required"] is True
    assert impact["credit_decision_made"] is False
    assert len(sha256_json(impact)) == 64


def test_v951_outbox_delivery_transitions_enforce_retry_ceiling():
    assert validate_outbox_transition("PENDING", "IN_FLIGHT") == "IN_FLIGHT"
    assert validate_outbox_transition("IN_FLIGHT", "PENDING") == "PENDING"
    assert validate_outbox_transition("PENDING", "DEAD_LETTER", attempts=8) == "DEAD_LETTER"
    with pytest.raises(ValueError):
        validate_outbox_transition("PENDING", "DEAD_LETTER", attempts=7)
    with pytest.raises(ValueError):
        validate_outbox_transition("DELIVERED", "PENDING", attempts=2)


def test_v951_json_csv_pdf_export_package_contains_verified_entry_hashes():
    manifest = {
        "package_schema_version": "1.0", "case_id": "case-01", "analysis_version_no": 2,
        "snapshot_sha256": "a" * 64, "applicant_snapshot_sha256": "b" * 64,
        "product_code": "RETAIL", "product_version": "3.2", "policy_reference": "POL-01",
        "policy_version": "2026.4", "calculation_reference": "CALC-01", "calculation_version": "2",
        "calculation_sha256": "c" * 64, "evidence_document_count": 1, "audit_head_sha256": "d" * 64,
    }
    package, final_manifest = build_export_zip(
        manifest=manifest, analysis_snapshot={"snapshot_schema_version": "1.0", "fields": []},
        evidence_rows=[{"document_id": "doc-01", "filename": "statement.csv", "mime_type": "text/csv",
                        "file_size": 100, "sha256": "e" * 64, "document_type": "BANK_STATEMENT",
                        "evidence_status": "RECEIVED", "processing_status": "COMPLETED"}],
    )
    assert package.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        names = set(archive.namelist())
        assert names == {"analysis.json", "evidence.csv", "summary.pdf", "manifest.json"}
        on_disk_manifest = json.loads(archive.read("manifest.json"))
        assert on_disk_manifest == final_manifest
        assert archive.read("summary.pdf").startswith(b"%PDF-")
        for name, expected_hash in final_manifest["package_files"].items():
            assert sha256_bytes(archive.read(name)) == expected_hash
        assert "statement.csv" in archive.read("evidence.csv").decode("utf-8-sig")


def test_v951_workflow_reopen_policy_and_product_changes_require_version_refs():
    with pytest.raises(ValidationError):
        WorkflowReopenIn(reason_code="POLICY_VERSION_CHANGED", reason="Policy was revised after approval")
    with pytest.raises(ValidationError):
        WorkflowReopenIn(reason_code="PRODUCT_VERSION_CHANGED", reason="Product criteria have changed")
    evidence = WorkflowReopenIn(reason_code="EVIDENCE_UPDATED", reason="New evidence has been received")
    assert evidence.reason_code == "EVIDENCE_UPDATED"


def test_v951_business_engine_receipt_requires_matching_hashes_and_aware_applied_at():
    payload = OverrideApplicationReceiptIn(
        external_application_reference="policy-engine:receipt-001", applied_proposal_sha256="a" * 64,
        applied_version_sha256="b" * 64, policy_reference="POL-01", policy_version="2026.4",
        applied_at=datetime.now(timezone.utc),
    )
    assert payload.external_application_reference.startswith("policy-engine:")
    with pytest.raises(ValidationError):
        OverrideApplicationReceiptIn(
            external_application_reference="policy-engine:receipt-002", applied_proposal_sha256="x" * 64,
            applied_version_sha256="b" * 64, policy_reference="POL-01", policy_version="2026.4",
            applied_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValidationError):
        OverrideApplicationReceiptIn(
            external_application_reference="policy-engine:receipt-003", applied_proposal_sha256="a" * 64,
            applied_version_sha256="b" * 64, policy_reference="POL-01", policy_version="2026.4",
            applied_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )


def test_v951_routes_publish_workflow_integration_contract_with_internal_auth():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/workflow/cases/{case_id}/binding",
        "/api/v1/workflow/outbox/claim",
        "/api/v1/workflow/outbox/{event_id}/ack",
        "/api/v1/workflow/events",
        "/api/v1/workflow/cases/{case_id}/events",
        "/api/v1/cases/{case_id}/workflow/evidence-requests",
        "/api/v1/cases/{case_id}/workflow/evidence-requests/{request_id}/resubmit",
        "/api/v1/cases/{case_id}/workflow/resubmissions",
        "/api/v1/cases/{case_id}/workflow/reopen",
        "/api/v1/cases/{case_id}/workflow/release-gates",
        "/api/v1/cases/{case_id}/workflow/export-packages",
        "/api/v1/cases/{case_id}/governance/override-requests/{request_id}/application-receipt",
    }
    assert expected.issubset(paths)
    for path in expected:
        for operation in paths[path].values():
            header_names = {p["name"].lower() for p in operation.get("parameters", []) if p.get("in") == "header"}
            assert {"x-internal-service-token", "x-service-assertion"}.issubset(header_names)


def test_v951_models_and_migration_are_aligned_and_use_append_only_ledgers():
    expected_tables = {
        "case_workflow_bindings": {"ix_workflow_binding_case_created", "uq_workflow_binding_active_case"},
        "workflow_outbox_events": {"ix_workflow_outbox_claim", "ix_workflow_outbox_case_created"},
        "workflow_inbox_events": {"ix_workflow_inbox_case_received"},
        "case_evidence_requests": {"ix_case_evidence_request_case_status"},
        "case_resubmissions": {"ix_case_resubmission_case_created"},
        "case_workflow_reopens": {"ix_case_workflow_reopen_case_created", "uq_case_workflow_reopen_open_case"},
        "case_workflow_release_gates": {"ix_case_workflow_release_case_created"},
        "case_workflow_export_packages": {"ix_case_workflow_export_case_created"},
        "case_override_application_receipts": {"ix_override_application_receipt_case_received"},
    }
    for table_name, expected_indexes in expected_tables.items():
        table = models.Base.metadata.tables[table_name]
        assert expected_indexes.issubset({index.name for index in table.indexes})
        str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    sql = MIGRATION.read_text(encoding="utf-8")
    for token in [
        "CREATE TABLE case_workflow_bindings", "CREATE TABLE workflow_outbox_events",
        "CREATE TABLE workflow_inbox_events", "CREATE TABLE case_evidence_requests",
        "CREATE TABLE case_resubmissions", "CREATE TABLE case_workflow_reopens",
        "CREATE TABLE case_workflow_release_gates", "CREATE TABLE case_workflow_export_packages",
        "CREATE TABLE case_override_application_receipts", "trg_workflow_inbox_append_only",
        "trg_case_resubmission_append_only", "trg_case_release_gate_append_only",
        "trg_case_export_package_append_only", "trg_override_application_receipt_append_only",
        "ck_workflow_outbox_lease_state", "ck_case_evidence_request_resolution",
        "ck_case_workflow_reopen_completion", "SKIP LOCKED", "NEW.attempts >= 8", "explicit open workflow reopen",
        "BUSINESS_ENGINE", "ck_case_audit_actor_role",
    ]:
        assert token in sql
    assert "Camunda owns BPMN tasks/timers" in sql
    assert "does not make credit decisions" in sql


def test_v951_g4_requires_exact_g3_context_and_business_engine_receipt():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "G3 and G4 must reference identical product, policy and evidence snapshot versions" in source
    assert "Named Authority approval has not been confirmed as applied by the Business Engine" in source
    assert "applied_proposal_sha256" in source
    assert "applied_version_sha256" in source


def test_v951_expiry_callback_does_not_mutate_a_checker_frozen_case_row():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    callback = source.split('def receive_camunda_workflow_event(', 1)[1].split('@app.post("/api/v1/cases/{case_id}/workflow/evidence-requests"', 1)[0]
    expired = callback.split('elif payload.event_type == "CASE_EXPIRED":', 1)[1].split('elif payload.event_type in {"G3_SHADOW_GATE_PASSED"', 1)[0]
    assert "case.status = \"EXPIRED\"" not in expired
    assert "append-only inbox event is the authoritative integration receipt" in expired


def test_v951_upload_keeps_document_manifest_audit_and_outbox_in_one_db_transaction():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    upload = source.split("async def upload_document(", 1)[1].split("@app.post(\"/api/v1/cases/{case_id}/documents/{document_id}/process\"", 1)[0]
    assert "commit=False" in upload
    assert upload.index("_enqueue_case_workflow_event") < upload.index("db.commit()")
    service_source = (ROOT / "app" / "service.py").read_text(encoding="utf-8")
    assert "if commit:" in service_source


def test_v951_v14_frozen_input_guard_only_allows_an_explicit_workflow_reopen():
    sql = MIGRATION.read_text(encoding="utf-8")
    guard = sql.split("CREATE OR REPLACE FUNCTION guard_case_data_when_frozen()", 1)[1]
    assert "w.status = 'OPEN'" in guard
    assert "w.based_on_version_id = v_latest_version_id" in guard
    assert "Checker return or an explicit workflow reopen is required" in guard
    assert "CREATE OR REPLACE FUNCTION enforce_case_analysis_version_sequence()" in sql


def test_v951_business_engine_application_receipt_rejects_combined_roles():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    endpoint = source.split("def record_override_application_receipt(", 1)[1].split('@app.post("/api/v1/cases/{case_id}/workflow/release-gates"', 1)[0]
    assert 'if roles != {"BUSINESS_ENGINE"}:' in endpoint
    assert "BUSINESS_ENGINE-only signed service identity" in endpoint


def test_v951_published_camunda_inbox_schema_matches_runtime_event_allowlist():
    from app.workflow_integration import SAFE_EVENT_KEYS
    contract = json.loads((ROOT / "contracts" / "camunda-workflow-inbox-event-v1.schema.json").read_text(encoding="utf-8"))
    assert set(contract["properties"]["event_type"]["enum"]) == {
        "PROCESS_STARTED", "TASK_ASSIGNED", "TASK_COMPLETED", "EVIDENCE_EXPIRED",
        "CASE_EXPIRED", "PROCESS_COMPLETED", "CAMUNDA_INCIDENT",
        "G3_SHADOW_GATE_PASSED", "G4_OPERATIONAL_GATE_PASSED",
    }
    assert set(contract["properties"]["payload"]["properties"]) == SAFE_EVENT_KEYS
    for sample in (ROOT / "contracts" / "examples").glob("camunda-inbox-*.json"):
        payload = json.loads(sample.read_text(encoding="utf-8"))
        assert payload["event_type"] in contract["properties"]["event_type"]["enum"]


def test_v951_database_constraints_restrict_reopen_and_release_gate_authority():
    reopen = models.Base.metadata.tables["case_workflow_reopens"]
    evidence_requests = models.Base.metadata.tables["case_evidence_requests"]
    release_gates = models.Base.metadata.tables["case_workflow_release_gates"]
    assert not reopen.c.based_on_version_id.nullable
    assert not evidence_requests.c.binding_id.nullable
    constraint_names = {c.name for c in reopen.constraints if c.name}
    assert "ck_case_workflow_reopen_completion" in constraint_names
    release_checks = {c.name for c in release_gates.constraints if c.name}
    assert "ck_case_workflow_release_actor_role" in release_checks
