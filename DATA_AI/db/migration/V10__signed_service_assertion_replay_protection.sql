-- V10: durable one-time nonce store for Backend signed service assertions.
-- Apply with Flyway; do not create this table from application startup.
SET search_path TO data_ai;

CREATE TABLE IF NOT EXISTS service_assertion_nonces (
    nonce VARCHAR(128) PRIMARY KEY,
    key_id VARCHAR(80) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_service_assertion_nonces_key_id
    ON service_assertion_nonces (key_id);
CREATE INDEX IF NOT EXISTS ix_service_assertion_nonces_expires_at
    ON service_assertion_nonces (expires_at);

COMMENT ON TABLE service_assertion_nonces IS
    'One-time nonce registry for signed Backend-to-DATA-AI assertions; expired rows are pruned during authenticated requests.';
