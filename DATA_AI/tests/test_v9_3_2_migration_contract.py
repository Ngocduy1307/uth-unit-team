from pathlib import Path

from app import models

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migration" / "V13__evidence_provenance_reconciliation.sql"


def test_v13_migration_creates_manifest_reconciliation_duplicate_and_review_ledgers():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ["evidence_manifest_entries", "transaction_duplicate_candidates",
                  "evidence_reconciliation_runs", "evidence_review_decisions"]:
        assert f"CREATE TABLE {table}" in sql
    assert "UNIQUE(case_id, sequence_no)" in sql
    assert "UNIQUE(left_transaction_id, right_transaction_id)" in sql
    assert "reject_evidence_ledger_mutation" in sql
    assert "BEFORE UPDATE OR DELETE ON evidence_manifest_entries" in sql
    assert "BEFORE UPDATE OR DELETE ON evidence_review_decisions" in sql
    assert "uq_evidence_manifest_document" in sql
    assert "ck_evidence_review_target_link" in sql
    assert "ck_evidence_review_decision_code" in sql


def test_v13_orm_models_are_registered_and_key_constraints_exist():
    assert models.EvidenceManifestEntry.__tablename__ == "evidence_manifest_entries"
    assert models.TransactionDuplicateCandidate.__tablename__ == "transaction_duplicate_candidates"
    assert models.EvidenceReconciliationRun.__tablename__ == "evidence_reconciliation_runs"
    assert models.EvidenceReviewDecision.__tablename__ == "evidence_review_decisions"
    assert "uq_evidence_manifest_case_sequence" in {c.name for c in models.EvidenceManifestEntry.__table__.constraints}
    assert "uq_evidence_manifest_document" in {c.name for c in models.EvidenceManifestEntry.__table__.constraints}
    assert "uq_duplicate_candidate_pair" in {c.name for c in models.TransactionDuplicateCandidate.__table__.constraints}
    assert "ck_evidence_review_target_link" in {c.name for c in models.EvidenceReviewDecision.__table__.constraints}
    assert "ck_evidence_review_decision_code" in {c.name for c in models.EvidenceReviewDecision.__table__.constraints}


def test_v13_migration_explicitly_does_not_claim_authenticity_or_credit_decisions():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "does not establish document authenticity" in sql
    assert "camunda" in sql
    assert "bank authorization remain external" in sql


def _foreign_key_targets(table):
    targets = []
    for constraint in table.foreign_key_constraints:
        targets.append(tuple(sorted(str(element.target_fullname) for element in constraint.elements)))
    return targets


def test_v13_models_enforce_same_case_source_links():
    manifest_targets = _foreign_key_targets(models.EvidenceManifestEntry.__table__)
    duplicate_targets = _foreign_key_targets(models.TransactionDuplicateCandidate.__table__)
    reconciliation_targets = _foreign_key_targets(models.EvidenceReconciliationRun.__table__)
    assert ("documents.case_id", "documents.id") in manifest_targets
    assert duplicate_targets.count(("transactions.case_id", "transactions.id")) == 2
    assert reconciliation_targets.count(("documents.case_id", "documents.id")) == 2
    assert "uq_documents_id_case" in {c.name for c in models.Document.__table__.constraints}
    assert "uq_transactions_id_case" in {c.name for c in models.Transaction.__table__.constraints}


def test_v13_migration_enforces_same_case_links_and_append_only_snapshots():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "FOREIGN KEY(document_id, case_id)" in sql
    assert "FOREIGN KEY(left_transaction_id, case_id)" in sql
    assert "FOREIGN KEY(right_transaction_id, case_id)" in sql
    assert "FOREIGN KEY(pdf_document_id, case_id)" in sql
    assert "FOREIGN KEY(csv_document_id, case_id)" in sql
    assert "trg_duplicate_candidate_append_only" in sql
    assert "trg_reconciliation_run_append_only" in sql
    assert "FOREIGN KEY(reconciliation_run_id, case_id)" in sql
    assert "FOREIGN KEY(duplicate_candidate_id, case_id)" in sql


def test_v13_orm_and_migration_index_catalogs_align():
    expected = {
        "evidence_manifest_entries": {"ix_evidence_manifest_case_received"},
        "transaction_duplicate_candidates": {"ix_duplicate_candidate_case", "ix_duplicate_candidate_fingerprint"},
        "evidence_reconciliation_runs": {"ix_reconciliation_case_created"},
        "evidence_review_decisions": {"ix_evidence_review_target_created", "ix_evidence_review_case_created"},
    }
    for table_name, expected_names in expected.items():
        table = models.Base.metadata.tables[table_name]
        actual_names = {index.name for index in table.indexes}
        assert expected_names.issubset(actual_names)
    sql = MIGRATION.read_text(encoding="utf-8")
    for index_name in set.union(*expected.values()):
        assert f"CREATE INDEX {index_name}" in sql
