from pathlib import Path

from app import models

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migration" / "V14__case_analysis_version_governance_freeze.sql"


def test_v14_creates_immutable_versions_and_governance_events():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE case_analysis_versions" in sql
    assert "CREATE TABLE case_governance_events" in sql
    assert "uq_case_analysis_version_case_no" in sql
    assert "FOREIGN KEY(based_on_version_id, case_id)" in sql
    assert "FOREIGN KEY(version_id, case_id)" in sql
    assert "trg_case_analysis_version_immutable" in sql
    assert "trg_case_governance_event_immutable" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "ck_case_analysis_version_requires_frozen_event" in sql


def test_v14_enforces_checker_independence_and_readiness_at_database_boundary():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "NEW.actor_id = v_created_by" in sql
    assert "NEW.event_type = 'CHECKER_CONFIRMED' AND NOT v_ready" in sql
    assert "uq_case_governance_checker_decision_per_version" in sql
    assert "a new version requires the previous version to be returned to Maker" in sql


def test_v14_protects_case_owned_data_while_latest_version_is_frozen():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ["cases", "documents", "extracted_fields", "transactions", "applicant_submissions",
                  "evidence_manifest_entries", "evidence_reconciliation_runs", "evidence_review_decisions",
                  "customer_expense_declarations", "customer_liability_declarations", "payroll_evidence",
                  "document_security_events"]:
        assert f"'{table}'" in sql
    assert "guard_case_data_when_frozen" in sql
    assert "FOR UPDATE" in sql
    assert "RETURNED_TO_MAKER" in sql
    assert "TG_TABLE_NAME = 'document_security_events'" in sql
    assert "OLD.document_id IS DISTINCT FROM NEW.document_id" in sql
    assert "ck_case_governance_no_extracted_field_reparent" in sql


def test_v14_orm_tables_and_indexes_match_migration_contract():
    assert models.CaseAnalysisVersion.__tablename__ in models.Base.metadata.tables
    assert models.CaseGovernanceEvent.__tablename__ in models.Base.metadata.tables
    expected = {
        "case_analysis_versions": {"ix_case_analysis_version_case_created"},
        "case_governance_events": {"ix_case_governance_case_created", "ix_case_governance_version_created",
            "uq_case_governance_frozen_per_version", "uq_case_governance_checker_decision_per_version",
            "uq_case_governance_superseded_per_version"},
    }
    for table, names in expected.items():
        assert names.issubset({index.name for index in models.Base.metadata.tables[table].indexes})
    sql = MIGRATION.read_text(encoding="utf-8")
    for name in set.union(*expected.values()):
        assert name in sql


def test_v14_explicitly_keeps_camunda_and_credit_decisions_outside_data_ai():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "camunda remains authoritative" in sql
    assert "not a credit decision" in sql
    assert "not an authoritative i/e/d result" in sql


def test_v14_orm_index_sort_order_matches_postgresql_migration():
    from sqlalchemy.schema import CreateIndex
    from sqlalchemy.dialects import postgresql
    for table_name, index_name in [
        ("case_analysis_versions", "ix_case_analysis_version_case_created"),
        ("case_governance_events", "ix_case_governance_case_created"),
        ("case_governance_events", "ix_case_governance_version_created"),
    ]:
        table = models.Base.metadata.tables[table_name]
        index = next(item for item in table.indexes if item.name == index_name)
        compiled = str(CreateIndex(index).compile(dialect=postgresql.dialect())).upper()
        assert "DESC" in compiled


def test_v14_snapshot_and_freeze_guard_include_document_security_events():
    sql = MIGRATION.read_text(encoding="utf-8")
    governance = (ROOT / "app" / "governance.py").read_text(encoding="utf-8")
    assert "'document_security_events'" in sql
    assert '"document_security_events": document_security_events' in governance
    assert "DOCUMENT_SCAN_EVIDENCE_MISSING" in governance
    assert "verify_version_integrity" in governance


def test_v14_guard_list_covers_every_case_scoped_orm_table_except_audit_and_governance_ledgers():
    protected = {
        "cases", "documents", "extracted_fields", "transactions", "processing_results",
        "applicant_submissions", "data_quality_issues", "payroll_evidence", "income_ledger_months",
        "earning_match_candidates", "loan_applications", "pipeline_runs",
        "customer_household_profiles", "customer_expense_declarations",
        "customer_liability_declarations", "customer_salary_accounts",
        "customer_declaration_revisions", "consent_events", "evidence_manifest_entries",
        "transaction_duplicate_candidates", "evidence_reconciliation_runs",
        "evidence_review_decisions", "document_security_events",
    }
    excluded = {"audit_events", "case_analysis_versions", "case_governance_events",
                "case_audit_entries", "case_override_requests", "case_override_events",
                # V16 workflow correlation, inbox/outbox, evidence lifecycle and immutable package ledgers
                "case_workflow_bindings", "workflow_outbox_events", "workflow_inbox_events",
                "case_evidence_requests", "case_resubmissions", "case_workflow_reopens",
                "case_workflow_release_gates", "case_workflow_export_packages",
                "case_override_application_receipts",
                # V18 Backend scope/consent attestations, declaration revisions,
                # Maker input-review and Financial Engine handoff ledgers are append-only.
                "case_scope_consent_attestations", "case_input_declaration_revisions",
                "case_input_declaration_evidence_links", "case_input_review_decisions",
                "case_financial_input_bundles", "case_proposed_schedule_references",
                "case_business_engine_receipts"}
    mapped_case_tables = {
        table.name for table in models.Base.metadata.tables.values() if "case_id" in table.c
    }
    # Cases, OCR fields and document scan events resolve case ownership through their own key.
    mapped_case_tables.update({"cases", "extracted_fields", "document_security_events"})
    assert mapped_case_tables - excluded == protected
    sql = MIGRATION.read_text(encoding="utf-8")
    for table_name in protected:
        assert f"'{table_name}'" in sql
