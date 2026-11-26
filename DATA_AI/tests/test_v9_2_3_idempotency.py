from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.idempotency import IdempotencyMiddleware
from app.models import ApiIdempotencyRecord


def build_client(tmp_path, *, max_response_bytes=1024, timeout=1800):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'idempotency.db'}",
        connect_args={"check_same_thread": False},
    )
    ApiIdempotencyRecord.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    calls = {"count": 0, "auth": 0}

    async def authenticate(request):
        calls["auth"] += 1
        request.state.internal_service_authenticated = True

    app = FastAPI()

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", str(uuid4()))
        return response

    app.add_middleware(
        IdempotencyMiddleware,
        session_factory=lambda: sessions,
        authenticator=authenticate,
        ttl_hours=72,
        max_request_bytes=1024 * 1024,
        max_response_bytes=max_response_bytes,
        in_progress_timeout_seconds=timeout,
    )

    @app.post("/api/v1/commands")
    async def command(payload: dict):
        calls["count"] += 1
        return {"accepted": True, "sequence": calls["count"], "payload": payload}

    @app.post("/api/v1/fails")
    async def fail():
        calls["count"] += 1
        from fastapi import HTTPException
        raise HTTPException(422, "invalid command")

    return TestClient(app), calls, sessions, engine


def headers(key="command-0001"):
    return {"Idempotency-Key": key, "X-Actor-Id": "maker-01", "X-Bank-Id": "BANK-01"}


def test_same_key_and_same_payload_replays_stored_response(tmp_path):
    client, calls, _, _ = build_client(tmp_path)
    first = client.post("/api/v1/commands", json={"value": 7}, headers=headers())
    second = client.post("/api/v1/commands", json={"value": 7}, headers=headers())

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls["count"] == 1
    assert calls["auth"] == 2  # A replay still validates each fresh service assertion.
    assert second.headers["idempotency-replayed"] == "true"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_same_key_with_different_payload_is_rejected(tmp_path):
    client, calls, _, _ = build_client(tmp_path)
    first = client.post("/api/v1/commands", json={"value": 7}, headers=headers())
    second = client.post("/api/v1/commands", json={"value": 8}, headers=headers())

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert calls["count"] == 1


def test_missing_key_preserves_legacy_behavior(tmp_path):
    client, calls, _, _ = build_client(tmp_path)
    first = client.post("/api/v1/commands", json={"value": 7})
    second = client.post("/api/v1/commands", json={"value": 7})
    assert first.status_code == second.status_code == 200
    assert calls["count"] == 2


def test_four_xx_response_releases_reservation(tmp_path):
    client, calls, _, _ = build_client(tmp_path)
    first = client.post("/api/v1/fails", headers=headers())
    assert first.status_code == 422
    with client:
        retry = client.post("/api/v1/commands", json={"value": 9}, headers=headers())
    assert retry.status_code == 200
    assert calls["count"] == 2


def test_in_progress_record_is_not_executed_twice(tmp_path):
    client, calls, sessions, _ = build_client(tmp_path)
    first = client.post("/api/v1/commands", json={"value": 7}, headers=headers())
    assert first.status_code == 200
    with sessions() as db:
        row = db.query(ApiIdempotencyRecord).one()
        row.state = "IN_PROGRESS"
        row.response_status = None
        row.response_headers = None
        row.response_body = None
        row.completed_at = None
        row.created_at = datetime.now(timezone.utc)
        db.commit()

    response = client.post("/api/v1/commands", json={"value": 7}, headers=headers())
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert calls["count"] == 1


def test_oversized_response_is_not_replayed(tmp_path):
    client, calls, _, _ = build_client(tmp_path, max_response_bytes=8)
    first = client.post("/api/v1/commands", json={"value": 7}, headers=headers())
    second = client.post("/api/v1/commands", json={"value": 7}, headers=headers())
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_RESPONSE_NOT_REPLAYABLE"
    assert calls["count"] == 1


def test_invalid_idempotency_key_rejected_before_execution(tmp_path):
    client, calls, _, _ = build_client(tmp_path)
    response = client.post("/api/v1/commands", json={"value": 7}, headers=headers("bad"))
    assert response.status_code == 400
    assert calls["count"] == 0


def test_handler_exception_is_marked_unknown_and_never_reexecuted(tmp_path):
    client, calls, sessions, _ = build_client(tmp_path)
    app = client.app

    @app.post("/api/v1/unstable")
    async def unstable():
        calls["count"] += 1
        raise RuntimeError("simulated failure after business-side work")

    # The server error is rendered as HTTP 500, while the idempotency row is
    # retained as OUTCOME_UNKNOWN instead of caching a partial response.
    from fastapi.testclient import TestClient as _TestClient
    client = _TestClient(app, raise_server_exceptions=False)
    first = client.post("/api/v1/unstable", headers=headers("unstable-0001"))
    assert first.status_code == 500
    with sessions() as db:
        row = db.query(ApiIdempotencyRecord).filter_by(
            idempotency_key_hash=__import__("hashlib").sha256(b"unstable-0001").hexdigest()
        ).one()
        assert row.state == "OUTCOME_UNKNOWN"
        assert row.response_body is None

    retry = client.post("/api/v1/unstable", headers=headers("unstable-0001"))
    assert retry.status_code == 409
    assert retry.json()["code"] == "IDEMPOTENCY_OUTCOME_UNKNOWN"
    assert calls["count"] == 1


def test_old_in_progress_reservation_becomes_outcome_unknown(tmp_path):
    client, calls, sessions, _ = build_client(tmp_path, timeout=60)
    first = client.post("/api/v1/commands", json={"value": 3}, headers=headers("stale-0001"))
    assert first.status_code == 200
    with sessions() as db:
        row = db.query(ApiIdempotencyRecord).one()
        row.state = "IN_PROGRESS"
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        row.response_status = None
        row.response_headers = None
        row.response_body = None
        db.commit()

    response = client.post("/api/v1/commands", json={"value": 3}, headers=headers("stale-0001"))
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_OUTCOME_UNKNOWN"
    assert calls["count"] == 1
