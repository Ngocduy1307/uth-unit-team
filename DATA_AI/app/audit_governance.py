"""V9.4.2 hash-chained case audit and override-governance helpers.

This is a DATA-AI evidence/approval-recording layer only. It does not validate
bank delegation rules, evaluate policy, execute an override, or complete a
Camunda task. Backend/SSO and the bank's policy/authority service remain the
sources of truth for those decisions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models

ZERO_HASH = "0" * 64
_ACTION_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def _safe_json(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe_json(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_audit_bytes(payload: dict) -> bytes:
    return json.dumps(_safe_json(payload), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def audit_payload_from_values(*, case_id, bank_id, sequence_no, actor_id, actor_role,
                               action_code, entity_type, entity_id, version_id,
                               request_id, reason, before_sha256, after_sha256,
                               details, previous_entry_sha256, created_at) -> dict:
    return {
        "case_id": str(case_id), "bank_id": str(bank_id), "sequence_no": int(sequence_no),
        "actor_id": str(actor_id), "actor_role": str(actor_role),
        "action_code": str(action_code), "entity_type": str(entity_type),
        "entity_id": str(entity_id), "version_id": str(version_id) if version_id else None,
        "request_id": str(request_id) if request_id else None,
        "reason": reason, "before_sha256": before_sha256, "after_sha256": after_sha256,
        "details": _safe_json(details or {}),
        "previous_entry_sha256": str(previous_entry_sha256),
        "created_at": _safe_json(created_at),
    }


def calculate_audit_entry_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_audit_bytes(payload)).hexdigest()


def append_case_audit_entry(db: Session, *, case: models.Case, actor_id: str,
                            actor_role: str, action_code: str, entity_type: str,
                            entity_id: str, request_id: UUID | None = None,
                            version_id: UUID | None = None, reason: str | None = None,
                            before_sha256: str | None = None, after_sha256: str | None = None,
                            details: dict | None = None,
                            created_at: datetime | None = None) -> models.CaseAuditEntry:
    """Append one hash-linked event; caller commits it with the business command."""
    if not _ACTION_RE.fullmatch(action_code):
        raise ValueError("action_code must be a stable uppercase audit code")
    # Serialize writers by locking the authoritative case row before reading the head.
    locked = (db.query(models.Case).filter_by(id=case.id)
              .populate_existing().with_for_update().first())
    if locked is None:
        raise HTTPException(404, "Case not found")
    latest = (db.query(models.CaseAuditEntry).filter_by(case_id=case.id)
              .order_by(models.CaseAuditEntry.sequence_no.desc()).first())
    sequence_no = (latest.sequence_no + 1) if latest else 1
    previous_hash = latest.entry_sha256 if latest else ZERO_HASH
    if request_id is not None and not isinstance(request_id, UUID):
        request_id = UUID(str(request_id))
    occurred_at = created_at or datetime.now(timezone.utc)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    payload = audit_payload_from_values(
        case_id=case.id, bank_id=locked.bank_id, sequence_no=sequence_no,
        actor_id=actor_id, actor_role=actor_role, action_code=action_code,
        entity_type=entity_type, entity_id=entity_id, version_id=version_id,
        request_id=request_id, reason=reason, before_sha256=before_sha256,
        after_sha256=after_sha256, details=details or {},
        previous_entry_sha256=previous_hash, created_at=occurred_at,
    )
    row = models.CaseAuditEntry(
        case_id=case.id, bank_id=locked.bank_id, sequence_no=sequence_no,
        actor_id=actor_id, actor_role=actor_role, action_code=action_code,
        entity_type=entity_type, entity_id=entity_id, version_id=version_id,
        request_id=request_id, reason=reason, before_sha256=before_sha256,
        after_sha256=after_sha256, details=details or {},
        previous_entry_sha256=previous_hash,
        entry_sha256=calculate_audit_entry_sha256(payload), created_at=occurred_at,
    )
    db.add(row)
    db.flush()
    return row


def audit_entry_payload(row: models.CaseAuditEntry) -> dict:
    return audit_payload_from_values(
        case_id=row.case_id, bank_id=row.bank_id, sequence_no=row.sequence_no,
        actor_id=row.actor_id, actor_role=row.actor_role, action_code=row.action_code,
        entity_type=row.entity_type, entity_id=row.entity_id, version_id=row.version_id,
        request_id=row.request_id, reason=row.reason, before_sha256=row.before_sha256,
        after_sha256=row.after_sha256, details=row.details,
        previous_entry_sha256=row.previous_entry_sha256, created_at=row.created_at,
    )


def verify_audit_chain(rows: list[models.CaseAuditEntry]) -> dict:
    expected_sequence = 1
    previous_hash = ZERO_HASH
    for row in rows:
        if row.sequence_no != expected_sequence:
            return {"valid": False, "verified_entries": expected_sequence - 1,
                    "first_invalid_sequence": row.sequence_no, "reason": "SEQUENCE_GAP"}
        if not hmac.compare_digest(str(row.previous_entry_sha256), previous_hash):
            return {"valid": False, "verified_entries": expected_sequence - 1,
                    "first_invalid_sequence": row.sequence_no, "reason": "PREVIOUS_HASH_MISMATCH"}
        expected_hash = calculate_audit_entry_sha256(audit_entry_payload(row))
        if not hmac.compare_digest(str(row.entry_sha256), expected_hash):
            return {"valid": False, "verified_entries": expected_sequence - 1,
                    "first_invalid_sequence": row.sequence_no, "reason": "ENTRY_HASH_MISMATCH"}
        previous_hash = row.entry_sha256
        expected_sequence += 1
    return {"valid": True, "verified_entries": len(rows),
            "first_invalid_sequence": None, "reason": None,
            "head_sha256": previous_hash}


def require_named_authority(actor_id: str, roles: set[str]) -> None:
    denied = {"MAKER", "CHECKER", "BANK_ADMIN", "SYSTEM_ADMIN", "DATA_AI_STAFF", "DATA_AI_SERVICE"}
    if not actor_id or not actor_id.strip() or "NAMED_AUTHORITY" not in roles or roles.intersection(denied):
        raise HTTPException(403, "A dedicated Named Authority identity is required")


def override_request_state(db: Session, request: models.CaseOverrideRequest) -> tuple[str, list[models.CaseOverrideEvent]]:
    events = (db.query(models.CaseOverrideEvent).filter_by(request_id=request.id, case_id=request.case_id)
              .order_by(models.CaseOverrideEvent.created_at, models.CaseOverrideEvent.id).all())
    terminal = next((e for e in reversed(events) if e.event_type in {"APPROVED", "REJECTED", "WITHDRAWN"}), None)
    if terminal:
        if terminal.event_type == "APPROVED" and terminal.valid_until and terminal.valid_until <= datetime.now(timezone.utc):
            return "EXPIRED", events
        return terminal.event_type, events
    version = (db.query(models.CaseAnalysisVersion)
               .filter_by(id=request.version_id, case_id=request.case_id).first())
    if version is None:
        return "INTEGRITY_ERROR", events
    from app.governance import get_version_state
    state, _ = get_version_state(db, version.id)
    if state in {"RETURNED_TO_MAKER", "SUPERSEDED"}:
        return "STALE", events
    if state == "CHECKER_CONFIRMED":
        return "PENDING_AUTHORITY", events
    return "PENDING_CHECKER", events


def validate_case_evidence_refs(db: Session, case_id: UUID, evidence_refs: list[UUID]) -> None:
    if not evidence_refs:
        raise HTTPException(422, "At least one same-case supporting evidence reference is required")
    ids = set(evidence_refs)
    found: set[UUID] = set()
    for model in (models.Document, models.Transaction, models.EvidenceReconciliationRun,
                  models.TransactionDuplicateCandidate, models.EvidenceReviewDecision):
        rows = db.query(model.id).filter(model.case_id == case_id, model.id.in_(ids)).all()
        found.update(row[0] for row in rows)
    doc_ids = [row[0] for row in db.query(models.Document.id).filter_by(case_id=case_id).all()]
    if doc_ids:
        rows = db.query(models.ExtractedField.id).filter(models.ExtractedField.document_id.in_(doc_ids),
                                                         models.ExtractedField.id.in_(ids)).all()
        found.update(row[0] for row in rows)
    manifest_rows = db.query(models.EvidenceManifestEntry.id).filter(
        models.EvidenceManifestEntry.case_id == case_id,
        models.EvidenceManifestEntry.id.in_(ids)).all()
    found.update(row[0] for row in manifest_rows)
    if found != ids:
        raise HTTPException(422, {"message": "Supporting evidence contains unknown or cross-case references",
                                  "invalid_reference_count": len(ids - found)})
