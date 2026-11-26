from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.governance import (
    assess_snapshot_readiness,
    calculate_snapshot_sha256,
    canonical_snapshot_bytes,
    require_governance_role,
    verify_version_integrity,
    version_state,
)
from app.schemas import GovernanceCheckerReviewIn, GovernanceFreezeIn
from app.main import app


def test_snapshot_hash_is_canonical_and_changes_when_source_changes():
    left = {"b": 2, "a": {"value": "đúng"}}
    right = {"a": {"value": "đúng"}, "b": 2}
    assert canonical_snapshot_bytes(left) == canonical_snapshot_bytes(right)
    assert calculate_snapshot_sha256(left) == calculate_snapshot_sha256(right)
    assert calculate_snapshot_sha256(left) != calculate_snapshot_sha256({"a": 1})


def test_maker_checker_role_separation_rejects_service_and_dual_roles():
    require_governance_role("maker-01", {"MAKER", "BANK_STAFF"}, "MAKER")
    require_governance_role("checker-01", {"CHECKER", "BANK_STAFF"}, "CHECKER")
    for actor, roles, expected in [
        ("svc", {"DATA_AI_SERVICE", "MAKER"}, "MAKER"),
        ("same-person", {"MAKER", "CHECKER"}, "MAKER"),
        ("maker", {"MAKER"}, "CHECKER"),
        ("checker", {"CHECKER"}, "MAKER"),
        ("", {"MAKER"}, "MAKER"),
        ("   ", {"MAKER"}, "MAKER"),
        ("admin-maker", {"MAKER", "BANK_ADMIN"}, "MAKER"),
        ("admin-checker", {"CHECKER", "SYSTEM_ADMIN"}, "CHECKER"),
    ]:
        with pytest.raises(HTTPException) as exc:
            require_governance_role(actor, roles, expected)
        assert exc.value.status_code == 403


def test_version_state_tracks_freeze_return_confirm_and_supersede():
    def ev(code):
        return SimpleNamespace(event_type=code)
    assert version_state([]) == "DRAFT"
    assert version_state([ev("FROZEN")]) == "FROZEN"
    assert version_state([ev("FROZEN"), ev("RETURNED_TO_MAKER")]) == "RETURNED_TO_MAKER"
    assert version_state([ev("FROZEN"), ev("CHECKER_CONFIRMED")]) == "CHECKER_CONFIRMED"
    assert version_state([ev("FROZEN"), ev("RETURNED_TO_MAKER"), ev("VERSION_SUPERSEDED")]) == "SUPERSEDED"


def test_checker_readiness_blocks_missing_manifest_scan_and_unreviewed_duplicates():
    snapshot = {
        "documents": [{"id": "d1", "malware_scan_status": "NOT_SCANNED", "processing_status": "COMPLETED"}],
        "evidence_manifest_entries": [],
        "transaction_duplicate_candidates": [{"id": "dup1"}],
        "evidence_review_decisions": [],
        "evidence_reconciliation_runs": [],
        "data_quality_issues": [],
        "extracted_fields": [{"review_status": "NEEDS_REVIEW", "extraction_decision": "ABSTAIN"}],
    }
    readiness = assess_snapshot_readiness(snapshot)
    blocker_codes = {item["code"] for item in readiness["blockers"]}
    assert readiness["review_ready"] is False
    assert readiness["status"] == "BLOCKED_FOR_TECHNICAL_CHECKER"
    assert {"DOCUMENTS_MISSING_MANIFEST", "DOCUMENT_SCAN_NOT_CLEARED",
            "DUPLICATE_CANDIDATES_NOT_REVIEWED"}.issubset(blocker_codes)
    warning_codes = {item["code"] for item in readiness["warnings"]}
    assert "OCR_ABSTENTIONS_PRESENT" in warning_codes
    assert "DATA_AI_SCOPE_LIMITATION" in warning_codes


def test_checker_readiness_allows_only_fully_manifested_scanned_and_processed_inputs():
    snapshot = {
        "documents": [{"id": "d1", "sha256": "a" * 64,
                        "malware_scan_status": "CLEAN", "processing_status": "COMPLETED"}],
        "document_security_events": [{"document_id": "d1", "scan_status": "CLEAN",
                                      "event_type": "SCAN_COMPLETED", "engine_name": "ClamAV",
                                      "engine_version": "ClamAV 1.4.2", "scanned_sha256": "a" * 64,
                                      "attestation_version": "V1_CLAMAV", "recorded_by": "scanner-service"}],
        "evidence_manifest_entries": [{"document_id": "d1"}],
        "transaction_duplicate_candidates": [], "evidence_review_decisions": [],
        "evidence_reconciliation_runs": [], "data_quality_issues": [], "extracted_fields": [],
    }
    readiness = assess_snapshot_readiness(snapshot)
    assert readiness["review_ready"] is True
    assert readiness["blockers"] == []


def test_governance_payloads_reject_blank_reasons_and_unknown_decisions():
    with pytest.raises(ValidationError):
        GovernanceFreezeIn(reason="   ")
    with pytest.raises(ValidationError):
        GovernanceCheckerReviewIn(decision="APPROVE", reason="reason long enough")
    assert GovernanceCheckerReviewIn(decision="CONFIRM", reason="Reviewed snapshot").decision == "CONFIRM"
    assert GovernanceCheckerReviewIn(decision="RETURN", reason="Needs a source correction").decision == "RETURN"


def test_governance_routes_are_exposed_and_scoped_to_case_versions():
    paths = app.openapi()["paths"]
    assert "/api/v1/cases/{case_id}/governance/freeze" in paths
    assert "/api/v1/cases/{case_id}/governance/versions" in paths
    assert "/api/v1/cases/{case_id}/governance/versions/{version_id}" in paths
    assert "/api/v1/cases/{case_id}/governance/versions/{version_id}/checker-review" in paths


def test_governance_snapshot_model_uses_same_case_parent_fk_and_immutable_event_model():
    from app import models
    assert models.CaseAnalysisVersion.__tablename__ == "case_analysis_versions"
    assert models.CaseGovernanceEvent.__tablename__ == "case_governance_events"
    version_constraints = {c.name for c in models.CaseAnalysisVersion.__table__.constraints}
    event_constraints = {c.name for c in models.CaseGovernanceEvent.__table__.constraints}
    assert "uq_case_analysis_version_case_no" in version_constraints
    assert "fk_case_analysis_version_parent_case" in version_constraints
    assert "fk_case_governance_event_version_case" in event_constraints
    event_indexes = {i.name for i in models.CaseGovernanceEvent.__table__.indexes}
    assert {"uq_case_governance_frozen_per_version", "uq_case_governance_checker_decision_per_version",
            "uq_case_governance_superseded_per_version"}.issubset(event_indexes)


def test_needs_more_evidence_is_not_counted_as_terminal_maker_review():
    snapshot = {
        "documents": [{"id": "d1", "malware_scan_status": "CLEAN", "processing_status": "COMPLETED"}],
        "evidence_manifest_entries": [{"document_id": "d1"}],
        "transaction_duplicate_candidates": [{"id": "dup1"}],
        "evidence_reconciliation_runs": [{"id": "run1"}],
        "evidence_review_decisions": [
            {"target_type": "TRANSACTION_DUPLICATE", "target_id": "dup1", "decision_code": "NEEDS_MORE_EVIDENCE"},
            {"target_type": "RECONCILIATION_RUN", "target_id": "run1", "decision_code": "NEEDS_MORE_EVIDENCE"},
        ],
        "data_quality_issues": [], "extracted_fields": [],
    }
    readiness = assess_snapshot_readiness(snapshot)
    blocker_codes = {x["code"] for x in readiness["blockers"]}
    assert "DUPLICATE_CANDIDATES_NOT_REVIEWED" in blocker_codes
    assert "RECONCILIATION_RUNS_NOT_REVIEWED" in blocker_codes


def test_checker_readiness_requires_auditable_scan_event_even_when_document_status_is_clean():
    snapshot = {
        "documents": [{"id": "d1", "malware_scan_status": "CLEAN", "processing_status": "COMPLETED"}],
        "document_security_events": [],
        "evidence_manifest_entries": [{"document_id": "d1"}],
        "transaction_duplicate_candidates": [], "evidence_review_decisions": [],
        "evidence_reconciliation_runs": [], "data_quality_issues": [], "extracted_fields": [],
    }
    readiness = assess_snapshot_readiness(snapshot)
    assert readiness["review_ready"] is False
    assert "DOCUMENT_SCAN_EVIDENCE_MISSING" in {item["code"] for item in readiness["blockers"]}


def test_persisted_snapshot_digest_and_readiness_projection_are_verified():
    snapshot = {"readiness": {"review_ready": True}, "source": {"count": 2}}
    version = SimpleNamespace(snapshot_data=snapshot,
                              snapshot_sha256=calculate_snapshot_sha256(snapshot),
                              readiness={"review_ready": True})
    assert verify_version_integrity(version) is True
    version.snapshot_data["source"]["count"] = 3
    assert verify_version_integrity(version) is False
    version.snapshot_data["source"]["count"] = 2
    version.readiness = {"review_ready": False}
    assert verify_version_integrity(version) is False
    version.snapshot_data = []
    assert verify_version_integrity(version) is False


def test_case_snapshot_captures_tenant_and_security_provenance_without_storage_paths():
    from datetime import datetime, timezone
    from app import models
    from app.governance import build_case_snapshot

    case_id, customer_id, org_id, document_id = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    document = SimpleNamespace(
        id=document_id, original_filename="statement.pdf", mime_type="application/pdf",
        detected_mime_type="application/pdf", file_size=128, sha256="a" * 64,
        document_type="BANK_STATEMENT", layout_code="GENERIC_PDF", evidence_status="RECEIVED",
        processing_status="COMPLETED", page_count=1, malware_scan_status="CLEAN",
        malware_scanned_at=now, malware_scan_engine="ClamAV", created_at=now,
        retention_until=None, legal_hold=False, deleted_at=None, stored_path="/private/storage",
        storage_object_key="private/object",
    )
    security_event = SimpleNamespace(
        id=uuid4(), document_id=document_id, event_type="SCAN_COMPLETED", scan_status="CLEAN",
        engine_name="ClamAV", engine_version="ClamAV 1.4.2", scanned_sha256="a" * 64,
        attestation_version="V1_CLAMAV", occurred_at=now, recorded_by="scanner-service",
        details={"private_path": "/do/not/copy"},
    )

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *args, **kwargs):
            return self
        def filter_by(self, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def all(self):
            if self.model is models.Document:
                return [document]
            if self.model is models.DocumentSecurityEvent:
                return [security_event]
            return []

    class FakeDB:
        def query(self, model):
            return FakeQuery(model)

    case = SimpleNamespace(
        id=case_id, external_case_id="CASE-001", bank_id="BANK-1",
        bank_organization_id=org_id, customer_id=customer_id, analysis_date=now,
        status="DRAFT", created_at=now,
    )
    snapshot, _ = build_case_snapshot(FakeDB(), case)
    assert snapshot["case"]["customer_id"] == str(customer_id)
    assert snapshot["case"]["bank_organization_id"] == str(org_id)
    assert snapshot["documents"][0]["detected_mime_type"] == "application/pdf"
    assert "stored_path" not in snapshot["documents"][0]
    assert "storage_object_key" not in snapshot["documents"][0]
    assert snapshot["document_security_events"][0]["scan_status"] == "CLEAN"
    assert "details" not in snapshot["document_security_events"][0]
