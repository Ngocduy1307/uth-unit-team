from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.evidence_reconciliation as evidence_reconciliation
from app.evidence_reconciliation import (
    calculate_manifest_entry_hash,
    duplicate_pair_key,
    build_duplicate_pairs,
    manifest_matches_document_metadata,
    reconcile_pdf_csv_candidates,
    summarize_document_integrity,
    transaction_fingerprint,
    verify_manifest_chain,
)
from app.main import app, _record_evidence_review
from app.service import append_evidence_manifest_entry, sha256_file
from app.schemas import EvidenceReviewIn


@pytest.fixture(autouse=True)
def allow_synthetic_calibration_fixture_only(monkeypatch):
    # The production allowlist is empty; this test-only fixture exercises the
    # arithmetic comparison branch without implying a real bank calibration.
    monkeypatch.setattr(evidence_reconciliation, "APPROVED_RECONCILIATION_CALIBRATION_BASES",
                        frozenset({"CALIBRATED_TEST_FIXTURE"}))


def manifest_entry(*, sequence_no, document_id=None, previous_hash=None, received_at=None):
    case_id = uuid4()
    document_id = document_id or uuid4()
    received_at = received_at or datetime(2026, 11, 26, 12, 0, sequence_no, tzinfo=timezone.utc)
    values = dict(
        case_id=case_id, sequence_no=sequence_no, document_id=document_id,
        original_filename=f"statement-{sequence_no}.pdf", sha256=("a" if sequence_no == 1 else "b") * 64,
        mime_type="application/pdf", file_size=1024, previous_entry_hash=previous_hash,
        received_at=received_at, received_by="maker-1",
    )
    entry_hash = calculate_manifest_entry_hash(**values)
    return SimpleNamespace(**{**values, "entry_hash": entry_hash, "hash_version": "1"})


def make_pdf_fields(*, confidence_basis="CALIBRATED_TEST_FIXTURE", extraction_decision="SUGGEST"):
    values = {
        "opening_balance": ({"amount_vnd": "1000"}, "amount"),
        "closing_balance": ({"amount_vnd": "1150"}, "amount"),
        "statement_start_date": ({"date": "2026-01-01"}, "date"),
        "statement_end_date": ({"date": "2026-01-31"}, "date"),
    }
    fields = []
    for index, (name, (normalized, _)) in enumerate(values.items(), start=1):
        fields.append(SimpleNamespace(
            field_name=name, normalized_value=normalized, validation_status="VALID",
            extraction_decision=extraction_decision, confidence_basis=confidence_basis,
            page_number=1, bbox={"x": 1, "y": index * 10, "width": 10, "height": 5},
        ))
    return fields


def tx(row, day, amount, direction):
    return SimpleNamespace(source_row=row, transaction_date=day,
                           amount_vnd=Decimal(str(amount)), direction=direction)


def test_manifest_hash_chain_is_valid_and_detects_tampering():
    first = manifest_entry(sequence_no=1)
    second = manifest_entry(sequence_no=2, previous_hash=first.entry_hash)
    # Chain entries must share a case ID.
    second.case_id = first.case_id
    second.entry_hash = calculate_manifest_entry_hash(
        case_id=second.case_id, sequence_no=second.sequence_no, document_id=second.document_id,
        original_filename=second.original_filename, sha256=second.sha256, mime_type=second.mime_type,
        file_size=second.file_size, previous_entry_hash=second.previous_entry_hash,
        received_at=second.received_at, received_by=second.received_by,
    )
    verified = verify_manifest_chain([second, first])
    assert verified["valid"] is True
    assert verified["entry_count"] == 2
    second.sha256 = "c" * 64
    tampered = verify_manifest_chain([first, second])
    assert tampered["valid"] is False
    assert "ENTRY_HASH_MISMATCH" in {x["code"] for x in tampered["errors"]}


def test_manifest_chain_detects_missing_sequence_or_wrong_previous_hash():
    first = manifest_entry(sequence_no=1)
    third = manifest_entry(sequence_no=3, previous_hash="f" * 64)
    third.case_id = first.case_id
    result = verify_manifest_chain([first, third])
    codes = {x["code"] for x in result["errors"]}
    assert "SEQUENCE_GAP" in codes
    assert "PREVIOUS_HASH_MISMATCH" in codes


def test_transaction_fingerprint_normalizes_description_and_absolute_amount():
    one = transaction_fingerprint("2026-01-01", Decimal("-100.00"), "DEBIT", "  ATM   CASH ")
    two = transaction_fingerprint("2026-01-01", Decimal("100"), "DEBIT", "atm cash")
    assert one == two
    assert transaction_fingerprint("2026-01-01", 100, "CREDIT", "atm cash") != one
    assert transaction_fingerprint("bad-date", 100, "DEBIT", "atm cash") is None
    assert transaction_fingerprint("2026-01-01", "NaN", "DEBIT", "atm cash") is None


def test_duplicate_pair_key_is_order_independent():
    case_id, a, b = uuid4(), uuid4(), uuid4()
    assert duplicate_pair_key(case_id, a, b) == duplicate_pair_key(case_id, b, a)


def test_duplicate_pair_builder_is_bounded_and_preserves_source_pair_ids():
    case_id = uuid4()
    rows = [SimpleNamespace(id=uuid4(), transaction_date="2026-01-01", amount_vnd=Decimal("100"),
                            direction="DEBIT", description="Coffee", source_row=i)
            for i in range(1, 5)]
    pairs, truncated = build_duplicate_pairs(case_id, rows, max_matches_per_transaction=1)
    assert len(pairs) == 3
    assert truncated == 3
    assert all(item["left_transaction_id"] != item["right_transaction_id"] for item in pairs)
    assert len({item["candidate_key"] for item in pairs}) == 3
    with pytest.raises(ValueError):
        build_duplicate_pairs(case_id, rows, max_matches_per_transaction=0)


def test_manifest_integrity_compares_all_receipt_metadata_and_reports_completeness_separately():
    entry = manifest_entry(sequence_no=1)
    doc = SimpleNamespace(id=entry.document_id, case_id=entry.case_id,
                          original_filename=entry.original_filename, sha256=entry.sha256,
                          mime_type=entry.mime_type, file_size=entry.file_size)
    assert manifest_matches_document_metadata(entry, doc)
    doc.mime_type = "application/octet-stream"
    assert not manifest_matches_document_metadata(entry, doc)
    summary = summarize_document_integrity([
        {"manifested": True, "manifest_metadata_integrity": "MATCH", "stored_bytes_integrity": "MATCH"},
        {"manifested": False, "manifest_metadata_integrity": "UNMANIFESTED", "stored_bytes_integrity": "MATCH"},
    ])
    assert summary["all_manifest_metadata_match"] is False
    assert summary["all_documents_manifested"] is False
    assert summary["unmanifested_document_count"] == 1


def test_pdf_csv_reconciliation_returns_match_candidate_but_not_verified():
    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(),
        csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT"), tx(3, "2026-01-04", 50, "DEBIT")],
        tolerance_vnd=Decimal("0"),
    )
    assert result["status"] == "BALANCE_MATCH_CANDIDATE"
    assert result["arithmetic_candidate_status"] == "BALANCE_MATCH_CANDIDATE"
    assert result["computed_closing_balance_vnd"] == "1150"
    assert result["variance_vnd"] == "0"
    assert result["maker_review_required"] is True
    assert result["account_ownership_verified"] is False
    assert result["statement_authenticity_verified"] is False
    assert result["authority"] == "DATA_AI_CANDIDATE_ONLY"


def test_pdf_csv_reconciliation_abstains_for_uncalibrated_pdf_extraction():
    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(confidence_basis="NATIVE_TEXT_LAYER_UNCALIBRATED"),
        csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT"), tx(3, "2026-01-04", 50, "DEBIT")],
    )
    assert result["status"] == "ABSTAINED"
    assert result["arithmetic_candidate_status"] == "BALANCE_MATCH_CANDIDATE"
    assert len(result["source_review_notes"]) == 4

    # A generic/manual label is not a calibration record either.
    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(confidence_basis="MANUAL"),
        csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT"), tx(3, "2026-01-04", 50, "DEBIT")],
    )
    assert result["status"] == "ABSTAINED"

    # A name that merely starts with CALIBRATED_ is not an approved allowlist entry.
    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(confidence_basis="CALIBRATED_UNAPPROVED"),
        csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT"), tx(3, "2026-01-04", 50, "DEBIT")],
    )
    assert result["status"] == "ABSTAINED"


def test_pdf_csv_reconciliation_detects_balance_variance_candidate():
    fields = make_pdf_fields()
    fields[1].normalized_value = {"amount_vnd": "1200"}
    result = reconcile_pdf_csv_candidates(
        pdf_fields=fields,
        csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT"), tx(3, "2026-01-04", 50, "DEBIT")],
    )
    assert result["status"] == "BALANCE_VARIANCE_CANDIDATE"
    assert result["variance_vnd"] == "50"


def test_pdf_csv_reconciliation_requires_unique_fields_and_source_anchors():
    fields = make_pdf_fields()
    fields.append(fields[0])
    result = reconcile_pdf_csv_candidates(pdf_fields=fields, csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT")])
    assert result["status"] == "INCOMPLETE"
    assert "AMBIGUOUS_OPENING_BALANCE" in result["errors"]

    fields = make_pdf_fields()
    fields[0].bbox = None
    result = reconcile_pdf_csv_candidates(pdf_fields=fields, csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT")])
    assert result["status"] == "INCOMPLETE"
    assert "MISSING_OR_INVALID_SOURCE_ANCHOR_OPENING_BALANCE" in result["errors"]

    fields = make_pdf_fields()
    fields[0].bbox["width"] = 0
    result = reconcile_pdf_csv_candidates(pdf_fields=fields, csv_transactions=[tx(2, "2026-01-03", 200, "CREDIT")])
    assert result["status"] == "INCOMPLETE"
    assert "MISSING_OR_INVALID_SOURCE_ANCHOR_OPENING_BALANCE" in result["errors"]


def test_pdf_csv_reconciliation_rejects_invalid_period_and_incomplete_csv_rows():
    fields = make_pdf_fields()
    fields[2].normalized_value = {"date": "2026-02-01"}
    fields[3].normalized_value = {"date": "2026-01-01"}
    result = reconcile_pdf_csv_candidates(pdf_fields=fields, csv_transactions=[tx(2, "2026-01-03", 100, "CREDIT")])
    assert result["status"] == "INCOMPLETE"
    assert result["errors"] == ["STATEMENT_PERIOD_START_AFTER_END"]

    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(),
        csv_transactions=[tx(2, "not-a-date", 200, "CREDIT")],
    )
    assert result["status"] == "INCOMPLETE"
    assert result["invalid_row_count"] == 1

    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(),
        csv_transactions=[tx(3, "2026-01-03", "NaN", "CREDIT")],
    )
    assert result["status"] == "INCOMPLETE"
    assert result["invalid_row_count"] == 1


def test_pdf_csv_reconciliation_filters_rows_outside_statement_period():
    result = reconcile_pdf_csv_candidates(
        pdf_fields=make_pdf_fields(),
        csv_transactions=[tx(2, "2025-12-31", 500, "CREDIT"), tx(3, "2026-01-03", 200, "CREDIT"),
                          tx(4, "2026-01-04", 50, "DEBIT")],
    )
    assert result["status"] == "BALANCE_MATCH_CANDIDATE"
    assert result["included_transaction_count"] == 2
    assert result["rows_outside_statement_period"] == 1


def test_pdf_csv_reconciliation_validates_tolerance():
    with pytest.raises(ValueError):
        reconcile_pdf_csv_candidates(pdf_fields=make_pdf_fields(), csv_transactions=[], tolerance_vnd="-1")
    with pytest.raises(ValueError):
        reconcile_pdf_csv_candidates(pdf_fields=make_pdf_fields(), csv_transactions=[], tolerance_vnd="1000001")
    with pytest.raises(ValueError):
        reconcile_pdf_csv_candidates(pdf_fields=make_pdf_fields(), csv_transactions=[], tolerance_vnd="NaN")


def test_v9_3_2_routes_are_published_in_openapi():
    paths = app.openapi()["paths"]
    assert "/api/v1/cases/{case_id}/evidence/provenance" in paths
    assert "/api/v1/cases/{case_id}/evidence/reconciliations" in paths
    assert "/api/v1/cases/{case_id}/evidence/duplicate-candidates" in paths
    assert "/api/v1/cases/{case_id}/evidence/reconciliations/{run_id}/review" in paths
    assert "/api/v1/cases/{case_id}/evidence/duplicate-candidates/{candidate_id}/review" in paths


def test_evidence_review_rejects_non_maker_roles():
    with pytest.raises(HTTPException) as error:
        _record_evidence_review(case_id=uuid4(), target_type="RECONCILIATION_RUN", target_id=uuid4(),
            payload=EvidenceReviewIn(decision_code="CONFIRMED_MATCH", reason="Reviewed source evidence"),
            db=None, actor="staff", roles={"BANK_STAFF"})
    assert error.value.status_code == 403


def test_evidence_review_rejects_short_reason_and_invalid_decision():
    with pytest.raises(ValueError):
        EvidenceReviewIn(decision_code="CONFIRMED_MATCH", reason="short")
    with pytest.raises(ValueError):
        EvidenceReviewIn(decision_code="CONFIRMED_MATCH", reason="        ")
    with pytest.raises(HTTPException) as error:
        _record_evidence_review(case_id=uuid4(), target_type="RECONCILIATION_RUN", target_id=uuid4(),
            payload=EvidenceReviewIn(decision_code="AUTO_ACCEPT", reason="Maker reviewed this source"),
            db=None, actor="maker", roles={"MAKER"})
    assert error.value.status_code == 422


def test_duplicate_confirmation_is_blocked_when_source_documents_are_missing():
    class StubQuery:
        def __init__(self, rows):
            self.rows = rows
        def filter(self, *args, **kwargs):
            return self
        def filter_by(self, **kwargs):
            return self
        def all(self):
            return self.rows
        def first(self):
            return self.rows[0] if self.rows else None

    class StubDB:
        def query(self, model):
            from app import models
            if model is models.TransactionDuplicateCandidate:
                return StubQuery([SimpleNamespace(left_transaction_id=uuid4(), right_transaction_id=uuid4())])
            if model is models.Transaction:
                return StubQuery([SimpleNamespace(document_id=None), SimpleNamespace(document_id=None)])
            return StubQuery([])

    with pytest.raises(HTTPException) as error:
        _record_evidence_review(
            case_id=uuid4(), target_type="TRANSACTION_DUPLICATE", target_id=uuid4(),
            payload=EvidenceReviewIn(decision_code="CONFIRMED_DUPLICATE", reason="Both source rows were reviewed"),
            db=StubDB(), actor="maker", roles={"MAKER"},
        )
    assert error.value.status_code == 409


def test_manifest_append_service_assigns_next_sequence_and_checks_storage(tmp_path):
    from app import models
    content = b"signed-evidence-source"
    source_path = tmp_path / "evidence.pdf"
    source_path.write_bytes(content)
    case = SimpleNamespace(id=uuid4())
    document = SimpleNamespace(
        id=uuid4(), case_id=case.id, stored_path=str(source_path),
        original_filename="evidence.pdf", sha256=sha256_file(source_path),
        mime_type="application/pdf", file_size=len(content),
    )

    class Query:
        def __init__(self, rows=()):
            self.rows = list(rows)
        def filter(self, *args, **kwargs):
            return self
        def filter_by(self, **kwargs):
            return self
        def with_for_update(self):
            return self
        def one(self):
            return SimpleNamespace(id=case.id)
        def order_by(self, *args, **kwargs):
            return self
        def all(self):
            return self.rows

    class DB:
        def __init__(self):
            self.added = []
        def query(self, model):
            if model is models.EvidenceManifestEntry:
                return Query([existing_entry])
            return Query()
        def add(self, obj):
            self.added.append(obj)
        def flush(self):
            pass

    received_at = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    existing_values = dict(
        case_id=case.id, sequence_no=1, document_id=uuid4(), original_filename="prior.pdf",
        sha256="a" * 64, mime_type="application/pdf", file_size=10,
        previous_entry_hash=None, received_at=received_at, received_by="maker-1",
    )
    existing_entry = SimpleNamespace(
        **existing_values,
        entry_hash=calculate_manifest_entry_hash(**existing_values),
    )
    db = DB()
    entry = append_evidence_manifest_entry(db, case, document, "maker-2")
    assert entry.sequence_no == 2
    assert entry.previous_entry_hash == existing_entry.entry_hash
    assert entry.sha256 == document.sha256
    assert db.added == [entry]


def test_manifest_append_service_refuses_to_extend_tampered_chain(tmp_path):
    from app import models
    source_path = tmp_path / "evidence.pdf"
    source_path.write_bytes(b"source")
    case_id = uuid4()
    document = SimpleNamespace(
        id=uuid4(), case_id=case_id, stored_path=str(source_path),
        original_filename="evidence.pdf", sha256=sha256_file(source_path),
        mime_type="application/pdf", file_size=6,
    )
    existing = manifest_entry(sequence_no=1)
    existing.case_id = case_id
    existing.sha256 = "f" * 64  # invalidates the stored entry hash

    class Query:
        def __init__(self, rows=()): self.rows = list(rows)
        def filter(self, *args, **kwargs): return self
        def filter_by(self, **kwargs): return self
        def with_for_update(self): return self
        def one(self): return SimpleNamespace(id=case_id)
        def order_by(self, *args, **kwargs): return self
        def all(self): return self.rows

    class DB:
        def query(self, model):
            return Query([existing] if model is models.EvidenceManifestEntry else [])
        def add(self, obj): raise AssertionError("invalid chain must not append")
        def flush(self): raise AssertionError("invalid chain must not flush")

    with pytest.raises(ValueError, match="invalid manifest hash chain"):
        append_evidence_manifest_entry(DB(), SimpleNamespace(id=case_id), document, "maker")
