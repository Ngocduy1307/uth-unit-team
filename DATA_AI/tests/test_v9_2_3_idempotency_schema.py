from pathlib import Path

from app.models import ApiIdempotencyRecord
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.dialects.postgresql import JSONB

ROOT = Path(__file__).resolve().parents[1]


def test_v11_migration_and_orm_define_durable_scoped_idempotency_record():
    sql = (ROOT / "db" / "migration" / "V11__api_idempotency_records.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS api_idempotency_records" in sql
    assert "UNIQUE (scope_hash, idempotency_key_hash)" in sql
    assert "OUTCOME_UNKNOWN" in sql
    assert "response_body BYTEA" in sql
    assert "expires_at TIMESTAMPTZ NOT NULL" in sql

    table = ApiIdempotencyRecord.__table__
    assert {"scope_hash", "idempotency_key_hash", "request_hash", "state", "response_body", "expires_at"}.issubset(table.columns.keys())
    assert any({"scope_hash", "idempotency_key_hash"}.issubset(set(c.columns.keys())) for c in table.constraints if c.__class__.__name__ == "UniqueConstraint")
    # The ORM uses portable JSON on SQLite tests and native JSONB on PostgreSQL.
    assert isinstance(table.c.response_headers.type.dialect_impl(postgresql_dialect()), JSONB)
