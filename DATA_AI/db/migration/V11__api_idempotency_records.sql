-- V11: persistent replay ledger for opt-in API mutation requests.
-- This table is intentionally separate from business tables. It is not an
-- outbox and does not replace domain transaction/audit records.
SET search_path TO data_ai;

CREATE TABLE IF NOT EXISTS api_idempotency_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_hash VARCHAR(64) NOT NULL,
    idempotency_key_hash VARCHAR(64) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    state VARCHAR(24) NOT NULL DEFAULT 'IN_PROGRESS'
        CHECK (state IN ('IN_PROGRESS', 'COMPLETED', 'OUTCOME_UNKNOWN')),
    response_status INTEGER NULL CHECK (response_status IS NULL OR response_status BETWEEN 100 AND 599),
    response_headers JSONB NULL,
    response_body BYTEA NULL,
    response_replayable BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_api_idempotency_scope_key UNIQUE (scope_hash, idempotency_key_hash)
);

CREATE INDEX IF NOT EXISTS ix_api_idempotency_expires_at
    ON api_idempotency_records (expires_at);
CREATE INDEX IF NOT EXISTS ix_api_idempotency_state_created
    ON api_idempotency_records (state, created_at);

COMMENT ON TABLE api_idempotency_records IS
    'Durable 72-hour replay ledger for Backend mutation requests. OUTCOME_UNKNOWN rows must be reconciled; never auto-re-executed.';
COMMENT ON COLUMN api_idempotency_records.scope_hash IS
    'SHA-256 of trusted actor ID and bank ID; raw identity values are not stored here.';
COMMENT ON COLUMN api_idempotency_records.idempotency_key_hash IS
    'SHA-256 of Idempotency-Key; raw client key is not persisted.';
COMMENT ON COLUMN api_idempotency_records.request_hash IS
    'Hash of method, raw path/query, actor context, and exact request-body hash.';
