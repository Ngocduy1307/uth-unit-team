"""Authorization and signed service-assertion helpers for DATA-AI."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from fastapi import HTTPException

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_ROLE_SPLIT = re.compile(r"[;,]")
_ASSERTION_RE = re.compile(r"^(v1|v2)\.([A-Za-z0-9_-]{1,80})\.(\d{10})\.([A-Za-z0-9_-]{16,128})\.([a-f0-9]{64})$")


def parse_trusted_roles(raw_roles: str | None) -> set[str]:
    if not raw_roles:
        return set()
    return {role.strip().upper() for role in _ROLE_SPLIT.split(raw_roles) if role.strip()}


def trusted_actor_context(actor_id: str | None, actor_roles: str | None, bank_id: str | None, *, require_bank: bool = True) -> tuple[str, set[str], str | None]:
    if not actor_id or not actor_id.strip():
        raise HTTPException(401, "Missing trusted actor context from Backend")
    if require_bank and (not bank_id or not bank_id.strip()):
        raise HTTPException(401, "Missing trusted bank context from Backend")
    actor = actor_id.strip()
    bank = bank_id.strip() if bank_id and bank_id.strip() else None
    if len(actor) > 160 or _CONTROL_CHARS.search(actor):
        raise HTTPException(400, "Invalid actor context")
    if bank is not None and (len(bank) > 100 or _CONTROL_CHARS.search(bank)):
        raise HTTPException(400, "Invalid bank context")
    roles = parse_trusted_roles(actor_roles)
    if len(roles) > 32 or any(len(role) > 64 or _CONTROL_CHARS.search(role) for role in roles):
        raise HTTPException(400, "Invalid role context")
    return actor, roles, bank


def require_any_role(roles: set[str], allowed: set[str], *, message: str) -> None:
    if not roles.intersection(allowed):
        raise HTTPException(403, message)


def enforce_bank_scope(resource_bank_id: str | None, caller_bank_id: str | None, roles: set[str], *, system_admin_role: str = "SYSTEM_ADMIN", not_found_message: str = "Resource not found") -> None:
    if system_admin_role in roles:
        return
    if not caller_bank_id or resource_bank_id != caller_bank_id:
        raise HTTPException(404, not_found_message)


def assertion_canonical(method: str, path: str, query: str, body: bytes, timestamp: str, nonce: str, actor_id: str, actor_roles: str, bank_id: str, issuer: str, audience: str, idempotency_key: str | None = None) -> bytes:
    """Canonical V1/V2 request binding. V2 additionally signs Idempotency-Key."""
    body_hash = hashlib.sha256(body).hexdigest()
    version = "V2" if idempotency_key is not None else "V1"
    fields = [f"DATA-AI-SERVICE-ASSERTION-{version}", issuer, audience, method.upper(), path, query, body_hash, timestamp, nonce, actor_id, actor_roles, bank_id]
    if idempotency_key is not None:
        fields.append(idempotency_key)
    if any("\n" in value or "\r" in value for value in fields):
        raise HTTPException(400, "Invalid signed assertion input")
    return "\n".join(fields).encode("utf-8")


def create_service_assertion(*, key_id: str, secret: str, method: str, path: str, query: str = "", body: bytes = b"", timestamp: int | None = None, nonce: str, actor_id: str, actor_roles: str, bank_id: str, issuer: str = "spring-boot-backend", audience: str = "data-ai", idempotency_key: str | None = None) -> str:
    ts = str(int(time.time()) if timestamp is None else int(timestamp))
    canonical = assertion_canonical(method, path, query, body, ts, nonce, actor_id, actor_roles, bank_id, issuer, audience, idempotency_key)
    signature = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    version = "v2" if idempotency_key is not None else "v1"
    return f"{version}.{key_id}.{ts}.{nonce}.{signature}"


def parse_assertion_keys(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SERVICE_ASSERTION_KEYS must be a JSON object") from exc
    if not isinstance(value, dict) or not value:
        raise RuntimeError("SERVICE_ASSERTION_KEYS must be a non-empty JSON object")
    keys: dict[str, str] = {}
    for key_id, secret in value.items():
        if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key_id):
            raise RuntimeError("Invalid service assertion key id")
        if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
            raise RuntimeError(f"Service assertion key {key_id!r} must contain at least 32 bytes")
        keys[key_id] = secret
    return keys


def verify_service_assertion(assertion: str | None, *, keys: dict[str, str], method: str, path: str, query: str = "", body: bytes = b"", actor_id: str | None, actor_roles: str | None, bank_id: str | None, issuer: str = "spring-boot-backend", audience: str = "data-ai", now: int | None = None, max_skew_seconds: int = 120, idempotency_key: str | None = None) -> tuple[str, int]:
    if not assertion:
        raise HTTPException(401, "Missing signed service assertion")
    match = _ASSERTION_RE.fullmatch(assertion)
    if not match:
        raise HTTPException(401, "Malformed signed service assertion")
    version, key_id, timestamp, nonce, supplied_signature = match.groups()
    if (version == "v2") != (idempotency_key is not None):
        raise HTTPException(401, "Signed assertion version does not match Idempotency-Key")
    secret = keys.get(key_id)
    if secret is None:
        raise HTTPException(401, "Unknown service assertion key")
    try:
        trusted_actor_context(actor_id, actor_roles, bank_id, require_bank=True)
        canonical = assertion_canonical(method, path, query, body, timestamp, nonce, actor_id or "", actor_roles or "", bank_id or "", issuer, audience, idempotency_key)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "Invalid signed assertion input") from exc
    current = int(time.time()) if now is None else int(now)
    if abs(current - int(timestamp)) > max_skew_seconds:
        raise HTTPException(401, "Service assertion has expired or is not yet valid")
    expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_signature):
        raise HTTPException(401, "Invalid service assertion signature")
    return nonce, int(timestamp) + max_skew_seconds
