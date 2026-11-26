"""Fail-closed production deployment checks for DATA-AI."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from sqlalchemy.engine import make_url

from app.security import parse_assertion_keys


PRODUCTION_ENVS = {"production", "prod", "staging"}
_PLACEHOLDER_MARKERS = ("replace", "change-me", "local-dev", "example", "sample", "dummy", "todo", "your-")


def _is_placeholder(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return not normalized or any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def production_configuration_issues(settings) -> list[str]:
    env = str(settings.app_env).strip().lower()
    if env not in PRODUCTION_ENVS:
        return []
    issues: list[str] = []

    token = str(settings.internal_service_token or "")
    if len(token.encode("utf-8")) < 32 or _is_placeholder(token):
        issues.append("INTERNAL_SERVICE_TOKEN must be a unique non-placeholder secret of at least 32 bytes")

    try:
        keys = parse_assertion_keys(settings.service_assertion_keys)
        if not keys or any(_is_placeholder(secret) for secret in keys.values()):
            issues.append("SERVICE_ASSERTION_KEYS must contain at least one active, non-placeholder signing key")
    except RuntimeError:
        issues.append("SERVICE_ASSERTION_KEYS is invalid")

    try:
        db_url = make_url(settings.database_url)
        sslmode = db_url.query.get("sslmode")
        if sslmode != "verify-full":
            issues.append("DATABASE_URL must require sslmode=verify-full")
        if db_url.drivername not in {"postgresql+psycopg", "postgresql"}:
            issues.append("DATABASE_URL must use PostgreSQL")
        if not db_url.host or not db_url.username:
            issues.append("DATABASE_URL must include an explicit database host and user")
        if not db_url.password or len(db_url.password.encode("utf-8")) < 24 or _is_placeholder(db_url.password):
            issues.append("DATABASE_URL must use a unique non-placeholder database password of at least 24 bytes")
        root_cert = db_url.query.get("sslrootcert")
        if not root_cert:
            issues.append("DATABASE_URL must set sslrootcert to the trusted PostgreSQL CA certificate")
        elif not Path(root_cert).is_absolute() or not Path(root_cert).is_file() or not os.access(root_cert, os.R_OK):
            issues.append("DATABASE_URL sslrootcert must point to an absolute, readable CA certificate file")
        db_password = db_url.password or ""
        if len(db_password.encode("utf-8")) < 24 or _is_placeholder(db_password):
            issues.append("DATABASE_URL must use a unique non-placeholder database password of at least 24 bytes")
    except Exception:
        issues.append("DATABASE_URL is invalid")

    clamav_host = str(settings.clamav_host or "").strip()
    if not clamav_host or "://" in clamav_host or "/" in clamav_host:
        issues.append("CLAMAV_HOST must identify the private malware scanning service (host only, no URL)")

    if (settings.storage_encryption_provider != "PLATFORM_MANAGED_KMS"
            or len(str(settings.storage_encryption_key_reference or "")) < 8
            or _is_placeholder(settings.storage_encryption_key_reference)):
        issues.append("Storage volume encryption must be platform-managed KMS with a non-placeholder key reference")
    if (settings.export_encryption_provider != "PLATFORM_MANAGED_KMS"
            or len(str(settings.export_encryption_key_reference or "")) < 8
            or _is_placeholder(settings.export_encryption_key_reference)):
        issues.append("Export volume encryption must be platform-managed KMS with a non-placeholder key reference")
    if str(getattr(settings, "required_flyway_version", "")) != "18":
        issues.append("REQUIRED_FLYWAY_VERSION must be 18 for the V10.0 DATA-AI input-handoff release")
    if getattr(settings, "require_scope_consent", False) is not True:
        issues.append("REQUIRE_SCOPE_CONSENT must be true so OCR cannot run before Backend scope/consent attestation")

    storage = Path(settings.storage_dir).resolve()
    exports = Path(settings.export_dir).resolve()
    if storage == exports or storage in exports.parents or exports in storage.parents:
        issues.append("STORAGE_DIR and EXPORT_DIR must be separate protected volumes")

    for label, directory in (("STORAGE_DIR", storage), ("EXPORT_DIR", exports)):
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            mode = stat.S_IMODE(directory.stat().st_mode)
            if mode & 0o077:
                issues.append(f"{label} permissions must not grant group/world access (expected 0700)")
        except OSError:
            issues.append(f"{label} must exist and be accessible to the non-root application user")
    return issues
