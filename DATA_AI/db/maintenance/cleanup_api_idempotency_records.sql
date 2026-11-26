-- Run periodically through the DBA/maintenance scheduler after V11.
-- Delete at most 10,000 expired rows per batch to avoid a long table-wide lock.
-- Repeat until the statement reports zero deleted rows.
WITH expired_batch AS (
    SELECT id
    FROM data_ai.api_idempotency_records
    WHERE expires_at < NOW()
    ORDER BY expires_at
    LIMIT 10000
    FOR UPDATE SKIP LOCKED
)
DELETE FROM data_ai.api_idempotency_records AS target
USING expired_batch
WHERE target.id = expired_batch.id;
