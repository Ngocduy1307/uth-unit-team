from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migration" / "V8__production_data_integrity_and_governance.sql"
ERD = ROOT / "docs" / "ERD_V8.md"


def test_v8_migration_is_additive_and_has_expected_safety_controls():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS consent_events" in sql
    assert "CREATE TABLE IF NOT EXISTS document_security_events" in sql
    assert "ADD COLUMN IF NOT EXISTS bank_organization_id UUID" in sql
    assert "NOT VALID" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "trg_max_three_salary_accounts" in sql
    assert "reject_append_only_mutation" in sql
    assert "DROP TABLE" not in sql.upper()


def test_erd_documents_case_centric_model_and_legacy_bank_identifier():
    doc = ERD.read_text(encoding="utf-8")
    assert "cases` là aggregate root" in doc
    assert "bank_organization_id" in doc
    assert "NOT VALID" in doc
    assert "earning_match_candidates" in doc
    assert "Backend/SSO" in doc


def test_flyway_migration_versions_are_unique_and_preflight_is_outside_migration_dir():
    from pathlib import Path
    import re
    migration_dir = Path(__file__).parents[1] / "db" / "migration"
    versions = []
    for path in migration_dir.glob("V*__*.sql"):
        match = re.match(r"V([0-9]+)__", path.name)
        assert match, path.name
        versions.append(int(match.group(1)))
    assert len(versions) == len(set(versions)), "Flyway migration versions must be unique"
    assert (migration_dir.parent / "preflight" / "V8_preflight_checks.sql").exists()
    assert not (migration_dir / "V8__preflight_checks.sql").exists()
