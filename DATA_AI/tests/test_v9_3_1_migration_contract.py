from pathlib import Path
from app import models

ROOT = Path(__file__).resolve().parents[1]


def test_v12_migration_adds_abstention_and_confidence_provenance():
    sql = (ROOT / "db/migration/V12__ocr_layout_field_governance.sql").read_text(encoding="utf-8")
    for name in ("confidence_basis", "validation_status", "extraction_decision", "abstain_reason", "extraction_rule_version"):
        assert name in sql
    assert "NOT VALID" in sql
    assert "ix_extracted_fields_decision_review" in sql


def test_v12_columns_are_not_marked_as_approval_or_authenticity():
    table = models.Base.metadata.tables["extracted_fields"]
    assert "extraction_decision" in table.columns
    assert "validation_status" in table.columns
    assert any(index.name == "ix_extracted_fields_decision_review" for index in table.indexes)
