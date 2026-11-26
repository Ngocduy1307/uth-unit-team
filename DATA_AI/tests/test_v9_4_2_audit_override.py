from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import models
from app.audit_governance import (
    ZERO_HASH, audit_payload_from_values, calculate_audit_entry_sha256,
    require_named_authority, verify_audit_chain,
)
from app.main import app
from app.schemas import NamedAuthorityReviewIn, OverrideRequestIn, OverrideWithdrawIn


def _audit_row(sequence, previous_hash, *, reason="checked source", created_at=None):
    values = dict(
        case_id=uuid4(), bank_id="BANK-01", sequence_no=sequence,
        actor_id="maker-01", actor_role="MAKER", action_code="CASE_VERSION_FROZEN",
        entity_type="case_analysis_version", entity_id="version-01", version_id=None,
        request_id=None, reason=reason, before_sha256=None, after_sha256=None,
        details={"scope": "DATA_AI_EVIDENCE_INPUTS_ONLY"},
        previous_entry_sha256=previous_hash,
        created_at=created_at or datetime(2026, 11, 26, tzinfo=timezone.utc),
    )
    return SimpleNamespace(**values, entry_sha256=calculate_audit_entry_sha256(values))


def test_audit_chain_verifies_complete_sequence_and_detects_content_tampering():
    first = _audit_row(1, ZERO_HASH)
    second = _audit_row(2, first.entry_sha256, created_at=datetime(2026, 11, 26, 1, tzinfo=timezone.utc))
    result = verify_audit_chain([first, second])
    assert result["valid"] is True
    assert result["verified_entries"] == 2
    assert result["head_sha256"] == second.entry_sha256
    second.reason = "silently edited"
    tampered = verify_audit_chain([first, second])
    assert tampered["valid"] is False
    assert tampered["first_invalid_sequence"] == 2
    assert tampered["reason"] == "ENTRY_HASH_MISMATCH"


def test_audit_chain_detects_sequence_gap_and_previous_hash_rewrite():
    first = _audit_row(1, ZERO_HASH)
    third = _audit_row(3, first.entry_sha256)
    assert verify_audit_chain([first, third])["reason"] == "SEQUENCE_GAP"
    bad_second = _audit_row(2, "f" * 64)
    assert verify_audit_chain([first, bad_second])["reason"] == "PREVIOUS_HASH_MISMATCH"


def test_named_authority_is_dedicated_and_not_maker_checker_admin_or_service():
    require_named_authority("authority-01", {"NAMED_AUTHORITY", "BANK_POLICY_OWNER"})
    for actor, roles in [
        ("maker", {"NAMED_AUTHORITY", "MAKER"}),
        ("checker", {"NAMED_AUTHORITY", "CHECKER"}),
        ("admin", {"NAMED_AUTHORITY", "BANK_ADMIN"}),
        ("service", {"NAMED_AUTHORITY", "DATA_AI_SERVICE"}),
        ("", {"NAMED_AUTHORITY"}),
        ("ordinary", {"BANK_POLICY_OWNER"}),
    ]:
        with pytest.raises(HTTPException) as exc:
            require_named_authority(actor, roles)
        assert exc.value.status_code == 403


def test_override_proposal_requires_provisional_evidence_and_bounded_payload():
    payload = OverrideRequestIn(
        request_kind="POLICY_EXCEPTION", exception_code="POLICY_THRESHOLD_EXCEPTION",
        policy_reference="POL-RETAIL-01", policy_version="2026.3",
        reason="Request a controlled exception for documented case facts",
        requested_change={"parameter": "threshold_x", "proposed_value": "0.42"},
        impact_summary={"affected_rule": "rule-1"}, evidence_refs=[uuid4()],
    )
    assert payload.request_kind == "POLICY_EXCEPTION"
    with pytest.raises(ValidationError):
        OverrideRequestIn(
            request_kind="OVERRIDE", exception_code="bad code", policy_reference="P1", policy_version="1",
            reason="A sufficiently long reason", requested_change={"x": 1}, evidence_refs=[uuid4()],
        )
    with pytest.raises(ValidationError):
        OverrideRequestIn(
            request_kind="OVERRIDE", exception_code="LIMIT_OVERRIDE", policy_reference="P1", policy_version="1",
            reason="A sufficiently long reason", requested_change={"x": "a" * 9000}, evidence_refs=[uuid4()],
        )
    with pytest.raises(ValidationError):
        OverrideRequestIn(
            request_kind="OVERRIDE", exception_code="LIMIT_OVERRIDE", policy_reference="P1", policy_version="1",
            reason="A sufficiently long reason", requested_change={"x": 1}, evidence_refs=[],
        )


def test_named_authority_approval_requires_future_aware_expiry_and_grant_refs():
    valid_until = datetime.now(timezone.utc) + timedelta(days=10)
    payload = NamedAuthorityReviewIn(
        decision="APPROVE", reason="Approved within the assigned delegation scope",
        authority_grant_ref="SSO-GRANT-123", authority_scope_ref="SCOPE-RETAIL-01",
        valid_until=valid_until,
    )
    assert payload.decision == "APPROVE"
    with pytest.raises(ValidationError):
        NamedAuthorityReviewIn(
            decision="APPROVE", reason="Approved within the assigned delegation scope",
            authority_grant_ref="SSO-GRANT-123", authority_scope_ref="SCOPE-RETAIL-01",
        )
    with pytest.raises(ValidationError):
        NamedAuthorityReviewIn(
            decision="REJECT", reason="Rejected because policy scope does not match",
            authority_grant_ref="SSO-GRANT-123", authority_scope_ref="SCOPE-RETAIL-01",
            valid_until=valid_until,
        )
    with pytest.raises(ValidationError):
        OverrideWithdrawIn(reason="short")


def test_v942_routes_are_published_and_protected_by_internal_auth_contract():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/cases/{case_id}/governance/versions/{version_id}/override-requests",
        "/api/v1/cases/{case_id}/governance/override-requests",
        "/api/v1/cases/{case_id}/governance/override-requests/{request_id}",
        "/api/v1/cases/{case_id}/governance/override-requests/{request_id}/authority-review",
        "/api/v1/cases/{case_id}/governance/override-requests/{request_id}/withdraw",
        "/api/v1/cases/{case_id}/governance/audit-trail",
        "/api/v1/cases/{case_id}/governance/audit-trail/verify",
    }
    assert expected.issubset(paths)
    for path in expected:
        for operation in paths[path].values():
            header_names = {p["name"].lower() for p in operation.get("parameters", []) if p.get("in") == "header"}
            assert {"x-internal-service-token", "x-service-assertion"}.issubset(header_names)


def test_v942_orm_tables_and_indexes_align_with_v15_migration():
    assert models.CaseAuditEntry.__tablename__ == "case_audit_entries"
    assert models.CaseOverrideRequest.__tablename__ == "case_override_requests"
    assert models.CaseOverrideEvent.__tablename__ == "case_override_events"
    request_constraints = {c.name for c in models.CaseOverrideRequest.__table__.constraints}
    assert "uq_case_override_version_proposal" in request_constraints
    expected = {
        "case_audit_entries": {"ix_case_audit_case_created", "ix_case_audit_case_action"},
        "case_override_requests": {"ix_case_override_case_created", "ix_case_override_version_created"},
        "case_override_events": {"ix_case_override_event_request_created",
                                  "uq_case_override_requested_per_request", "uq_case_override_terminal_per_request"},
    }
    for table_name, indexes in expected.items():
        assert indexes.issubset({idx.name for idx in models.Base.metadata.tables[table_name].indexes})


def test_v15_migration_declares_append_only_audit_override_and_authority_constraints():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sql = (root / "db/migration/V15__audit_trail_override_authority.sql").read_text(encoding="utf-8")
    for token in [
        "CREATE TABLE case_audit_entries", "CREATE TABLE case_override_requests",
        "CREATE TABLE case_override_events", "trg_case_audit_append",
        "trg_case_audit_entry_immutable", "trg_case_override_request_immutable",
        "trg_case_override_event_immutable", "ck_case_override_authority_independence",
        "NAMED_AUTHORITY", "uq_case_override_terminal_per_request", "uq_case_override_version_proposal",
    ]:
        assert token in sql
    assert "override" in sql.lower() and "does not execute" in sql.lower()


def test_override_proposal_hash_covers_maker_identity_version_and_evidence_refs():
    from app.main import _override_proposal_payload
    from app.audit_governance import calculate_audit_entry_sha256
    case_id, version_id, evidence_ref = uuid4(), uuid4(), uuid4()
    payload = OverrideRequestIn(
        request_kind="OVERRIDE", exception_code="INCOME_POLICY_OVERRIDE",
        policy_reference="POL-INCOME-01", policy_version="2026.2",
        reason="Documented exception request with evidence support",
        requested_change={"parameter": "income_cap", "value": "45000000"},
        impact_summary={"impact": "requires authority review"}, evidence_refs=[evidence_ref],
    )
    maker_payload = _override_proposal_payload(
        payload, case_id=case_id, version_id=version_id,
        version_sha256="a" * 64, requested_by="maker-01")
    stored_record = models.CaseOverrideRequest(
        case_id=case_id, version_id=version_id, version_sha256="a" * 64,
        request_kind=payload.request_kind, exception_code=payload.exception_code,
        policy_reference=payload.policy_reference, policy_version=payload.policy_version,
        requested_by="maker-01", reason=payload.reason,
        requested_change=payload.requested_change, impact_summary=payload.impact_summary,
        evidence_refs=[str(evidence_ref)],
    )
    persisted_payload = _override_proposal_payload(stored_record)
    assert maker_payload == persisted_payload
    assert calculate_audit_entry_sha256(maker_payload) == calculate_audit_entry_sha256(persisted_payload)


def test_postgres_ddl_compiles_for_all_v15_orm_tables():
    from sqlalchemy.schema import CreateTable, CreateIndex
    from sqlalchemy.dialects import postgresql
    for table_name in ("case_audit_entries", "case_override_requests", "case_override_events"):
        table = models.Base.metadata.tables[table_name]
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table_name}" in ddl
        for index in table.indexes:
            compiled = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            assert "CREATE" in compiled


def test_v15_evidence_reference_trigger_checks_same_case_records():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sql = (root / "db/migration/V15__audit_trail_override_authority.sql").read_text(encoding="utf-8")
    assert "validate_case_override_evidence_refs" in sql
    assert "ck_case_override_evidence_same_case" in sql
    for table_name in ["documents", "transactions", "evidence_manifest_entries",
                       "evidence_reconciliation_runs", "transaction_duplicate_candidates",
                       "evidence_review_decisions"]:
        assert f"FROM {table_name}" in sql


def test_override_proposal_reader_is_narrower_than_audit_ledger_reader(monkeypatch):
    from app.main import _case_override_reader_context
    fake_case = SimpleNamespace(id=uuid4(), bank_id="BANK-01")
    monkeypatch.setattr("app.main._case_audit_context", lambda *args: (
        fake_case, "audit-admin", {"BANK_ADMIN"}))
    with pytest.raises(HTTPException) as exc:
        _case_override_reader_context(fake_case.id, None, "audit-admin", None, "BANK-01")
    assert exc.value.status_code == 403

    monkeypatch.setattr("app.main._case_audit_context", lambda *args: (
        fake_case, "checker-01", {"CHECKER"}))
    case, actor, roles = _case_override_reader_context(
        fake_case.id, None, "checker-01", None, "BANK-01")
    assert case is fake_case
    assert actor == "checker-01"
    assert roles == {"CHECKER"}


def test_named_authority_scope_revalidates_role_and_bank_without_widening_general_case_access(monkeypatch):
    from app.main import _assert_case_named_authority_scope, _assert_case_bank_scope
    case = SimpleNamespace(bank_id="BANK-01")
    monkeypatch.setattr("app.main.trusted_actor_context", lambda *args, **kwargs: (
        "authority-01", {"NAMED_AUTHORITY"}, "BANK-01"))
    scoped = []
    monkeypatch.setattr("app.main.enforce_bank_scope", lambda *args, **kwargs: scoped.append(args))
    actor, roles = _assert_case_named_authority_scope(
        case, "authority-01", "NAMED_AUTHORITY", "BANK-01")
    assert actor == "authority-01"
    assert roles == {"NAMED_AUTHORITY"}
    assert scoped and scoped[0][0] == "BANK-01"
    with pytest.raises(HTTPException) as exc:
        _assert_case_bank_scope(case, "authority-01", "NAMED_AUTHORITY", "BANK-01")
    assert exc.value.status_code == 403


def test_override_proposal_reader_rejects_dual_maker_checker_identity(monkeypatch):
    from app.main import _case_override_reader_context
    fake_case = SimpleNamespace(id=uuid4(), bank_id="BANK-01")
    monkeypatch.setattr("app.main._case_audit_context", lambda *args: (
        fake_case, "dual-actor", {"MAKER", "CHECKER"}))
    with pytest.raises(HTTPException) as exc:
        _case_override_reader_context(fake_case.id, None, "dual-actor", None, "BANK-01")
    assert exc.value.status_code == 403
