import json
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.models import ApiIdempotencyRecord, ServiceAssertionNonce
from app.security import create_service_assertion
from app.idempotency import IdempotencyMiddleware


def test_signed_v2_authentication_and_nonce_check_run_before_response_replay(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'signed-idempotency.db'}",
        connect_args={"check_same_thread": False},
    )
    ServiceAssertionNonce.__table__.create(engine)
    ApiIdempotencyRecord.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    secret = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(main.settings, "app_env", "production")
    monkeypatch.setattr(main.settings, "internal_service_token", "service-token-for-test")
    monkeypatch.setattr(main.settings, "service_assertion_keys", json.dumps({"kid-test": secret}))
    monkeypatch.setattr(main.settings, "service_assertion_issuer", "spring-boot-backend")
    monkeypatch.setattr(main.settings, "service_assertion_audience", "data-ai")
    monkeypatch.setattr(main.settings, "service_assertion_max_skew_seconds", 120)
    monkeypatch.setattr(main, "get_session_factory", lambda: sessions)

    app = FastAPI()
    app.add_middleware(
        IdempotencyMiddleware,
        session_factory=lambda: sessions,
        authenticator=main._authenticate_request_for_idempotency,
        ttl_hours=72,
        max_request_bytes=1024 * 1024,
        max_response_bytes=1024 * 1024,
        in_progress_timeout_seconds=1800,
    )
    calls = {"count": 0}

    @app.post("/api/v1/commands", dependencies=[Depends(main.require_internal_token)])
    async def command(payload: dict):
        calls["count"] += 1
        return {"number": calls["count"], "value": payload["value"]}

    def signed_headers(key: str, body: bytes, nonce: str | None = None):
        nonce = nonce or uuid4().hex
        assertion = create_service_assertion(
            key_id="kid-test", secret=secret, method="POST", path="/api/v1/commands",
            body=body, nonce=nonce, actor_id="maker-007", actor_roles="MAKER",
            bank_id="BANK-007", issuer="spring-boot-backend", audience="data-ai",
            idempotency_key=key,
        )
        return {
            "X-Internal-Service-Token": "service-token-for-test",
            "X-Service-Assertion": assertion,
            "X-Actor-Id": "maker-007",
            "X-Actor-Roles": "MAKER",
            "X-Bank-Id": "BANK-007",
            "Idempotency-Key": key,
            "Content-Type": "application/json",
        }

    client = TestClient(app)
    body = b'{"value":17}'
    first = client.post("/api/v1/commands", content=body,
                        headers=signed_headers("signed-key-0001", body, "nonce-first-00000001"))
    replay = client.post("/api/v1/commands", content=body,
                         headers=signed_headers("signed-key-0001", body, "nonce-second-000002"))

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert calls["count"] == 1
    assert replay.headers["idempotency-replayed"] == "true"
    with sessions() as db:
        assert db.query(ServiceAssertionNonce).count() == 2
        row = db.query(ApiIdempotencyRecord).one()
        assert row.state == "COMPLETED"

    # Reusing the key but signing a different Idempotency-Key must fail HMAC
    # verification and must not execute the command or retrieve the stored body.
    tampered = signed_headers("signed-key-0002", body, "nonce-third-000003")
    tampered["Idempotency-Key"] = "signed-key-0001"
    denied = client.post("/api/v1/commands", content=body, headers=tampered)
    assert denied.status_code == 401
    assert calls["count"] == 1
