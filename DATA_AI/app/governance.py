"""DATA-AI V9.4.1 bounded governance primitives.

Backend/SSO authenticates identities and supplies trusted roles in the signed
service assertion. This module records immutable DATA-AI input snapshots and
independent technical review; it does not implement Camunda or credit policy.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models

SNAPSHOT_SCHEMA_VERSION = "V10.0.0.1"


def _json_value(value: Any) -> Any:
    if isinstance(value, (UUID,)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_snapshot_bytes(snapshot: dict) -> bytes:
    return json.dumps(_json_value(snapshot), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def calculate_snapshot_sha256(snapshot: dict) -> str:
    return hashlib.sha256(canonical_snapshot_bytes(snapshot)).hexdigest()


def verify_version_integrity(version: Any) -> bool:
    """Verify persisted snapshot bytes and the duplicated readiness projection."""
    if not isinstance(version.snapshot_data, dict) or not isinstance(version.readiness, dict):
        return False
    try:
        actual = calculate_snapshot_sha256(version.snapshot_data)
    except (TypeError, ValueError):
        return False
    expected = str(version.snapshot_sha256 or "")
    if not expected or not hmac.compare_digest(actual, expected):
        return False
    return version.snapshot_data.get("readiness") == version.readiness


def require_governance_role(actor_id: str, roles: set[str], expected_role: str) -> None:
    """Enforce strict human-role separation after signed-assertion validation."""
    if not actor_id or not actor_id.strip() or roles.intersection({"DATA_AI_SERVICE", "BANK_ADMIN", "SYSTEM_ADMIN", "DATA_AI_STAFF"}):
        raise HTTPException(403, "Governance actions require a dedicated human Maker or Checker identity")
    if {"MAKER", "CHECKER"}.issubset(roles):
        raise HTTPException(403, "A staff identity cannot act as both Maker and Checker")
    if expected_role not in roles:
        raise HTTPException(403, f"{expected_role.title()} role required")
    opposite = "CHECKER" if expected_role == "MAKER" else "MAKER"
    if opposite in roles:
        raise HTTPException(403, "Maker–Checker segregation of duties violation")


def version_state(events: list[Any]) -> str:
    event_types = {getattr(item, "event_type", item.get("event_type") if isinstance(item, dict) else None)
                   for item in events}
    if "VERSION_SUPERSEDED" in event_types:
        return "SUPERSEDED"
    if "RETURNED_TO_MAKER" in event_types:
        return "RETURNED_TO_MAKER"
    if "CHECKER_CONFIRMED" in event_types:
        return "CHECKER_CONFIRMED"
    if "FROZEN" in event_types:
        return "FROZEN"
    return "DRAFT"


def assess_snapshot_readiness(snapshot: dict) -> dict:
    """Readiness checks for technical Checker confirmation, never credit eligibility."""
    blockers: list[dict] = []
    warnings: list[dict] = []
    documents = snapshot.get("documents", [])
    manifest_document_ids = {item.get("document_id") for item in snapshot.get("evidence_manifest_entries", [])}

    if not documents:
        blockers.append({"code": "NO_EVIDENCE_DOCUMENTS", "count": 1})

    unmanifested = [d for d in documents if d.get("id") not in manifest_document_ids]
    if unmanifested:
        blockers.append({"code": "DOCUMENTS_MISSING_MANIFEST", "count": len(unmanifested),
                         "document_ids": [d.get("id") for d in unmanifested]})

    security_events = snapshot.get("document_security_events", [])
    # Workflow(3) requires a real byte-bound scanner attestation. Legacy CLEAN
    # and EXEMPT flags are not proof that the current stored bytes were scanned.
    unsafe_scan = [d for d in documents if d.get("malware_scan_status") != "CLEAN"]
    if unsafe_scan:
        blockers.append({"code": "DOCUMENT_SCAN_NOT_CLEARED", "count": len(unsafe_scan),
                         "document_ids": [d.get("id") for d in unsafe_scan]})
    scan_evidence_missing = []
    for document in documents:
        status = document.get("malware_scan_status")
        if status != "CLEAN":
            continue
        document_events = [event for event in security_events
                           if event.get("document_id") == document.get("id")
                           and event.get("scan_status") == status
                           and event.get("event_type") == "SCAN_COMPLETED"
                           and event.get("recorded_by")
                           and event.get("engine_name") == "ClamAV"
                           and event.get("engine_version")
                           and event.get("scanned_sha256") == document.get("sha256")
                           and event.get("attestation_version") == "V1_CLAMAV"]
        if not document_events:
            scan_evidence_missing.append(document.get("id"))
    if scan_evidence_missing:
        blockers.append({"code": "DOCUMENT_SCAN_EVIDENCE_MISSING",
                         "count": len(scan_evidence_missing),
                         "document_ids": scan_evidence_missing})

    not_processed = [d for d in documents if d.get("processing_status") != "COMPLETED"]
    if not_processed:
        blockers.append({"code": "DOCUMENT_PROCESSING_INCOMPLETE", "count": len(not_processed),
                         "document_ids": [d.get("id") for d in not_processed]})

    duplicate_reviews = {d.get("target_id") for d in snapshot.get("evidence_review_decisions", [])
                         if d.get("target_type") == "TRANSACTION_DUPLICATE"
                         and d.get("decision_code") in {"CONFIRMED_DUPLICATE", "NOT_DUPLICATE"}}
    pending_duplicates = [c for c in snapshot.get("transaction_duplicate_candidates", [])
                          if c.get("id") not in duplicate_reviews]
    if pending_duplicates:
        blockers.append({"code": "DUPLICATE_CANDIDATES_NOT_REVIEWED", "count": len(pending_duplicates),
                         "candidate_ids": [c.get("id") for c in pending_duplicates]})

    reconciliation_reviews = {d.get("target_id") for d in snapshot.get("evidence_review_decisions", [])
                              if d.get("target_type") == "RECONCILIATION_RUN"
                              and d.get("decision_code") in {"CONFIRMED_MATCH", "CONFIRMED_VARIANCE", "REJECTED"}}
    pending_reconciliations = [r for r in snapshot.get("evidence_reconciliation_runs", [])
                               if r.get("id") not in reconciliation_reviews]
    if pending_reconciliations:
        blockers.append({"code": "RECONCILIATION_RUNS_NOT_REVIEWED", "count": len(pending_reconciliations),
                         "run_ids": [r.get("id") for r in pending_reconciliations]})

    open_critical = [q for q in snapshot.get("data_quality_issues", [])
                     if str(q.get("severity", "")).upper() == "CRITICAL"
                     and str(q.get("issue_status", "OPEN")).upper() not in {"RESOLVED", "CLOSED"}]
    if open_critical:
        blockers.append({"code": "CRITICAL_DATA_QUALITY_ISSUES_OPEN", "count": len(open_critical),
                         "issue_ids": [q.get("id") for q in open_critical]})

    unreviewed_fields = [f for f in snapshot.get("extracted_fields", [])
                         if str(f.get("review_status", "")).upper() not in {"APPROVED", "ACCEPTED", "REVIEWED"}]
    abstained_fields = [f for f in snapshot.get("extracted_fields", [])
                        if str(f.get("extraction_decision", "")).upper() == "ABSTAIN"]
    if unreviewed_fields:
        warnings.append({"code": "EXTRACTED_FIELDS_REQUIRE_HUMAN_REVIEW", "count": len(unreviewed_fields)})
    if abstained_fields:
        warnings.append({"code": "OCR_ABSTENTIONS_PRESENT", "count": len(abstained_fields)})
    warnings.append({"code": "DATA_AI_SCOPE_LIMITATION",
                     "message": "This snapshot is not an authoritative I/E/D, DSR, stress, policy or credit-decision result."})

    return {
        "status": "READY_FOR_TECHNICAL_CHECKER" if not blockers else "BLOCKED_FOR_TECHNICAL_CHECKER",
        "review_ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }


def _serialize_model_rows(db: Session, model, case_id, *, order_column=None,
                           exclude_fields: set[str] | None = None) -> list[dict]:
    query = db.query(model).filter(model.case_id == case_id)
    if order_column is not None:
        query = query.order_by(order_column)
    excluded = exclude_fields or set()
    output = []
    for row in query.all():
        item = {}
        for attr in model.__mapper__.column_attrs:
            key = attr.key
            if key in excluded:
                continue
            item[key] = _json_value(getattr(row, key))
        output.append(item)
    return output


def build_case_snapshot(db: Session, case: models.Case) -> tuple[dict, dict]:
    """Capture DATA-AI evidence/input records without exposing physical storage paths."""
    docs = db.query(models.Document).filter_by(case_id=case.id).order_by(models.Document.created_at, models.Document.id).all()
    document_ids = [d.id for d in docs]
    documents = []
    for d in docs:
        documents.append({
            "id": str(d.id), "original_filename": d.original_filename, "mime_type": d.mime_type,
            "detected_mime_type": d.detected_mime_type, "file_size": d.file_size, "sha256": d.sha256,
            "document_type": d.document_type, "layout_code": d.layout_code,
            "evidence_status": d.evidence_status, "processing_status": d.processing_status,
            "page_count": d.page_count, "malware_scan_status": d.malware_scan_status,
            "malware_scanned_at": _json_value(d.malware_scanned_at),
            "malware_scan_engine": d.malware_scan_engine, "created_at": _json_value(d.created_at),
            "retention_until": _json_value(d.retention_until), "legal_hold": d.legal_hold,
            "deleted_at": _json_value(d.deleted_at),
        })

    extracted_fields = []
    if document_ids:
        fields = (db.query(models.ExtractedField).filter(models.ExtractedField.document_id.in_(document_ids))
                  .order_by(models.ExtractedField.created_at, models.ExtractedField.id).all())
        extracted_fields = [{attr.key: _json_value(getattr(row, attr.key))
                             for attr in models.ExtractedField.__mapper__.column_attrs}
                            for row in fields]

    case_data = {
        "id": str(case.id), "external_case_id": case.external_case_id, "bank_id": case.bank_id,
        "bank_organization_id": _json_value(case.bank_organization_id),
        "customer_id": _json_value(case.customer_id),
        "analysis_date": _json_value(case.analysis_date), "status": case.status,
        "created_at": _json_value(case.created_at),
    }
    document_security_events = []
    if document_ids:
        security_rows = (db.query(models.DocumentSecurityEvent)
                         .filter(models.DocumentSecurityEvent.document_id.in_(document_ids))
                         .order_by(models.DocumentSecurityEvent.occurred_at, models.DocumentSecurityEvent.id).all())
        document_security_events = [{
            "id": str(row.id), "document_id": str(row.document_id), "event_type": row.event_type,
            "scan_status": row.scan_status, "engine_name": row.engine_name,
            "engine_version": row.engine_version,
            "scanned_sha256": getattr(row, "scanned_sha256", None),
            "attestation_version": getattr(row, "attestation_version", "LEGACY_UNVERIFIED"),
            "occurred_at": _json_value(row.occurred_at),
            "recorded_by": row.recorded_by,
        } for row in security_rows]

    snapshot = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "case": case_data,
        "documents": documents,
        "document_security_events": document_security_events,
        "evidence_manifest_entries": _serialize_model_rows(db, models.EvidenceManifestEntry, case.id,
                                                             order_column=models.EvidenceManifestEntry.sequence_no),
        "extracted_fields": extracted_fields,
        "transactions": _serialize_model_rows(db, models.Transaction, case.id,
                                                order_column=models.Transaction.created_at),
        "applicant_submissions": _serialize_model_rows(db, models.ApplicantSubmission, case.id,
                                                         order_column=models.ApplicantSubmission.submitted_at),
        "processing_results": _serialize_model_rows(db, models.ProcessingResult, case.id,
                                                      order_column=models.ProcessingResult.created_at),
        "pipeline_runs": _serialize_model_rows(db, models.PipelineRun, case.id,
                                                 order_column=models.PipelineRun.started_at),
        "data_quality_issues": _serialize_model_rows(db, models.DataQualityIssue, case.id,
                                                       order_column=models.DataQualityIssue.created_at),
        "payroll_evidence": _serialize_model_rows(db, models.PayrollEvidence, case.id,
                                                    order_column=models.PayrollEvidence.created_at),
        "income_ledger_months": _serialize_model_rows(db, models.IncomeLedgerMonth, case.id,
                                                        order_column=models.IncomeLedgerMonth.period_month),
        "earning_match_candidates": _serialize_model_rows(db, models.EarningMatchCandidate, case.id,
                                                            order_column=models.EarningMatchCandidate.created_at),
        "loan_applications": _serialize_model_rows(db, models.LoanApplication, case.id,
                                                     order_column=models.LoanApplication.submitted_at),
        "customer_household_profiles": _serialize_model_rows(db, models.CustomerHouseholdProfile, case.id,
                                                               order_column=models.CustomerHouseholdProfile.created_at),
        "customer_expense_declarations": _serialize_model_rows(db, models.CustomerExpenseDeclaration, case.id,
                                                                order_column=models.CustomerExpenseDeclaration.created_at),
        "customer_liability_declarations": _serialize_model_rows(db, models.CustomerLiabilityDeclaration, case.id,
                                                                  order_column=models.CustomerLiabilityDeclaration.created_at),
        "customer_salary_accounts": _serialize_model_rows(db, models.CustomerSalaryAccount, case.id,
                                                            order_column=models.CustomerSalaryAccount.created_at),
        "customer_declaration_revisions": _serialize_model_rows(db, models.CustomerDeclarationRevision, case.id,
                                                                 order_column=models.CustomerDeclarationRevision.submitted_at),
        "consent_events": _serialize_model_rows(db, models.ConsentEvent, case.id,
                                                 order_column=models.ConsentEvent.created_at,
                                                 exclude_fields={"evidence_uri"}),
        "transaction_duplicate_candidates": _serialize_model_rows(db, models.TransactionDuplicateCandidate, case.id,
                                                                    order_column=models.TransactionDuplicateCandidate.created_at),
        "evidence_reconciliation_runs": _serialize_model_rows(db, models.EvidenceReconciliationRun, case.id,
                                                                order_column=models.EvidenceReconciliationRun.created_at),
        "evidence_review_decisions": _serialize_model_rows(db, models.EvidenceReviewDecision, case.id,
                                                             order_column=models.EvidenceReviewDecision.created_at),
        "scope_consent_attestations": _serialize_model_rows(db, models.CaseScopeConsentAttestation, case.id,
                                                              order_column=models.CaseScopeConsentAttestation.attested_at),
        "input_declaration_revisions": _serialize_model_rows(db, models.CaseInputDeclarationRevision, case.id,
                                                               order_column=models.CaseInputDeclarationRevision.submitted_at),
        "input_declaration_evidence_links": _serialize_model_rows(db, models.CaseInputDeclarationEvidenceLink, case.id,
                                                                    order_column=models.CaseInputDeclarationEvidenceLink.created_at),
        "input_review_decisions": _serialize_model_rows(db, models.CaseInputReviewDecision, case.id,
                                                          order_column=models.CaseInputReviewDecision.created_at),
        "financial_input_bundles": _serialize_model_rows(db, models.CaseFinancialInputBundle, case.id,
                                                           order_column=models.CaseFinancialInputBundle.created_at),
        "proposed_schedule_references": _serialize_model_rows(db, models.CaseProposedScheduleReference, case.id,
                                                                order_column=models.CaseProposedScheduleReference.created_at),
        "business_engine_receipts": _serialize_model_rows(db, models.CaseBusinessEngineReceipt, case.id,
                                                            order_column=models.CaseBusinessEngineReceipt.received_at),
    }
    for name in ("evidence_manifest_entries", "transaction_duplicate_candidates", "evidence_reconciliation_runs",
                 "evidence_review_decisions"):
        for row in snapshot[name]:
            for key, value in list(row.items()):
                if isinstance(value, UUID):
                    row[key] = str(value)

    readiness = assess_snapshot_readiness(snapshot)
    snapshot["readiness"] = readiness
    counts = {key: len(value) for key, value in snapshot.items() if isinstance(value, list)}
    snapshot["record_counts"] = counts
    return snapshot, readiness


def get_version_state(db: Session, version_id: UUID) -> tuple[str, list[models.CaseGovernanceEvent]]:
    events = (db.query(models.CaseGovernanceEvent).filter_by(version_id=version_id)
              .order_by(models.CaseGovernanceEvent.created_at, models.CaseGovernanceEvent.id).all())
    return version_state(events), events


def get_latest_case_version(db: Session, case_id: UUID):
    return (db.query(models.CaseAnalysisVersion).filter_by(case_id=case_id)
            .order_by(models.CaseAnalysisVersion.version_no.desc()).first())
