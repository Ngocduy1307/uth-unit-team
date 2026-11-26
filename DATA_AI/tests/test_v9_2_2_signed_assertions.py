import pytest
from fastapi import HTTPException

from app.security import (
    create_service_assertion,
    parse_assertion_keys,
    verify_service_assertion,
)

KEYS = {"backend-2026-01": "0123456789abcdef0123456789abcdef"}
BASE = dict(
    key_id="backend-2026-01",
    secret=KEYS["backend-2026-01"],
    method="POST",
    path="/api/v1/cases",
    query="source=backend",
    body=b'{"external_case_id":"CASE-1"}',
    timestamp=1_800_000_000,
    nonce="abcdefghijklmnop1234",
    actor_id="staff-123",
    actor_roles="MAKER",
    bank_id="BANK-01",
)


def signed(**overrides):
    values = {**BASE, **overrides}
    return create_service_assertion(**values)


def verify(assertion, **overrides):
    values = {
        "keys": KEYS,
        "method": BASE["method"],
        "path": BASE["path"],
        "query": BASE["query"],
        "body": BASE["body"],
        "actor_id": BASE["actor_id"],
        "actor_roles": BASE["actor_roles"],
        "bank_id": BASE["bank_id"],
        "now": BASE["timestamp"],
        "max_skew_seconds": 120,
    }
    values.update(overrides)
    return verify_service_assertion(assertion, **values)


def test_valid_assertion_binds_request_and_identity():
    nonce, expiry = verify(signed())
    assert nonce == BASE["nonce"]
    assert expiry == BASE["timestamp"] + 120


@pytest.mark.parametrize("field,value", [
    ("method", "GET"),
    ("path", "/api/v1/customers"),
    ("query", "source=browser"),
    ("body", b'{"external_case_id":"CASE-2"}'),
    ("actor_id", "another-user"),
    ("actor_roles", "SYSTEM_ADMIN"),
    ("bank_id", "BANK-OTHER"),
])
def test_assertion_rejects_tampered_request_or_identity(field, value):
    assertion = signed()
    args = {field: value}
    with pytest.raises(HTTPException) as exc:
        verify(assertion, **args)
    assert exc.value.status_code == 401


def test_expired_assertion_is_rejected():
    assertion = signed()
    with pytest.raises(HTTPException) as exc:
        verify(assertion, now=BASE["timestamp"] + 121)
    assert exc.value.status_code == 401


def test_unknown_key_is_rejected():
    assertion = signed()
    with pytest.raises(HTTPException) as exc:
        verify(assertion, keys={"other-key": KEYS["backend-2026-01"]})
    assert exc.value.status_code == 401


@pytest.mark.parametrize("assertion", [None, "", "v1.bad", "v1.kid.123.nonce.sig"])
def test_malformed_or_missing_assertion_is_rejected(assertion):
    with pytest.raises(HTTPException) as exc:
        verify(assertion)
    assert exc.value.status_code == 401


def test_assertion_key_configuration_requires_strong_secrets():
    with pytest.raises(RuntimeError):
        parse_assertion_keys('{"kid":"short"}')
    assert parse_assertion_keys('{"kid":"0123456789abcdef0123456789abcdef"}')


def test_assertion_nonce_shape_is_enforced():
    with pytest.raises(HTTPException) as exc:
        verify(signed(nonce="short"))
    assert exc.value.status_code == 401


def test_v10_migration_creates_persistent_nonce_registry():
    from pathlib import Path
    migration = Path("db/migration/V10__signed_service_assertion_replay_protection.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS service_assertion_nonces" in migration
    assert "nonce VARCHAR(128) PRIMARY KEY" in migration
    assert "expires_at TIMESTAMPTZ NOT NULL" in migration


def test_v2_assertion_binds_idempotency_key():
    key = "case-create-2026-001"
    assertion = signed(idempotency_key=key)
    nonce, _ = verify(assertion, idempotency_key=key)
    assert nonce == BASE["nonce"]
    with pytest.raises(HTTPException) as exc:
        verify(assertion, idempotency_key="case-create-2026-002")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        verify(assertion)
    assert exc.value.status_code == 401


def test_v1_assertion_remains_compatible_without_idempotency_key():
    assertion = signed()
    assert assertion.startswith("v1.")
    verify(assertion)
