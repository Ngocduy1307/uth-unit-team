from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from pydantic import Field

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://data_ai:data_ai_dev_password@localhost:5432/income_assistant?options=-csearch_path%3Ddata_ai"
    storage_dir: Path = Path("./storage")
    max_file_mb: int = 20
    max_files_per_case: int = 10
    max_pdf_pages: int = 60
    max_csv_rows: int = 3000
    ocr_lang: str = "vie+eng"
    internal_service_token: str = ""
    # JSON object: {"kid-2026-01": "base64-or-raw-secret"}. Keep secrets in a vault.
    service_assertion_keys: str = ""
    service_assertion_max_skew_seconds: int = Field(default=120, ge=1, le=600)
    service_assertion_issuer: str = "spring-boot-backend"
    service_assertion_audience: str = "data-ai"
    max_signed_request_mb: int = Field(default=24, ge=1, le=256)
    app_env: str = "development"
    export_dir: Path = Path("./exports")
    export_max_rows_per_sheet: int = 50000
    # SQLAlchemy pool controls; bounded defaults prevent unbounded DB pressure.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    # Idempotency is opt-in per mutation request. Keys remain valid for 72 hours.
    idempotency_ttl_hours: int = Field(default=72, ge=1, le=720)
    idempotency_max_request_mb: int = Field(default=24, ge=1, le=256)
    idempotency_max_response_kb: int = Field(default=1024, ge=1, le=8192)
    idempotency_in_progress_timeout_seconds: int = Field(default=1800, ge=60, le=86400)
    # V9.5.2: malware scanning is an external, fail-closed dependency.
    clamav_host: str = ""
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    clamav_chunk_kb: int = Field(default=64, ge=4, le=1024)
    # Production deployments must use separately encrypted platform volumes.
    # These are deployment attestations/references, not application encryption.
    storage_encryption_provider: str = ""
    storage_encryption_key_reference: str = ""
    export_encryption_provider: str = ""
    export_encryption_key_reference: str = ""
    required_flyway_version: str = "18"
    # Enforce Backend scope + consent attestation before any OCR processing in production.
    require_scope_consent: bool = False
    max_request_body_mb: int = Field(default=28, ge=1, le=300)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
settings.export_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
for _private_dir in (settings.storage_dir, settings.export_dir):
    try:
        _private_dir.chmod(0o700)
    except OSError:
        # Production readiness reports permission failures explicitly.
        pass
