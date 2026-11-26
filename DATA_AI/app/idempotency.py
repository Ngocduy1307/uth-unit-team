"""Opt-in durable idempotency middleware for mutation requests.

The middleware authenticates a signed Backend request before it can replay a
stored response. A request is reserved before business execution; bounded
responses are persisted before they are sent to the caller. Oversized responses
are streamed and marked non-replayable. An interrupted request is never
automatically re-executed: operators must reconcile its outcome.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models import ApiIdempotencyRecord

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_STRIP_RESPONSE_HEADERS = {
    # Hop-by-hop and per-attempt headers must be regenerated, not replayed.
    b"content-length", b"transfer-encoding", b"connection", b"keep-alive",
    b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer",
    b"upgrade", b"date", b"x-request-id", b"idempotency-replayed",
    # DATA-AI is a machine-to-machine API; never replay a session cookie.
    b"set-cookie",
}


class IdempotencyMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        session_factory: Callable,
        authenticator: Callable[[Request], Awaitable[None]],
        ttl_hours: int = 72,
        max_request_bytes: int = 24 * 1024 * 1024,
        max_response_bytes: int = 1024 * 1024,
        in_progress_timeout_seconds: int = 1800,
    ) -> None:
        self.app = app
        self.session_factory = session_factory
        self.authenticator = authenticator
        self.ttl_hours = ttl_hours
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self.in_progress_timeout_seconds = in_progress_timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() not in _MUTATION_METHODS:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return

        raw_keys = [value for name, value in scope.get("headers", []) if name.lower() == b"idempotency-key"]
        if not raw_keys:
            await self.app(scope, receive, send)
            return
        request_id = self._request_id(scope)
        if len(raw_keys) != 1:
            await self._json_error(send, 400, "INVALID_IDEMPOTENCY_KEY", "Exactly one Idempotency-Key header is allowed", request_id)
            return
        try:
            idempotency_key = raw_keys[0].decode("ascii")
        except UnicodeDecodeError:
            await self._json_error(send, 400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be ASCII", request_id)
            return
        if not _KEY_RE.fullmatch(idempotency_key):
            await self._json_error(send, 400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 8-128 safe characters", request_id)
            return

        body_parts: list[bytes] = []
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            part = message.get("body", b"")
            body_size += len(part)
            if body_size > self.max_request_bytes:
                await self._json_error(send, 413, "IDEMPOTENCY_BODY_TOO_LARGE", "Request body exceeds the configured idempotency limit", request_id)
                return
            body_parts.append(part)
            if not message.get("more_body", False):
                break
        body = b"".join(body_parts)
        def make_replay_receive():
            sent_body = False
            async def replay_receive() -> Message:
                nonlocal sent_body
                if not sent_body:
                    sent_body = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}
            return replay_receive

        request = Request(scope, receive=make_replay_receive())
        # Do not let an idempotency replay bypass the normal service token,
        # HMAC assertion, actor/bank binding, or PostgreSQL nonce replay checks.
        try:
            await self.authenticator(request)
        except Exception:
            # FastAPI's normal dependency path will emit the canonical auth error.
            await self.app(scope, make_replay_receive(), send)
            return

        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        actor_id_raw = headers.get(b"x-actor-id", b"").decode("latin-1")
        actor_roles_raw = headers.get(b"x-actor-roles", b"").decode("latin-1")
        bank_id_raw = headers.get(b"x-bank-id", b"").decode("latin-1")
        # Use the same normalized trust context as route authorization. The
        # raw assertion still signs the original header values; normalization
        # here only makes the persistence scope deterministic.
        from app.security import trusted_actor_context
        try:
            actor_id, roles, bank_id = trusted_actor_context(
                actor_id_raw, actor_roles_raw, bank_id_raw, require_bank=True
            )
        except Exception:
            # Let FastAPI's dependency/route layer produce the canonical auth
            # or actor-context error instead of turning it into middleware 500.
            await self.app(scope, make_replay_receive(), send)
            return
        roles_material = ",".join(sorted(roles))
        raw_path = scope.get("raw_path", scope.get("path", "").encode("utf-8"))
        raw_query = scope.get("query_string", b"")
        body_hash = hashlib.sha256(body).hexdigest()
        request_material = b"\n".join([
            scope.get("method", "").upper().encode("ascii"), raw_path, raw_query,
            headers.get(b"content-type", b"").lower(), headers.get(b"content-encoding", b"").lower(),
            headers.get(b"accept", b"").lower(), actor_id.encode("utf-8"),
            roles_material.encode("utf-8"), bank_id.encode("utf-8"), body_hash.encode("ascii"),
        ])
        request_hash = hashlib.sha256(request_material).hexdigest()
        scope_hash = hashlib.sha256((actor_id + "\n" + bank_id).encode("utf-8")).hexdigest()
        key_hash = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()

        try:
            reservation = self._reserve(scope_hash, key_hash, request_hash)
        except Exception:
            await self._json_error(send, 503, "IDEMPOTENCY_STORE_UNAVAILABLE", "Idempotency store is unavailable; business operation was not started", request_id)
            return

        if reservation["kind"] == "MISMATCH":
            await self._json_error(send, 409, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different request", request_id)
            return
        if reservation["kind"] == "IN_PROGRESS":
            await self._json_error(send, 409, "IDEMPOTENCY_IN_PROGRESS", "A request with this key is still being processed", request_id, retry_after="2")
            return
        if reservation["kind"] == "UNKNOWN":
            await self._json_error(send, 409, "IDEMPOTENCY_OUTCOME_UNKNOWN", "The previous attempt did not complete its response record; reconcile the business record before retrying", request_id)
            return
        if reservation["kind"] == "COMPLETED":
            if not reservation["replayable"] or reservation["body"] is None:
                await self._json_error(send, 409, "IDEMPOTENCY_RESPONSE_NOT_REPLAYABLE", "The operation completed, but its response exceeded the replay limit; reconcile the result instead of repeating it", request_id)
                return
            replay_headers = [
                (k.encode("latin-1"), v.encode("latin-1"))
                for k, v in (reservation["headers"] or [])
                if k.lower().encode("latin-1") not in _STRIP_RESPONSE_HEADERS
            ]
            replay_headers.extend([
                (b"content-length", str(len(reservation["body"])).encode("ascii")),
                (b"x-request-id", request_id.encode("ascii")),
                (b"idempotency-replayed", b"true"),
            ])
            await send({"type": "http.response.start", "status": reservation["status"], "headers": replay_headers})
            await send({"type": "http.response.body", "body": reservation["body"], "more_body": False})
            return

        # Owner: collect the response before sending it so the durable replay
        # record is committed before the caller can observe success.
        captured: list[Message] = []
        captured_bytes = 0
        overflow = False
        overflow_status: int | None = None
        overflow_headers: list[list[str]] = []

        async def capture_send(message: Message) -> None:
            nonlocal captured_bytes, overflow, overflow_status, overflow_headers
            if message["type"] == "http.response.start":
                overflow_status = int(message["status"])
                overflow_headers = [
                    [name.decode("latin-1"), value.decode("latin-1")]
                    for name, value in message.get("headers", [])
                    if name.lower() not in _STRIP_RESPONSE_HEADERS
                ]
            if not overflow:
                captured.append(dict(message))
                if message["type"] == "http.response.body":
                    captured_bytes += len(message.get("body", b""))
                if captured_bytes > self.max_response_bytes:
                    overflow = True
                    for item in captured:
                        await send(item)
                    captured.clear()
            else:
                await send(message)

        try:
            await self.app(scope, make_replay_receive(), capture_send)
        except Exception:
            # Never persist a partial response from an exception path. The
            # business transaction may have committed before the exception,
            # so leave a durable tombstone and require reconciliation.
            self._mark_unknown(scope_hash, key_hash, request_hash)
            raise

        if overflow:
            # The body was already flushed as a stream; record completion but
            # refuse unsafe replay of an uncached response.
            if overflow_status is not None:
                try:
                    self._complete(scope_hash, key_hash, request_hash, overflow_status, overflow_headers, None, replayable=False)
                except Exception:
                    self._mark_unknown(scope_hash, key_hash, request_hash)
            else:
                self._mark_unknown(scope_hash, key_hash, request_hash)
            return

        status, response_headers, response_body = self._extract_response(captured, b"")
        if status is None:
            self._mark_unknown(scope_hash, key_hash, request_hash)
            for item in captured:
                await send(item)
            return

        # Deterministic 4xx responses normally indicate validation/auth/business
        # precondition failures and should not lock the caller's key forever.
        if 400 <= status < 500:
            self._release(scope_hash, key_hash, request_hash)
            for item in captured:
                await send(item)
            return

        try:
            self._complete(scope_hash, key_hash, request_hash, status, response_headers, response_body, replayable=True)
        except Exception:
            self._mark_unknown(scope_hash, key_hash, request_hash)
            await self._json_error(send, 503, "IDEMPOTENCY_OUTCOME_UNKNOWN", "The business handler returned, but its idempotency response could not be persisted; reconcile before retrying", request_id)
            return
        for item in captured:
            await send(item)

    @staticmethod
    def _request_id(scope: Scope) -> str:
        supplied = next((v for n, v in scope.get("headers", []) if n.lower() == b"x-request-id"), b"")
        try:
            return str(UUID(supplied.decode("ascii"))) if supplied else str(uuid4())
        except (ValueError, UnicodeDecodeError, TypeError):
            return str(uuid4())

    async def _json_error(self, send: Send, status: int, code: str, detail: str, request_id: str, retry_after: str | None = None) -> None:
        body = json.dumps({"detail": detail, "code": code}, ensure_ascii=False).encode("utf-8")
        headers = [(b"content-type", b"application/json; charset=utf-8"),
                   (b"content-length", str(len(body)).encode("ascii")),
                   (b"x-request-id", request_id.encode("ascii"))]
        if retry_after:
            headers.append((b"retry-after", retry_after.encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    @staticmethod
    def _extract_response(messages: list[Message], default_body: bytes | None) -> tuple[int | None, list[list[str]], bytes | None]:
        status = None
        headers: list[list[str]] = []
        body_parts: list[bytes] = []
        body_seen = False
        for message in messages:
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = [
                    [name.decode("latin-1"), value.decode("latin-1")]
                    for name, value in message.get("headers", [])
                    if name.lower() not in _STRIP_RESPONSE_HEADERS
                ]
            elif message["type"] == "http.response.body":
                body_seen = True
                body_parts.append(message.get("body", b""))
        if not body_seen:
            return status, headers, default_body
        return status, headers, b"".join(body_parts)

    def _reserve(self, scope_hash: str, key_hash: str, request_hash: str) -> dict:
        now = datetime.now(timezone.utc)
        try:
            with self.session_factory()() as db:
                # Avoid a table-wide expiry DELETE on every mutation request.
                # Expired rows for this key are recycled here; a separate
                # bounded maintenance statement prunes unrelated expired keys.
                row = db.query(ApiIdempotencyRecord).filter_by(scope_hash=scope_hash, idempotency_key_hash=key_hash).first()
                if row is not None:
                    expiry = row.expires_at
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    if expiry <= now:
                        db.delete(row)
                        db.commit()
                        row = None
                    else:
                        if row.request_hash != request_hash:
                            db.commit()
                            return {"kind": "MISMATCH"}
                        if row.state == "COMPLETED":
                            data = {"kind": "COMPLETED", "status": row.response_status,
                                    "headers": row.response_headers or [], "body": bytes(row.response_body) if row.response_body is not None else None,
                                    "replayable": bool(row.response_replayable)}
                            db.commit()
                            return data
                        age = (now - row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else now - row.created_at)
                        if row.state == "OUTCOME_UNKNOWN" or age.total_seconds() > self.in_progress_timeout_seconds:
                            row.state = "OUTCOME_UNKNOWN"
                            db.commit()
                            return {"kind": "UNKNOWN"}
                        db.commit()
                        return {"kind": "IN_PROGRESS"}
                if row is None:
                    db.add(ApiIdempotencyRecord(
                        scope_hash=scope_hash, idempotency_key_hash=key_hash,
                        request_hash=request_hash, state="IN_PROGRESS",
                        expires_at=now + timedelta(hours=self.ttl_hours),
                        response_replayable=True,
                    ))
                    db.commit()
                    return {"kind": "OWNER"}
        except IntegrityError:
            # A concurrent request won the unique-key insert. Read its state in
            # a fresh transaction instead of attempting the operation twice.
            with self.session_factory()() as db:
                row = db.query(ApiIdempotencyRecord).filter_by(scope_hash=scope_hash, idempotency_key_hash=key_hash).first()
                if row is None:
                    raise
                if row.request_hash != request_hash:
                    return {"kind": "MISMATCH"}
                if row.state == "COMPLETED":
                    return {"kind": "COMPLETED", "status": row.response_status,
                            "headers": row.response_headers or [], "body": bytes(row.response_body) if row.response_body is not None else None,
                            "replayable": bool(row.response_replayable)}
                if row.state == "OUTCOME_UNKNOWN":
                    return {"kind": "UNKNOWN"}
                return {"kind": "IN_PROGRESS"}

    def _complete(self, scope_hash: str, key_hash: str, request_hash: str, status: int, headers: list[list[str]], body: bytes | None, *, replayable: bool) -> None:
        with self.session_factory()() as db:
            row = db.query(ApiIdempotencyRecord).filter_by(
                scope_hash=scope_hash, idempotency_key_hash=key_hash, request_hash=request_hash
            ).first()
            if row is None or row.state not in {"IN_PROGRESS", "OUTCOME_UNKNOWN"}:
                raise RuntimeError("Idempotency reservation disappeared before completion")
            row.state = "COMPLETED"
            row.response_status = status
            row.response_headers = headers
            row.response_body = body
            row.response_replayable = replayable
            row.completed_at = datetime.now(timezone.utc)
            db.commit()

    def _release(self, scope_hash: str, key_hash: str, request_hash: str) -> None:
        with self.session_factory()() as db:
            db.query(ApiIdempotencyRecord).filter_by(
                scope_hash=scope_hash, idempotency_key_hash=key_hash, request_hash=request_hash,
                state="IN_PROGRESS",
            ).delete(synchronize_session=False)
            db.commit()

    def _mark_unknown(self, scope_hash: str, key_hash: str, request_hash: str) -> None:
        try:
            with self.session_factory()() as db:
                row = db.query(ApiIdempotencyRecord).filter_by(
                    scope_hash=scope_hash, idempotency_key_hash=key_hash, request_hash=request_hash
                ).first()
                if row is not None and row.state == "IN_PROGRESS":
                    row.state = "OUTCOME_UNKNOWN"
                    db.commit()
        except Exception:
            pass
