from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app import models
from app.main import app
from app.malware_scanner import ScanResult, scan_file, MalwareScannerUnavailable
from app.production_readiness import production_configuration_issues
from app.service import validate_upload_content, process_document

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migration" / "V17__production_security_scan_and_integrity.sql"


class _FakeSocket:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.sent = bytearray()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def settimeout(self, _):
        pass

    def sendall(self, data: bytes):
        self.sent.extend(data)

    def recv(self, _size: int):
        if self.reply:
            result, self.reply = self.reply, b""
            return result
        return b""


def _settings(tmp_path, **overrides):
    storage = tmp_path / "storage"
    exports = tmp_path / "exports"
    storage.mkdir(parents=True, mode=0o700)
    exports.mkdir(parents=True, mode=0o700)
    storage.chmod(0o700)
    exports.chmod(0o700)
    ca_file = tmp_path / "pg-root-ca.pem"
    ca_file.write_text("test-only CA placeholder for path validation", encoding="utf-8")
    ca_file.chmod(0o600)
    values = {
        "app_env": "production",
        "internal_service_token": "s" * 48,
        "service_assertion_keys": json.dumps({"backend-prod-01": "k" * 48}),
        "database_url": f"postgresql+psycopg://data_ai:db-password-that-is-at-least-32-bytes@db.internal/data_ai?sslmode=verify-full&sslrootcert={ca_file}",
        "clamav_host": "clamav.internal",
        "storage_encryption_provider": "PLATFORM_MANAGED_KMS",
        "storage_encryption_key_reference": "kms://storage-key/versions/3",
        "export_encryption_provider": "PLATFORM_MANAGED_KMS",
        "export_encryption_key_reference": "kms://export-key/versions/2",
        "required_flyway_version": "18",
        "require_scope_consent": True,
        "storage_dir": storage,
        "export_dir": exports,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_v952_accepts_uploads_only_when_extension_and_content_signature_match():
    assert validate_upload_content("statement.pdf", b"%PDF-1.7\nbody")[1] == "application/pdf"
    assert validate_upload_content("statement.csv", b"date,amount\n2026-01-01,100")[1] == "text/csv"
    assert validate_upload_content("../private/statement.pdf", b"%PDF-1.7\nbody")[0] == "statement.pdf"
    with pytest.raises(ValueError, match="không khớp"):
        validate_upload_content("fake.pdf", b"\x89PNG\r\n\x1a\nnot-a-pdf")
    with pytest.raises(ValueError, match="NUL"):
        validate_upload_content("binary.csv", b"a,b\n\x00\xff")


def test_v952_image_upload_requires_valid_image_container_not_only_magic_bytes():
    from PIL import Image
    image = Image.new("RGB", (2, 2), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    safe_name, mime = validate_upload_content("photo.png", output.getvalue())
    assert safe_name == "photo.png"
    assert mime == "image/png"
    with pytest.raises(ValueError, match="ảnh bị lỗi"):
        validate_upload_content("fake.png", b"\x89PNG\r\n\x1a\n" + b"not-an-image")


@pytest.mark.parametrize(
    "reply,expected",
    [(b"stream: OK\0", "CLEAN"), (b"stream: Eicar-Test-Signature FOUND\0", "INFECTED")],
)
def test_v952_clamav_stream_protocol_never_fakes_verdict(monkeypatch, tmp_path, reply, expected):
    content = b"%PDF-1.7\nsmall test file"
    path = tmp_path / "sample.pdf"
    path.write_bytes(content)
    scan_socket = _FakeSocket(reply)
    version_socket = _FakeSocket(b"ClamAV 1.4.2/28001\0")
    sockets = iter([scan_socket, version_socket])
    import app.malware_scanner as scanner
    monkeypatch.setattr(scanner.socket, "create_connection", lambda *args, **kwargs: next(sockets))

    result = scan_file(path, host="clamav.internal", port=3310, timeout=2, chunk_size=4096)
    assert isinstance(result, ScanResult)
    assert result.status == expected
    assert result.engine_name == "ClamAV"
    assert result.engine_version.startswith("ClamAV 1.4.2")
    assert result.scanned_sha256 == __import__("hashlib").sha256(content).hexdigest()
    assert scan_socket.sent.startswith(b"zINSTREAM\0")
    assert struct.unpack("!I", scan_socket.sent[10:14])[0] == len(content)
    assert scan_socket.sent.endswith(struct.pack("!I", 0))


def test_v952_clamav_unknown_reply_is_a_hard_failure(monkeypatch, tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text("a,b\n1,2", encoding="utf-8")
    import app.malware_scanner as scanner
    monkeypatch.setattr(scanner.socket, "create_connection", lambda *args, **kwargs: _FakeSocket(b"stream: maybe\0"))
    with pytest.raises(MalwareScannerUnavailable, match="unrecognized"):
        scan_file(path, host="clamav.internal", port=3310)


def test_v952_production_preflight_requires_tls_scanner_tokens_kms_and_private_volumes(tmp_path):
    good = _settings(tmp_path)
    assert production_configuration_issues(good) == []

    bad = _settings(
        tmp_path / "bad",
        internal_service_token="local-dev-only-change-me",
        service_assertion_keys="{}",
        database_url="postgresql+psycopg://data_ai:short-secret@db.internal/data_ai",
        clamav_host="",
        storage_encryption_provider="",
        export_encryption_key_reference="",
    )
    issues = production_configuration_issues(bad)
    assert any("INTERNAL_SERVICE_TOKEN" in issue for issue in issues)
    assert any("SERVICE_ASSERTION_KEYS" in issue for issue in issues)
    assert any("sslmode=verify-full" in issue for issue in issues)
    assert any("sslrootcert" in issue for issue in issues)
    assert any("CLAMAV_HOST" in issue for issue in issues)
    assert any("Storage volume encryption" in issue for issue in issues)
    assert any("Export volume encryption" in issue for issue in issues)


def test_v952_nonproduction_preflight_is_not_blocked_by_external_deployment_contracts(tmp_path):
    assert production_configuration_issues(SimpleNamespace(app_env="development")) == []


def test_v952_scan_attestation_model_and_postgresql_schema_have_byte_hash_fields():
    table = models.DocumentSecurityEvent.__table__
    assert {"scanned_sha256", "attestation_version"}.issubset(table.columns.keys())
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "scanned_sha256" in ddl
    assert "attestation_version" in ddl


def test_v952_v17_migration_binds_clean_verdict_to_document_hash_and_is_append_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    for fragment in (
        "scanned_sha256", "V1_CLAMAV", "validate_document_scan_attestation_v17",
        "guard_document_scan_status_v17", "document security events are append-only",
        "ck_documents_no_new_scan_exempt_v17",
    ):
        assert fragment in sql
    assert "NEW.scanned_sha256 IS DISTINCT FROM v_document_sha256" in sql
    assert "event_type = 'SCAN_COMPLETED'" in sql


def test_v952_security_scan_route_is_published_and_requires_internal_auth():
    path = "/api/v1/cases/{case_id}/documents/{document_id}/security-scan"
    operation = app.openapi()["paths"][path]["post"]
    assert "document-security" in operation["tags"]
    headers = {p["name"].lower() for p in operation.get("parameters", []) if p["in"] == "header"}
    assert {"x-internal-service-token", "x-service-assertion", "x-actor-id", "x-actor-roles", "x-bank-id"}.issubset(headers)


def test_v952_container_hardening_contract_is_present():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "USER 10001:10001" in dockerfile
    assert "read_only: true" in compose
    assert "cap_drop:" in compose and "no-new-privileges:true" in compose
    assert "pids_limit: 128" in compose and "nofile:" in compose
    assert '127.0.0.1:${API_PORT:-8001}:8001' in compose
    assert "${POSTGRES_PASSWORD:?" in compose


def test_v952_service_processing_cannot_bypass_scanner_gate():
    class Query:
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return None

    class FakeDB:
        def query(self, _model):
            return Query()

    document = SimpleNamespace(id="doc-1", malware_scan_status="NOT_SCANNED", sha256="a" * 64)
    with pytest.raises(ValueError, match="ClamAV CLEAN attestation"):
        process_document(FakeDB(), SimpleNamespace(id="case-1"), document)


def test_v952_readiness_rejects_legacy_clean_without_hash_bound_scan_attestation():
    from app.governance import assess_snapshot_readiness
    snapshot = {
        "documents": [{"id": "doc-1", "sha256": "a" * 64,
                        "malware_scan_status": "CLEAN", "processing_status": "COMPLETED"}],
        "document_security_events": [{"document_id": "doc-1", "scan_status": "CLEAN",
                                      "event_type": "SCAN_COMPLETED", "engine_name": "legacy-scanner",
                                      "engine_version": "unknown", "recorded_by": "old-worker",
                                      "scanned_sha256": None, "attestation_version": "LEGACY_UNVERIFIED"}],
        "evidence_manifest_entries": [{"document_id": "doc-1"}],
        "transaction_duplicate_candidates": [], "evidence_review_decisions": [],
        "evidence_reconciliation_runs": [], "data_quality_issues": [], "extracted_fields": [],
    }
    readiness = assess_snapshot_readiness(snapshot)
    assert readiness["review_ready"] is False
    assert "DOCUMENT_SCAN_EVIDENCE_MISSING" in {x["code"] for x in readiness["blockers"]}


def test_v952_security_headers_are_applied_to_api_responses():
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers.get("X-Request-ID")


def test_v952_production_preflight_rejects_long_but_placeholder_secrets(tmp_path):
    bad = _settings(
        tmp_path,
        internal_service_token="replace-with-a-long-random-token-value-123456789",
        service_assertion_keys=json.dumps({"backend-prod-01": "replace-with-32-byte-minimum-random-secret-value"}),
        database_url="postgresql+psycopg://data_ai:replace-with-a-long-password-value@db.internal/data_ai?sslmode=verify-full",
        storage_encryption_key_reference="replace-with-storage-kms-key-reference",
        export_encryption_key_reference="replace-with-export-kms-key-reference",
    )
    issues = production_configuration_issues(bad)
    assert any("INTERNAL_SERVICE_TOKEN" in issue for issue in issues)
    assert any("SERVICE_ASSERTION_KEYS" in issue for issue in issues)
    assert any("DATABASE_URL" in issue and "password" in issue for issue in issues)
    assert any("Storage volume encryption" in issue for issue in issues)
    assert any("Export volume encryption" in issue for issue in issues)


def test_v952_production_preflight_pins_required_flyway_release(tmp_path):
    bad = _settings(tmp_path, required_flyway_version="16")
    assert any("REQUIRED_FLYWAY_VERSION" in issue
               for issue in production_configuration_issues(bad))


def test_v952_verified_processing_copy_hashes_bytes_and_uses_private_read_only_copy(monkeypatch, tmp_path):
    import hashlib
    import stat
    from app import service
    content = b"%PDF-1.7\nverified bytes"
    storage = tmp_path / "storage"
    case_dir = storage / "case-1"
    case_dir.mkdir(parents=True, mode=0o700)
    source = case_dir / "doc.pdf"
    source.write_bytes(content)
    monkeypatch.setattr(service.settings, "storage_dir", storage)
    doc = SimpleNamespace(stored_path=str(source), original_filename="statement.pdf",
                          file_size=len(content), sha256=hashlib.sha256(content).hexdigest(), id="doc-1")

    copied = service._verified_processing_copy(doc)
    try:
        assert copied.read_bytes() == content
        assert stat.S_IMODE(copied.stat().st_mode) == 0o400
        source.write_bytes(b"%PDF-1.7\nchanged after scan")
        assert copied.read_bytes() == content
    finally:
        copied.unlink(missing_ok=True)


def test_v952_verified_processing_copy_rejects_storage_hash_drift(monkeypatch, tmp_path):
    import hashlib
    from app import service
    storage = tmp_path / "storage"
    case_dir = storage / "case-1"
    case_dir.mkdir(parents=True, mode=0o700)
    source = case_dir / "doc.csv"
    source.write_text("a,b\n1,2", encoding="utf-8")
    monkeypatch.setattr(service.settings, "storage_dir", storage)
    doc = SimpleNamespace(stored_path=str(source), original_filename="statement.csv",
                          file_size=source.stat().st_size,
                          sha256=hashlib.sha256(b"different bytes").hexdigest(), id="doc-1")
    with pytest.raises(ValueError, match="changed after the ClamAV scan"):
        service._verified_processing_copy(doc)


def test_v952_image_upload_rejects_dimension_bomb(monkeypatch):
    from app import service
    class OversizedImage:
        width = 100_000
        height = 100_000
        def verify(self):
            raise AssertionError("verify must not run for pixel-bomb dimensions")
    class FakeImageModule:
        class DecompressionBombWarning(Warning):
            pass
        @staticmethod
        def open(_stream):
            return OversizedImage()
    import PIL.Image
    monkeypatch.setattr(PIL, "Image", FakeImageModule, raising=False)
    with pytest.raises(ValueError, match="vượt giới hạn pixel"):
        service.validate_upload_content("oversized.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64)


def test_v952_clamav_refuses_symlink_instead_of_scanning_followed_target(tmp_path):
    target = tmp_path / "real.csv"
    target.write_text("a,b\n1,2", encoding="utf-8")
    link = tmp_path / "alias.csv"
    link.symlink_to(target)
    with pytest.raises(MalwareScannerUnavailable):
        scan_file(link, host="clamav.internal", port=3310)


def test_v952_processing_copy_refuses_symlinked_evidence_path(monkeypatch, tmp_path):
    import hashlib
    from app import service
    storage = tmp_path / "storage"
    case_dir = storage / "case-1"
    case_dir.mkdir(parents=True, mode=0o700)
    target = case_dir / "real.pdf"
    content = b"%PDF-1.7\nsource"
    target.write_bytes(content)
    link = case_dir / "linked.pdf"
    link.symlink_to(target)
    monkeypatch.setattr(service.settings, "storage_dir", storage)
    doc = SimpleNamespace(stored_path=str(link), original_filename="statement.pdf",
                          file_size=len(content), sha256=hashlib.sha256(content).hexdigest(), id="doc-1")
    with pytest.raises(service.EvidenceIntegrityError, match="symbolic link"):
        service._verified_processing_copy(doc)


def test_v952_backup_restore_scripts_require_tls_ca_and_isolated_restore_target():
    backup = (ROOT / "scripts" / "backup_postgres.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts" / "restore_postgres.sh").read_text(encoding="utf-8")
    assert "PGSSLROOTCERT" in backup and 'export PGSSLMODE="verify-full"' in backup
    assert "PGSSLROOTCERT" in restore and 'export PGSSLMODE="verify-full"' in restore
    assert ': "${PRODUCTION_PGDATABASE:?' in restore
    assert ': "${PGSSLROOTCERT:?' in restore
    assert 'TARGET_PGDATABASE" == "$PRODUCTION_PGDATABASE' in restore
