from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from pathlib import Path
import secrets
from contextlib import asynccontextmanager
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db, get_session_factory
from app import models, repository, service
from app.schemas import (CaseCreate, CaseOut, DocumentOut, OCRCatalogOut,
                          EvidenceReconciliationIn, EvidenceReviewIn,
                          GovernanceFreezeIn, GovernanceCheckerReviewIn, OverrideRequestIn,
                          NamedAuthorityReviewIn, OverrideWithdrawIn, WorkflowBindingIn,
                          WorkflowEvidenceRequestIn, WorkflowResubmissionIn, WorkflowReopenIn,
                          WorkflowInboxEventIn, WorkflowOutboxClaimIn, WorkflowOutboxAckIn,
                          WorkflowReleaseGateIn, WorkflowExportPackageIn, OverrideApplicationReceiptIn,
                          ScopeConsentAttestationIn, InputDeclarationRevisionIn, CaseInputReviewIn,
                          ProposedScheduleReferenceIn, BusinessEngineReceiptIn)
from app.config import settings
from app.security import (trusted_actor_context, require_any_role, enforce_bank_scope,
                          parse_assertion_keys, verify_service_assertion)
from app.idempotency import IdempotencyMiddleware
from app.audit_governance import (append_case_audit_entry, verify_audit_chain,
                                  require_named_authority, override_request_state,
                                  validate_case_evidence_refs, calculate_audit_entry_sha256)
from app.governance import (build_case_snapshot, calculate_snapshot_sha256,
                            get_latest_case_version, get_version_state, require_governance_role,
                            verify_version_integrity)
from app.workflow_integration import (canonical_json_bytes, sha256_json, sha256_bytes,
                                      sanitize_workflow_event_payload, build_resubmission_impact,
                                      build_export_zip, validate_outbox_transition)
from app.evidence_reconciliation import verify_manifest_chain, manifest_matches_document_metadata
from app.malware_scanner import scan_file as clamav_scan_file, get_clamav_version, MalwareScannerUnavailable
from app.production_readiness import production_configuration_issues
from app.data_handoff import (latest_attestation as _v10_latest_attestation,
                              latest_declarations as _v10_latest_declarations,
                              evaluate_data_readiness as _v10_evaluate_data_readiness,
                              build_financial_input_payload as _v10_build_financial_input_payload,
                              validate_declaration_payload as _v10_validate_declaration_payload)


def _assert_case_bank_scope(case, x_actor_id: str | None, x_actor_roles: str | None, x_bank_id: str | None):
    actor, roles, bank_id = trusted_actor_context(
        x_actor_id, x_actor_roles, x_bank_id, require_bank=True
    )
    require_any_role(
        roles,
        {"DATA_AI_SERVICE", "SYSTEM_ADMIN", "BANK_ADMIN", "BANK_STAFF", "MAKER", "CHECKER", "DATA_AI_STAFF"},
        message="No authorized case access role",
    )
    enforce_bank_scope(
        case.bank_id, bank_id, roles, not_found_message="Case not found"
    )
    return actor, roles

@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    issues = production_configuration_issues(settings)
    if issues:
        raise RuntimeError("Production configuration is incomplete: " + "; ".join(issues))
    yield


app = FastAPI(
    title="UNIT Income & Affordability - DATA AI Service",
    version="10.0.0",
    description=("DATA-AI evidence, document intelligence, provenance, Maker input review and "
                "hash-bound handoff service. Backend owns identity/consent; Camunda owns orchestration; "
                "the external Financial Engine owns calculations and policy. DATA-AI never approves loans."),
    lifespan=app_lifespan,
)


@app.middleware("http")
async def request_correlation_middleware(request: Request, call_next):
    """Attach a server-controlled correlation ID to every HTTP response.

    A caller-provided ID is accepted only when it is a canonical UUID. This
    prevents arbitrary log injection while allowing Backend trace propagation.
    """
    supplied = request.headers.get("x-request-id", "")
    try:
        request_id = str(UUID(supplied)) if supplied else str(uuid4())
    except (ValueError, TypeError, AttributeError):
        request_id = str(uuid4())
    request.state.request_id = request_id
    max_bytes = settings.max_request_body_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                from fastapi.responses import JSONResponse
                response = JSONResponse(status_code=413, content={"detail": "Request body exceeds configured limit"})
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Cache-Control"] = "no-store"
                return response
        except ValueError:
            from fastapi.responses import JSONResponse
            response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            response.headers["X-Request-ID"] = request_id
            return response
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response


async def _authenticate_internal_request(
    request: Request,
    x_internal_service_token: str | None,
    x_service_assertion: str | None,
    x_actor_id: str | None,
    x_actor_roles: str | None,
    x_bank_id: str | None,
    x_idempotency_key: str | None = None,
):
    """Shared authentication path used before idempotent replays and by routes."""
    if getattr(request.state, "internal_service_authenticated", False):
        return
    production = settings.app_env.lower() not in {"development", "test"}
    if not settings.internal_service_token:
        if production:
            raise HTTPException(status_code=503, detail="Internal service authentication is not configured")
    elif not x_internal_service_token or not secrets.compare_digest(
        x_internal_service_token, settings.internal_service_token
    ):
        raise HTTPException(status_code=401, detail="Invalid internal service token")

    try:
        assertion_keys = parse_assertion_keys(settings.service_assertion_keys)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Service assertion keys are misconfigured") from exc

    if not assertion_keys:
        if production:
            raise HTTPException(status_code=503, detail="Signed service assertions are required but not configured")
        request.state.internal_service_authenticated = True
        return  # Explicit local/test compatibility; never permitted in production.

    max_signed_bytes = settings.max_signed_request_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_signed_bytes:
                raise HTTPException(status_code=413, detail="Signed request body exceeds configured limit")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    body = await request.body()
    if len(body) > max_signed_bytes:
        raise HTTPException(status_code=413, detail="Signed request body exceeds configured limit")
    nonce, expires_epoch = verify_service_assertion(
        x_service_assertion, keys=assertion_keys, method=request.method,
        path=request.scope.get("raw_path", request.url.path.encode("ascii", errors="strict")).decode("ascii"),
        query=request.scope.get("query_string", b"").decode("ascii"), body=body,
        actor_id=x_actor_id, actor_roles=x_actor_roles, bank_id=x_bank_id,
        issuer=settings.service_assertion_issuer, audience=settings.service_assertion_audience,
        max_skew_seconds=settings.service_assertion_max_skew_seconds,
        idempotency_key=x_idempotency_key,
    )
    # Persist nonce in an independent transaction so a later business rollback
    # cannot make the assertion reusable. PostgreSQL's PK arbitrates concurrent replay.
    from app.models import ServiceAssertionNonce
    factory = get_session_factory()
    try:
        with factory() as nonce_db:
            nonce_db.query(ServiceAssertionNonce).filter(
                ServiceAssertionNonce.expires_at < datetime.now(timezone.utc)
            ).delete(synchronize_session=False)
            nonce_db.add(ServiceAssertionNonce(
                nonce=nonce, key_id=x_service_assertion.split(".")[1],
                expires_at=datetime.fromtimestamp(expires_epoch, tz=timezone.utc),
            ))
            nonce_db.commit()
    except IntegrityError as exc:
        raise HTTPException(status_code=401, detail="Service assertion replay detected") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Replay protection store is unavailable") from exc
    request.state.internal_service_authenticated = True


async def _authenticate_request_for_idempotency(request: Request):
    """Authenticate the exact signed bytes before middleware can replay a response."""
    headers = request.headers
    await _authenticate_internal_request(
        request,
        headers.get("x-internal-service-token"),
        headers.get("x-service-assertion"),
        headers.get("x-actor-id"),
        headers.get("x-actor-roles"),
        headers.get("x-bank-id"),
        headers.get("idempotency-key"),
    )


async def require_internal_token(
    request: Request,
    x_internal_service_token: str | None = Header(default=None),
    x_service_assertion: str | None = Header(default=None),
    x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    """Authenticate Backend calls; middleware may pre-authenticate replay candidates."""
    await _authenticate_internal_request(
        request, x_internal_service_token, x_service_assertion,
        x_actor_id, x_actor_roles, x_bank_id, request.headers.get("idempotency-key"),
    )


app.add_middleware(
    IdempotencyMiddleware,
    session_factory=get_session_factory,
    authenticator=_authenticate_request_for_idempotency,
    ttl_hours=settings.idempotency_ttl_hours,
    max_request_bytes=settings.idempotency_max_request_mb * 1024 * 1024,
    max_response_bytes=settings.idempotency_max_response_kb * 1024,
    in_progress_timeout_seconds=settings.idempotency_in_progress_timeout_seconds,
)

@app.get("/health", tags=["operations"])
def health():
    return {"status": "ok", "service": "data-ai", "version": "1.0.0"}

@app.get("/ready", tags=["operations"])
def ready(db: Session = Depends(get_db)):
    from sqlalchemy import text
    db.execute(text("SELECT 1"))
    try:
        migration_version = db.execute(text("SELECT version FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 1")).scalar()
    except Exception:
        raise HTTPException(503, "Database reachable but Flyway migrations are not applied")
    if str(migration_version) != str(settings.required_flyway_version):
        raise HTTPException(503, f"Database migration V{settings.required_flyway_version} is required")
    scanner_status = "NOT_CONFIGURED"
    if settings.clamav_host:
        try:
            scanner_status = get_clamav_version(settings.clamav_host, settings.clamav_port, timeout=2.0)
        except MalwareScannerUnavailable:
            raise HTTPException(503, "Malware scanner is unavailable")
    issues = production_configuration_issues(settings)
    if issues:
        raise HTTPException(503, {"detail": "Production prerequisites are incomplete", "issues": issues})
    if settings.app_env.lower() in {"production", "prod"} and scanner_status == "NOT_CONFIGURED":
        raise HTTPException(503, "Malware scanner is required in production")
    return {"status": "ready", "database": "reachable", "flyway_latest_version": migration_version,
            "malware_scanner": scanner_status}

@app.post("/api/v1/cases", response_model=CaseOut, status_code=201, dependencies=[Depends(require_internal_token)])
def create_case(payload: CaseCreate, db: Session = Depends(get_db),
                x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
                x_bank_id: str | None = Header(default=None)):
    if not x_actor_id or not x_bank_id:
        raise HTTPException(401, "Missing trusted Backend context")
    roles = {r.strip().upper() for r in (x_actor_roles or "").replace(";", ",").split(",") if r.strip()}
    if not roles.intersection({"DATA_AI_SERVICE", "SYSTEM_ADMIN", "BANK_ADMIN"}):
        raise HTTPException(403, "Backend service or authorized administrator required")
    if "SYSTEM_ADMIN" not in roles and payload.bank_id != x_bank_id:
        raise HTTPException(403, "Case bank_id is outside authenticated caller scope")
    if db.query(models.Case).filter_by(external_case_id=payload.external_case_id).first():
        raise HTTPException(409, "external_case_id already exists")
    try:
        return repository.create_case(db, payload.external_case_id, payload.bank_id, payload.analysis_date)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "external_case_id already exists") from exc

@app.get("/api/v1/cases/{case_id}", dependencies=[Depends(require_internal_token)])
def get_case(case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
             x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    return {"id": str(case.id), "external_case_id": case.external_case_id,
            "bank_id": case.bank_id, "analysis_date": case.analysis_date,
            "status": case.status, "created_at": case.created_at}

@app.post("/api/v1/cases/{case_id}/documents", response_model=DocumentOut, status_code=201, dependencies=[Depends(require_internal_token)])
async def upload_document(case_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                          x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
                          x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    # Enforce size while streaming into memory for this pilot-sized upload limit.
    content = await file.read(settings.max_file_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_file_mb} MiB")
    saved = None
    try:
        # Keep the document, manifest entry, audit event and workflow outbox row
        # inside one DB transaction. The filesystem object is compensated if
        # that transaction cannot commit.
        saved = service.save_upload(db, case, file.filename or "upload", content,
                                    actor_id=x_actor_id, commit=False)
        _enqueue_case_workflow_event(db, case, "EVIDENCE_DOCUMENT_RECEIVED", {
            "document_id": str(saved.id), "document_sha256": saved.sha256,
            "reason_code": "DOCUMENT_RECEIVED"}, idempotency_key=f"DOCUMENT_RECEIVED:{saved.id}")
        db.commit()
        db.refresh(saved)
        return saved
    except ValueError as exc:
        db.rollback()
        if saved is not None:
            from pathlib import Path as _Path
            _Path(saved.stored_path).unlink(missing_ok=True)
        raise HTTPException(400, str(exc))
    except Exception:
        db.rollback()
        if saved is not None:
            from pathlib import Path as _Path
            _Path(saved.stored_path).unlink(missing_ok=True)
        raise


def _latest_trusted_document_scan(db: Session, document):
    return (db.query(models.DocumentSecurityEvent)
            .filter(models.DocumentSecurityEvent.document_id == document.id,
                    models.DocumentSecurityEvent.event_type == "SCAN_COMPLETED",
                    models.DocumentSecurityEvent.scan_status == "CLEAN",
                    models.DocumentSecurityEvent.scanned_sha256 == document.sha256,
                    models.DocumentSecurityEvent.attestation_version == "V1_CLAMAV",
                    models.DocumentSecurityEvent.engine_name == "ClamAV",
                    models.DocumentSecurityEvent.engine_version.isnot(None))
            .order_by(models.DocumentSecurityEvent.occurred_at.desc(),
                      models.DocumentSecurityEvent.id.desc()).first())


@app.post("/api/v1/cases/{case_id}/documents/{document_id}/security-scan",
          tags=["document-security"], status_code=200,
          dependencies=[Depends(require_internal_token)])
def scan_case_document(case_id: UUID, document_id: UUID, db: Session = Depends(get_db),
                       x_actor_id: str | None = Header(default=None),
                       x_actor_roles: str | None = Header(default=None),
                       x_bank_id: str | None = Header(default=None)):
    """Workflow Service Task: byte-bound ClamAV scan; never fake a CLEAN verdict."""
    case, actor, roles = _workflow_case_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"DOCUMENT_SCANNER"})
    if roles != {"DOCUMENT_SCANNER"}:
        raise HTTPException(403, "A dedicated DOCUMENT_SCANNER service identity is required")
    case = (db.query(models.Case).filter_by(id=case_id).populate_existing()
            .with_for_update().first())
    document = (db.query(models.Document).filter_by(id=document_id, case_id=case_id)
                .populate_existing().with_for_update().first())
    if not case or not document or document.deleted_at is not None:
        raise HTTPException(404, "Case/document not found")
    # Revalidate tenant scope after acquiring the row lock; do not rely on the
    # pre-lock Case instance if its bank assignment changed concurrently.
    _, locked_roles, locked_bank_id = trusted_actor_context(
        x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    enforce_bank_scope(case.bank_id, locked_bank_id, locked_roles, not_found_message="Case not found")
    if document.malware_scan_status == "INFECTED":
        raise HTTPException(409, "Document is quarantined and cannot be rescanned in place")
    if document.malware_scan_status not in {"NOT_SCANNED", "ERROR", "CLEAN"}:
        raise HTTPException(409, "Document is not in a scannable state")
    if not settings.clamav_host:
        raise HTTPException(503, "ClamAV is not configured; document remains untrusted")

    stored_path = Path(document.stored_path)
    try:
        if stored_path.is_symlink():
            raise ValueError("Evidence storage path must not be a symbolic link")
        storage_root = settings.storage_dir.resolve()
        resolved_path = stored_path.resolve(strict=True)
        resolved_path.relative_to(storage_root)
        if not resolved_path.is_file():
            raise ValueError("Evidence storage object is not a regular file")
        before_hash = service.sha256_file(resolved_path).lower()
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(409, "Evidence storage object is missing, unsafe or outside the protected storage root")
    if before_hash != document.sha256.lower():
        security_event = models.DocumentSecurityEvent(
            document_id=document.id, event_type="STORAGE_INTEGRITY_MISMATCH",
            scan_status="ERROR", details={"expected_sha256": document.sha256,
                                            "observed_sha256": before_hash},
            recorded_by=actor,
        )
        db.add(security_event)
        document.processing_status = "BLOCKED"
        db.add(models.AuditEvent(case_id=case.id, actor=actor, action="DOCUMENT_STORAGE_INTEGRITY_MISMATCH",
                                 entity_type="document", entity_id=str(document.id),
                                 details={"document_sha256": document.sha256}))
        _enqueue_case_workflow_event(db, case, "DOCUMENT_INTEGRITY_FAILURE", {
            "document_id": str(document.id), "document_sha256": document.sha256,
            "reason_code": "STORAGE_HASH_MISMATCH"})
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(503, "Evidence integrity incident could not be persisted")
        raise HTTPException(409, "Evidence hash mismatch; document has been blocked and an incident event recorded")

    # A repeat scan request is idempotent only after verifying the current bytes
    # still match both the document record and the previously stored attestation.
    if document.malware_scan_status == "CLEAN":
        previous = _latest_trusted_document_scan(db, document)
        if previous:
            return {"document_id": str(document.id), "scan_status": "CLEAN",
                    "scanned_sha256": document.sha256, "engine": previous.engine_name,
                    "engine_version": previous.engine_version, "idempotent": True}
        # Legacy CLEAN values are rescanned in place; no legacy row is trusted.

    try:
        result = clamav_scan_file(
            resolved_path, host=settings.clamav_host, port=settings.clamav_port,
            timeout=settings.clamav_timeout_seconds, chunk_size=settings.clamav_chunk_kb * 1024,
            max_bytes=settings.max_file_mb * 1024 * 1024,
        )
    except MalwareScannerUnavailable as exc:
        raise HTTPException(503, "Malware scanner unavailable; document remains untrusted") from exc

    try:
        after_hash = service.sha256_file(resolved_path).lower()
    except OSError as exc:
        raise HTTPException(503, "Evidence storage integrity could not be rechecked after scanning") from exc
    if (after_hash != before_hash or after_hash != document.sha256.lower()
            or result.scanned_sha256.lower() != document.sha256.lower()):
        document.processing_status = "BLOCKED"
        document.evidence_status = "QUARANTINED"
        db.add(models.DocumentSecurityEvent(
            document_id=document.id, event_type="STORAGE_INTEGRITY_MISMATCH",
            scan_status="ERROR", details={"expected_sha256": document.sha256,
                                            "before_scan_sha256": before_hash,
                                            "scanner_stream_sha256": result.scanned_sha256,
                                            "after_scan_sha256": after_hash},
            recorded_by=actor,
        ))
        db.add(models.AuditEvent(case_id=case.id, actor=actor,
            action="DOCUMENT_STORAGE_CHANGED_DURING_SCAN", entity_type="document",
            entity_id=str(document.id), details={"document_sha256": document.sha256}))
        _enqueue_case_workflow_event(db, case, "DOCUMENT_INTEGRITY_FAILURE", {
            "document_id": str(document.id), "document_sha256": document.sha256,
            "reason_code": "STORAGE_CHANGED_DURING_SCAN"})
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(503, "Evidence integrity incident could not be persisted")
        raise HTTPException(409, "Evidence changed during scanning; document was blocked and no CLEAN verdict was recorded")

    now = datetime.now(timezone.utc)
    quarantine_path = None
    quarantine_moved = False
    try:
        event = models.DocumentSecurityEvent(
            document_id=document.id,
            event_type="SCAN_COMPLETED" if result.status == "CLEAN" else "SCAN_INFECTED",
            scan_status=result.status, engine_name=result.engine_name,
            engine_version=result.engine_version, scanned_sha256=after_hash,
            attestation_version="V1_CLAMAV",
            details={"protocol": "INSTREAM", "file_size": document.file_size,
                     "scanner_reply": result.scanner_reply,
                     "storage_hash_verified_before_and_after": True},
            occurred_at=now, recorded_by=actor,
        )
        db.add(event)
        db.flush()
        document.malware_scan_status = result.status
        document.malware_scanned_at = now
        document.malware_scan_engine = result.engine_name
        if result.status == "INFECTED":
            quarantine_dir = (settings.storage_dir / "_quarantine").resolve()
            quarantine_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                quarantine_dir.chmod(0o700)
            except OSError:
                pass
            quarantine_path = quarantine_dir / f"{document.id}-{document.sha256}{Path(document.original_filename).suffix.lower()}"
            if quarantine_path.exists():
                quarantine_path = quarantine_dir / f"{document.id}-{uuid4().hex}.quarantine"
            import os
            os.replace(resolved_path, quarantine_path)
            quarantine_moved = True
            document.stored_path = str(quarantine_path)
            document.evidence_status = "QUARANTINED"
            document.processing_status = "BLOCKED"
        db.add(models.AuditEvent(
            case_id=case.id, actor=actor,
            action="DOCUMENT_SCAN_CLEAN" if result.status == "CLEAN" else "DOCUMENT_QUARANTINED",
            entity_type="document", entity_id=str(document.id),
            details={"document_sha256": document.sha256, "engine": result.engine_name,
                     "engine_version": result.engine_version, "scan_status": result.status,
                     "attestation_version": "V1_CLAMAV"},
        ))
        _enqueue_case_workflow_event(db, case,
            "DOCUMENT_SCAN_CLEAN" if result.status == "CLEAN" else "DOCUMENT_QUARANTINED", {
                "document_id": str(document.id), "document_sha256": document.sha256,
                "scanned_sha256": result.scanned_sha256.lower(),
                "reason_code": "SCAN_CLEAN" if result.status == "CLEAN" else "MALWARE_DETECTED",
            }, idempotency_key=f"DOCUMENT_SCAN:{document.id}:{document.sha256}")
        db.commit()
    except Exception:
        db.rollback()
        if quarantine_moved and quarantine_path is not None and quarantine_path.exists():
            import os
            os.replace(quarantine_path, resolved_path)
        raise
    return {"document_id": str(document.id), "scan_status": result.status,
            "scanned_sha256": after_hash, "engine": result.engine_name,
            "engine_version": result.engine_version,
            "evidence_status": document.evidence_status,
            "processing_allowed": result.status == "CLEAN"}

@app.post("/api/v1/cases/{case_id}/documents/{document_id}/process", dependencies=[Depends(require_internal_token)])
def process(case_id: UUID, document_id: UUID, db: Session = Depends(get_db),
            x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
            x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if case:
        _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    doc = db.query(models.Document).filter_by(id=document_id, case_id=case_id).first()
    if not case or not doc:
        raise HTTPException(404, "Case/document not found")
    if doc.malware_scan_status != "CLEAN" or _latest_trusted_document_scan(db, doc) is None:
        raise HTTPException(409, "OCR is blocked until a byte-bound ClamAV CLEAN attestation exists")
    try:
        return service.process_document(db, case, doc)
    except service.EvidenceIntegrityError as exc:
        db.rollback()
        locked_case = (db.query(models.Case).filter_by(id=case_id).populate_existing()
                       .with_for_update().first())
        locked_doc = (db.query(models.Document).filter_by(id=document_id, case_id=case_id)
                      .populate_existing().with_for_update().first())
        if locked_case is None or locked_doc is None:
            raise HTTPException(404, "Case/document not found") from exc
        _, locked_roles, caller_bank = trusted_actor_context(
            x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
        enforce_bank_scope(locked_case.bank_id, caller_bank,
                           locked_roles, not_found_message="Case not found")
        locked_doc.processing_status = "BLOCKED"
        locked_doc.evidence_status = "QUARANTINED"
        db.add(models.DocumentSecurityEvent(
            document_id=locked_doc.id, event_type="STORAGE_INTEGRITY_FAILURE",
            scan_status="ERROR", details={"reason": str(exc)[:240],
                                           "expected_sha256": locked_doc.sha256},
            recorded_by=x_actor_id or "data-ai-service"))
        db.add(models.AuditEvent(case_id=locked_case.id, actor=x_actor_id or "data-ai-service",
            action="DOCUMENT_PROCESSING_INTEGRITY_FAILURE", entity_type="document",
            entity_id=str(locked_doc.id), details={"document_sha256": locked_doc.sha256}))
        _enqueue_case_workflow_event(db, locked_case, "DOCUMENT_INTEGRITY_FAILURE", {
            "document_id": str(locked_doc.id), "document_sha256": locked_doc.sha256,
            "reason_code": "STORAGE_INTEGRITY_FAILURE"})
        try:
            db.commit()
        except Exception as persist_exc:
            db.rollback()
            raise HTTPException(503, "Evidence integrity failure could not be persisted") from persist_exc
        raise HTTPException(409, "Stored evidence integrity failed; document is blocked and Maker review is required") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, f"Processing failed: {type(exc).__name__}")

@app.get("/api/v1/cases/{case_id}/documents", dependencies=[Depends(require_internal_token)])
def documents(case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
              x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    return repository.list_case_documents(db, case_id)

@app.get("/api/v1/cases/{case_id}/transactions", dependencies=[Depends(require_internal_token)])
def transactions(case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                 x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    return repository.list_case_transactions(db, case_id)

@app.get("/api/v1/cases/{case_id}/fields", dependencies=[Depends(require_internal_token)])
def extracted_fields(case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                     x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    return (db.query(models.ExtractedField)
            .join(models.Document, models.Document.id == models.ExtractedField.document_id)
            .filter(models.Document.case_id == case_id)
            .order_by(models.ExtractedField.created_at).all())


@app.get("/api/v1/admin/ocr/catalog", tags=["ocr-governance"], response_model=OCRCatalogOut,
         dependencies=[Depends(require_internal_token)])
def ocr_governance_catalog(x_actor_id: str | None = Header(default=None),
                          x_actor_roles: str | None = Header(default=None),
                          x_bank_id: str | None = Header(default=None)):
    """Read-only provisional layout/field catalogue; not a bank approval endpoint."""
    _, roles, _ = trusted_actor_context(x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    require_any_role(roles, {"SYSTEM_ADMIN", "BANK_ADMIN", "DATA_AI_STAFF", "DATA_AI_SERVICE"},
                     message="OCR catalogue access requires an authorized service or administrator role")
    from app.document_intelligence import get_ocr_catalog
    return get_ocr_catalog()

# ---- Customer form snapshots and staff-only Excel export -----------------
from fastapi import Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from app.schemas import ApplicantSubmissionIn
from app.export_service import build_data_workbook
import json

@app.post("/api/v1/cases/{case_id}/applicant-submissions", status_code=201,
          dependencies=[Depends(require_internal_token)], tags=["applicant-data"])
def create_applicant_submission(
    case_id: UUID,
    payload: ApplicantSubmissionIn,
    x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Backend-to-DATA-AI endpoint. Backend must validate consent and allowed form fields first."""
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    if len(json.dumps(payload.form_data, ensure_ascii=False, default=str).encode("utf-8")) > 100_000:
        raise HTTPException(413, "Applicant form payload exceeds 100 KB")
    existing = db.query(models.ApplicantSubmission).filter_by(
        case_id=case_id, applicant_ref=payload.applicant_ref, form_version=payload.form_version
    ).first()
    if existing:
        raise HTTPException(409, "This applicant form version already exists; submit a new form_version")
    obj = models.ApplicantSubmission(
        case_id=case_id,
        applicant_ref=payload.applicant_ref,
        form_version=payload.form_version,
        form_data=payload.form_data,
        consent_reference=payload.consent_reference,
        submitted_by=(x_actor_id or "backend")[:120],
    )
    db.add(obj)
    db.add(models.AuditEvent(case_id=case_id, actor=(x_actor_id or "backend")[:100],
        action="APPLICANT_FORM_RECEIVED", entity_type="applicant_submission",
        entity_id=payload.applicant_ref, details={"form_version": payload.form_version}))
    db.commit()
    db.refresh(obj)
    return {"id": str(obj.id), "case_id": str(obj.case_id), "applicant_ref": obj.applicant_ref,
            "form_version": obj.form_version, "submitted_at": obj.submitted_at.isoformat()}


def require_export_staff(
    x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    roles = {r.strip().upper() for r in (x_actor_roles or "").replace(";", ",").split(",") if r.strip()}
    if not x_actor_id or not x_bank_id:
        raise HTTPException(401, "Missing trusted actor or bank context from Backend")
    if not roles.intersection({"STAFF", "BANK_STAFF", "DATA_AI_STAFF", "MAKER", "CHECKER", "BANK_ADMIN", "SYSTEM_ADMIN"}):
        raise HTTPException(403, "Staff role required to export data")
    return {"actor_id": x_actor_id[:120], "bank_id": x_bank_id[:100], "roles": sorted(roles)}

@app.get("/api/v1/admin/exports/excel", dependencies=[Depends(require_internal_token)],
         tags=["data-export"])
def export_excel(
    case_id: UUID | None = Query(default=None),
    staff=Depends(require_export_staff),
    db: Session = Depends(get_db),
):
    """Create an XLSX snapshot for the staff member's bank. Backend must overwrite identity headers."""
    if case_id:
        case = repository.get_case(db, case_id)
        if not case or case.bank_id != staff["bank_id"]:
            raise HTTPException(404, "Case not found in caller bank scope")
    output, counts = build_data_workbook(db, staff["bank_id"], case_id)
    job = models.ExportJob(bank_id=staff["bank_id"], requested_by=staff["actor_id"],
        export_scope="BOTH", filters={"case_id": str(case_id) if case_id else None},
        row_counts=counts, status="COMPLETED")
    db.add(job)
    export_bank = db.query(models.BankOrganization).filter_by(bank_code=staff["bank_id"]).first()
    db.add(models.ManagementAuditLog(bank_id=export_bank.id if export_bank else None, actor_external_id=staff["actor_id"], action="DATA_EXCEL_EXPORTED",
        target_type="export_job", target_id=str(job.id),
        after_data={"scope": "BOTH", "row_counts": counts, "bank_id": staff["bank_id"],
                    "case_id": str(case_id) if case_id else None}))
    if case_id:
        db.add(models.AuditEvent(case_id=case_id, actor=staff["actor_id"], action="DATA_EXCEL_EXPORTED",
            entity_type="export", entity_id=str(job.id), details={"scope": "BOTH", "row_counts": counts,
            "bank_id": staff["bank_id"]}))
    db.commit()
    filename = f"data_ai_export_{job.id}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"',
               "X-Export-Id": str(job.id), "Cache-Control": "no-store"}
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers)

@app.get("/api/v1/admin/exports/history", dependencies=[Depends(require_internal_token)],
         tags=["data-export"])
def export_history(staff=Depends(require_export_staff), db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    rows = db.query(models.ExportJob).filter_by(bank_id=staff["bank_id"]).order_by(models.ExportJob.created_at.desc()).limit(limit).all()
    return [{"id": str(r.id), "requested_by": r.requested_by, "scope": r.export_scope,
             "filters": r.filters, "row_counts": r.row_counts, "status": r.status,
             "created_at": r.created_at} for r in rows]

# ---- Customer / staff / configurable form management ----------------------
from datetime import datetime, timezone, timedelta
from pathlib import Path
from app.schemas import CustomerCreate, CustomerUpdate, LoanApplicationCreate, StaffSyncIn, FormDefinitionUpdate, BankOrganizationIn, BankBranchIn


def _validate_form_values(fields, form_data):
    import re
    from decimal import Decimal, InvalidOperation
    from datetime import date as date_type
    errors = []
    for field in fields:
        key = field.field_key
        value = form_data.get(key)
        if field.is_required and value in (None, ""):
            errors.append(key)
            continue
        if value in (None, ""):
            continue
        rules = field.validation_json or {}
        try:
            if field.data_type == "number":
                number = Decimal(str(value))
                if "minimum" in rules and number < Decimal(str(rules["minimum"])): errors.append(key)
                if "maximum" in rules and number > Decimal(str(rules["maximum"])): errors.append(key)
            elif field.data_type == "date":
                date_type.fromisoformat(str(value))
            elif field.data_type in {"text", "email", "phone", "select", "textarea"}:
                if not isinstance(value, str): errors.append(key); continue
                if "max_length" in rules and len(value) > int(rules["max_length"]): errors.append(key)
                pattern = rules.get("pattern")
                if pattern and not re.fullmatch(pattern, value): errors.append(key)
                options = field.options_json or rules.get("options")
                if field.data_type == "select" and options and value not in options: errors.append(key)
            elif field.data_type == "checkbox" and not isinstance(value, bool):
                errors.append(key)
        except (ValueError, InvalidOperation, TypeError):
            errors.append(key)
    return sorted(set(errors))


def _customer_out(customer, db):
    address = db.query(models.CustomerAddress).filter_by(customer_id=customer.id).order_by(models.CustomerAddress.is_primary.desc()).first()
    employment = db.query(models.CustomerEmployment).filter_by(customer_id=customer.id).order_by(models.CustomerEmployment.is_current.desc()).first()
    return {
        "id": str(customer.id), "customer_code": customer.customer_code,
        "full_name": customer.full_name, "date_of_birth": customer.date_of_birth,
        "phone": customer.phone, "email": customer.email,
        "customer_status": customer.customer_status,
        "address": ({"address_type": address.address_type, "country_code": address.country_code,
                     "province_code": address.province_code, "province_name": address.province_name,
                     "district_name": address.district_name, "ward_name": address.ward_name,
                     "street_address": address.street_address} if address else None),
        "employment": ({"employment_type": employment.employment_type, "employer_name": employment.employer_name,
                        "job_title": employment.job_title,
                        "monthly_income_declared": employment.monthly_income_declared,
                        "income_basis": employment.income_basis, "income_currency": employment.income_currency,
                        "is_current": employment.is_current} if employment else None),
        "created_at": customer.created_at, "updated_at": customer.updated_at,
    }


@app.post("/api/v1/customers", status_code=201, tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    actor, bank_scope_id, roles = _customer_bank_scope(x_actor_id, x_actor_roles, x_bank_id, db)
    if bank_scope_id is not None and payload.bank_id not in (None, bank_scope_id):
        raise HTTPException(403, "Customer bank_id must match authenticated bank scope")
    if bank_scope_id is not None:
        payload.bank_id = bank_scope_id
    if db.query(models.CustomerProfile).filter_by(customer_code=payload.customer_code).first():
        raise HTTPException(409, "customer_code already exists")
    if payload.bank_id and not db.query(models.BankOrganization).filter_by(id=payload.bank_id).first():
        raise HTTPException(400, "Unknown bank_id")
    customer = models.CustomerProfile(**payload.model_dump(exclude={"address", "employment"}))
    db.add(customer)
    db.flush()
    if payload.address:
        db.add(models.CustomerAddress(customer_id=customer.id, **payload.address.model_dump()))
    if payload.employment:
        db.add(models.CustomerEmployment(customer_id=customer.id, **payload.employment.model_dump()))
    db.add(models.ManagementAuditLog(bank_id=customer.bank_id, actor_external_id=x_actor_id or "backend", action="CUSTOMER_CREATED",
        target_type="customer", target_id=str(customer.id), after_data={"customer_code": customer.customer_code}))
    db.commit(); db.refresh(customer)
    return _customer_out(customer, db)


@app.get("/api/v1/customers/{customer_id}", tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def get_customer(customer_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                 x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    _, bank_scope_id, _ = _customer_bank_scope(x_actor_id, x_actor_roles, x_bank_id, db)
    query = db.query(models.CustomerProfile).filter_by(id=customer_id)
    if bank_scope_id is not None:
        query = query.filter(models.CustomerProfile.bank_id == bank_scope_id)
    customer = query.first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    db.add(models.ManagementAuditLog(bank_id=customer.bank_id, actor_external_id=x_actor_id,
        action="CUSTOMER_VIEWED", target_type="customer", target_id=str(customer.id),
        after_data={"access_scope": "DETAIL"}))
    db.commit()
    return _customer_out(customer, db)


@app.get("/api/v1/customers", tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def list_customers(bank_id: UUID | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                   x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    _, bank_scope_id, _ = _customer_bank_scope(x_actor_id, x_actor_roles, x_bank_id, db)
    query = db.query(models.CustomerProfile)
    if bank_scope_id is not None:
        if bank_id is not None and bank_id != bank_scope_id:
            raise HTTPException(403, "Requested bank_id is outside authenticated bank scope")
        query = query.filter(models.CustomerProfile.bank_id == bank_scope_id)
    elif bank_id:
        query = query.filter(models.CustomerProfile.bank_id == bank_id)
    rows = query.order_by(models.CustomerProfile.created_at.desc()).offset(offset).limit(limit).all()
    db.add(models.ManagementAuditLog(bank_id=bank_scope_id, actor_external_id=x_actor_id,
        action="CUSTOMER_LIST_VIEWED", target_type="customer_collection", target_id=None,
        after_data={"result_count": len(rows), "limit": limit, "offset": offset}))
    db.commit()
    return [_customer_out(c, db) for c in rows]


@app.patch("/api/v1/customers/{customer_id}", tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def update_customer(customer_id: UUID, payload: CustomerUpdate, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    actor, bank_scope_id, _ = _customer_bank_scope(x_actor_id, x_actor_roles, x_bank_id, db)
    query = db.query(models.CustomerProfile).filter_by(id=customer_id)
    if bank_scope_id is not None:
        query = query.filter(models.CustomerProfile.bank_id == bank_scope_id)
    customer = query.first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    update_data = payload.model_dump(exclude_unset=True)
    address_data = update_data.pop("address", None)
    employment_data = update_data.pop("employment", None)
    before = {k: getattr(customer, k) for k in update_data}
    for key, value in update_data.items():
        setattr(customer, key, value)
    if address_data is not None:
        address = db.query(models.CustomerAddress).filter_by(customer_id=customer.id, is_primary=True).first()
        if address is None:
            address = models.CustomerAddress(customer_id=customer.id, **address_data)
            db.add(address)
        else:
            for key, value in address_data.items(): setattr(address, key, value)
    if employment_data is not None:
        employment = db.query(models.CustomerEmployment).filter_by(customer_id=customer.id, is_current=True).first()
        if employment is None:
            employment = models.CustomerEmployment(customer_id=customer.id, **employment_data)
            db.add(employment)
        else:
            for key, value in employment_data.items(): setattr(employment, key, value)
    customer.updated_at = datetime.now(timezone.utc)
    db.add(models.ManagementAuditLog(bank_id=customer.bank_id, actor_external_id=x_actor_id or "backend", action="CUSTOMER_UPDATED",
        target_type="customer", target_id=str(customer.id), before_data={k: str(v) if v is not None else None for k,v in before.items()},
        after_data=payload.model_dump(exclude_unset=True, mode="json")))
    db.commit(); db.refresh(customer)
    return _customer_out(customer, db)


@app.post("/api/v1/customers/{customer_id}/applications", status_code=201, tags=["application-management"], dependencies=[Depends(require_internal_token)])
def create_customer_application(customer_id: UUID, payload: LoanApplicationCreate, db: Session = Depends(get_db),
                                x_actor_id: str | None = Header(default=None),
                                x_actor_roles: str | None = Header(default=None),
                                x_bank_id: str | None = Header(default=None)):
    actor, roles, caller_bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"DATA_AI_SERVICE", "SYSTEM_ADMIN", "BANK_ADMIN", "BANK_STAFF", "MAKER"}):
        raise HTTPException(403, "Backend service or authorized bank role required")
    if "SYSTEM_ADMIN" not in roles and caller_bank_code != payload.bank_id:
        raise HTTPException(403, "Application bank_id is outside authenticated caller scope")
    customer = db.query(models.CustomerProfile).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    bank = db.query(models.BankOrganization).filter_by(bank_code=payload.bank_id, status="ACTIVE").first()
    if not bank:
        raise HTTPException(400, "Unknown or inactive bank_id. Register the bank organization first.")
    if customer.bank_id and customer.bank_id != bank.id:
        raise HTTPException(403, "Customer does not belong to the requested bank")
    if customer.bank_id is None:
        customer.bank_id = bank.id
    employment = (db.query(models.CustomerEmployment)
                  .filter_by(customer_id=customer.id, is_current=True)
                  .order_by(models.CustomerEmployment.created_at.desc()).first())
    if (not employment or employment.employment_type != "SALARIED" or not employment.employer_name
            or not employment.monthly_income_declared or employment.monthly_income_declared <= 0
            or employment.income_basis not in {"NET", "GROSS"}):
        raise HTTPException(422, "Current salaried employment, positive declared income and NET/GROSS basis are required")
    if db.query(models.Case).filter_by(external_case_id=payload.external_case_id).first():
        raise HTTPException(409, "external_case_id already exists")
    case = models.Case(external_case_id=payload.external_case_id, bank_id=payload.bank_id, customer_id=customer.id, status="SUBMITTED")
    db.add(case); db.flush()
    application = models.LoanApplication(case_id=case.id, customer_id=customer.id,
        product_code=payload.product_code, requested_amount=payload.requested_amount,
        requested_term_months=payload.requested_term_months, loan_purpose=payload.loan_purpose,
        preferred_disbursement_account_last4=payload.preferred_disbursement_account_last4)
    db.add(application)
    address = db.query(models.CustomerAddress).filter_by(customer_id=customer.id).order_by(models.CustomerAddress.is_primary.desc()).first()
    employment = db.query(models.CustomerEmployment).filter_by(customer_id=customer.id).order_by(models.CustomerEmployment.is_current.desc()).first()
    incoming_form_data = dict(payload.form_data)
    # Snapshot only the approved v1.1 intake fields. Do not copy legacy/optional PII
    # columns into the customer's submitted form snapshot.
    form_data = {
        "full_name": customer.full_name,
        "date_of_birth": str(customer.date_of_birth) if customer.date_of_birth else None,
        "phone": customer.phone,
        "email": customer.email,
        "residency_declaration": incoming_form_data.get("residency_declaration"),
        "province_name": address.province_name if address else None,
        "ward_name": address.ward_name if address else None,
        "street_address": address.street_address if address else None,
        "employment_type": employment.employment_type,
        "employer_name": employment.employer_name,
        "job_title": employment.job_title,
        "monthly_income_declared": str(employment.monthly_income_declared),
        "income_basis": employment.income_basis,
        "salary_paid_to_bank": incoming_form_data.get("salary_paid_to_bank"),
        "requested_amount": str(payload.requested_amount),
        "requested_term_months": payload.requested_term_months,
        "loan_purpose": payload.loan_purpose,
        "consent": incoming_form_data.get("consent"),
    }
    active_form = db.query(models.FormDefinition).filter_by(form_code="CUSTOMER_LOAN_APPLICATION", is_active=True).order_by(models.FormDefinition.created_at.desc()).first()
    if not active_form:
        raise HTTPException(503, "No active CUSTOMER_LOAN_APPLICATION form is configured")
    if active_form.version != payload.form_version:
        raise HTTPException(409, f"Form version mismatch. Active version is {active_form.version}")
    if active_form:
        configured_fields = db.query(models.FormFieldDefinition).filter_by(form_definition_id=active_form.id, is_active=True).all()
        invalid_fields = _validate_form_values(configured_fields, form_data)
        if invalid_fields:
            raise HTTPException(422, {"message": "Application form contains missing or invalid fields", "fields": invalid_fields})
    db.add(models.ApplicantSubmission(case_id=case.id, applicant_ref=customer.customer_code,
        form_version=payload.form_version, form_data=form_data, consent_reference=payload.consent_reference,
        submitted_by=x_actor_id or "backend"))
    db.add(models.ManagementAuditLog(bank_id=bank.id, actor_external_id=x_actor_id or "backend", action="APPLICATION_CREATED",
        target_type="loan_application", target_id=str(application.id), after_data={"case_id": str(case.id), "customer_id": str(customer.id)}))
    db.commit(); db.refresh(application)
    return {"case_id": str(case.id), "application_id": str(application.id), "customer_id": str(customer.id),
        "external_case_id": case.external_case_id, "application_status": application.application_status,
        "submitted_at": application.submitted_at}


def _trusted_staff_context(x_actor_id: str | None, x_actor_roles: str | None, x_bank_id: str | None):
    actor, roles, bank_code = trusted_actor_context(
        x_actor_id, x_actor_roles, x_bank_id, require_bank=True
    )
    return actor, roles, bank_code


def _customer_bank_scope(x_actor_id, x_actor_roles, x_bank_id, db):
    actor, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if "SYSTEM_ADMIN" in roles:
        return actor, None, roles
    if not roles.intersection({"BANK_ADMIN", "BANK_STAFF", "DATA_AI_STAFF", "MAKER", "CHECKER"}):
        raise HTTPException(403, "Customer data access requires an authorized bank role")
    bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code, status="ACTIVE").first()
    if not bank:
        raise HTTPException(403, "Unknown or inactive caller bank scope")
    return actor, bank.id, roles


def _assert_customer_scope(customer, bank_scope_id):
    if bank_scope_id is not None and customer.bank_id != bank_scope_id:
        # Avoid disclosing whether a customer exists in another bank.
        raise HTTPException(404, "Customer not found")


@app.post("/api/v1/internal/staff-sync", tags=["staff-management"], dependencies=[Depends(require_internal_token)])
def sync_staff(payload: StaffSyncIn, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None)):
    """Mirror staff identity and roles from Backend/SSO. No password or credential is stored here."""
    if payload.bank_id and not db.query(models.BankOrganization).filter_by(id=payload.bank_id).first():
        raise HTTPException(400, "Unknown staff bank_id")
    if payload.branch_id:
        branch = db.query(models.BankBranch).filter_by(id=payload.branch_id).first()
        if not branch or branch.bank_id != payload.bank_id:
            raise HTTPException(400, "Staff branch must belong to the selected bank")
    staff = db.query(models.StaffUser).filter_by(employee_code=payload.employee_code).first()
    if not staff:
        staff = models.StaffUser(employee_code=payload.employee_code, full_name=payload.full_name, email=payload.email)
        db.add(staff)
    staff.full_name = payload.full_name; staff.email = payload.email; staff.bank_id = payload.bank_id
    staff.branch_id = payload.branch_id; staff.phone = payload.phone; staff.staff_type = payload.staff_type
    staff.external_identity_id = payload.external_identity_id; staff.status = "ACTIVE"
    db.flush()
    desired_roles = set(r.upper() for r in payload.roles)
    existing_links = db.query(models.StaffUserRole).filter_by(staff_user_id=staff.id).all()
    for existing_link in existing_links:
        existing_role = db.query(models.AccessRole).filter_by(id=existing_link.role_id).first()
        if existing_role and existing_role.role_code not in desired_roles:
            db.add(models.StaffRoleAssignmentHistory(
                staff_user_id=staff.id, role_id=existing_link.role_id, action="REVOKED",
                changed_by_external_id=(x_actor_id or "backend")[:160], reason="Backend/SSO role sync"
            ))
            db.delete(existing_link)
    assigned = []
    for role_code in desired_roles:
        role = db.query(models.AccessRole).filter_by(role_code=role_code).first()
        if not role:
            raise HTTPException(400, f"Unsupported role: {role_code}")
        link = db.query(models.StaffUserRole).filter_by(staff_user_id=staff.id, role_id=role.id).first()
        if not link:
            db.add(models.StaffUserRole(staff_user_id=staff.id, role_id=role.id))
            db.add(models.StaffRoleAssignmentHistory(
                staff_user_id=staff.id, role_id=role.id, action="ASSIGNED",
                changed_by_external_id=(x_actor_id or "backend")[:160], reason="Backend/SSO role sync"
            ))
        assigned.append(role_code)
    db.add(models.ManagementAuditLog(bank_id=payload.bank_id, actor_external_id=x_actor_id or "backend", action="STAFF_SYNCED",
        target_type="staff_user", target_id=str(staff.id), after_data={"roles": assigned}))
    db.commit()
    return {"staff_id": str(staff.id), "employee_code": staff.employee_code, "roles": assigned, "status": staff.status}


@app.get("/api/v1/admin/access-control/catalog", tags=["access-control"], dependencies=[Depends(require_internal_token)])
def access_control_catalog(db: Session = Depends(get_db)):
    """Read-only role/permission catalogue. Backend/SSO remains the authorization authority."""
    roles = db.query(models.AccessRole).order_by(models.AccessRole.role_code).all()
    permissions = db.query(models.Permission).order_by(models.Permission.permission_code).all()
    links = db.query(models.RolePermission).all()
    permission_codes = {p.id: p.permission_code for p in permissions}
    by_role = {}
    for link in links:
        by_role.setdefault(link.role_id, []).append(permission_codes.get(link.permission_id))
    return {
        "authority": "BACKEND_SSO",
        "roles": [{"role_code": r.role_code, "role_name": r.role_name,
                   "description": r.description, "permissions": sorted(x for x in by_role.get(r.id, []) if x)}
                  for r in roles],
        "permissions": [{"permission_code": p.permission_code, "resource": p.resource,
                         "action": p.action, "description": p.description} for p in permissions]
    }


@app.get("/api/v1/admin/staff/{staff_id}/role-history", tags=["access-control"], dependencies=[Depends(require_internal_token)])
def staff_role_history(staff_id: UUID, db: Session = Depends(get_db),
                       x_actor_id: str | None = Header(default=None),
                       x_actor_roles: str | None = Header(default=None),
                       x_bank_id: str | None = Header(default=None)):
    actor, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    staff = db.query(models.StaffUser).filter_by(id=staff_id).first()
    if not staff:
        raise HTTPException(404, "Staff not found")
    if "SYSTEM_ADMIN" not in roles:
        bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
        if not bank or staff.bank_id != bank.id:
            raise HTTPException(404, "Staff not found")
    rows = (db.query(models.StaffRoleAssignmentHistory)
            .filter_by(staff_user_id=staff_id)
            .order_by(models.StaffRoleAssignmentHistory.changed_at.desc()).limit(200).all())
    role_map = {r.id: r.role_code for r in db.query(models.AccessRole).all()}
    return [{"role_code": role_map.get(row.role_id), "action": row.action,
             "changed_by": row.changed_by_external_id, "reason": row.reason,
             "changed_at": row.changed_at.isoformat()} for row in rows]


@app.get("/api/v1/admin/forms/{form_code}", tags=["form-management"], dependencies=[Depends(require_internal_token)])
def get_form_definition(form_code: str, db: Session = Depends(get_db)):
    form = db.query(models.FormDefinition).filter_by(form_code=form_code, is_active=True).order_by(models.FormDefinition.created_at.desc()).first()
    if not form:
        raise HTTPException(404, "Active form not found")
    fields = db.query(models.FormFieldDefinition).filter_by(form_definition_id=form.id, is_active=True).order_by(models.FormFieldDefinition.display_order).all()
    return {"form_code": form.form_code, "form_name": form.form_name, "version": form.version,
        "audience": form.audience, "definition": form.definition_json,
        "fields": [{"field_key": f.field_key, "field_label": f.field_label, "data_type": f.data_type,
            "is_required": f.is_required, "is_sensitive": f.is_sensitive, "display_order": f.display_order,
            "validation": f.validation_json, "options": f.options_json} for f in fields]}


@app.put("/api/v1/admin/forms/{form_code}", tags=["form-management"], dependencies=[Depends(require_internal_token)])
def publish_form_definition(form_code: str, payload: FormDefinitionUpdate, db: Session = Depends(get_db),
                            x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
                            x_bank_id: str | None = Header(default=None)):
    actor, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    form_bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
    if "SYSTEM_ADMIN" not in roles and not form_bank:
        raise HTTPException(404, "Bank scope not found")
    if len(payload.fields) > 150:
        raise HTTPException(422, "A form can contain at most 150 fields")
    db.query(models.FormDefinition).filter_by(form_code=form_code, is_active=True).update({"is_active": False})
    form = models.FormDefinition(form_code=form_code, form_name=payload.form_name, version=payload.version,
        audience=payload.audience, definition_json=payload.definition_json, is_active=True)
    db.add(form); db.flush()
    for index, item in enumerate(payload.fields):
        key = item.get("field_key"); label = item.get("field_label"); dtype = item.get("data_type", "text")
        if not key or not label or dtype not in {"text", "email", "phone", "date", "number", "select", "checkbox", "textarea"}:
            db.rollback(); raise HTTPException(422, "Each field requires field_key, field_label and a supported data_type")
        db.add(models.FormFieldDefinition(form_definition_id=form.id, field_key=key, field_label=label,
            data_type=dtype, is_required=bool(item.get("is_required", False)),
            is_sensitive=bool(item.get("is_sensitive", False)), display_order=int(item.get("display_order", index)),
            validation_json=item.get("validation", {}), options_json=item.get("options", [])))
    db.add(models.ManagementAuditLog(bank_id=form_bank.id if form_bank else None, actor_external_id=actor, action="FORM_VERSION_PUBLISHED",
        target_type="form_definition", target_id=str(form.id), after_data={"form_code": form_code, "version": payload.version}))
    db.commit()
    return {"form_code": form_code, "version": payload.version, "field_count": len(payload.fields), "status": "PUBLISHED"}

@app.get("/api/v1/admin/staff", tags=["staff-management"], dependencies=[Depends(require_internal_token)])
def list_staff(db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
               x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
               limit: int = Query(100, ge=1, le=300)):
    _, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
    query = db.query(models.StaffUser)
    if "SYSTEM_ADMIN" not in roles:
        if not bank:
            raise HTTPException(404, "Bank scope not found")
        query = query.filter(models.StaffUser.bank_id == bank.id)
    staff_rows = query.order_by(models.StaffUser.created_at.desc()).limit(limit).all()
    output = []
    for item in staff_rows:
        role_rows = (db.query(models.AccessRole.role_code).join(models.StaffUserRole,
            models.StaffUserRole.role_id == models.AccessRole.id).filter(models.StaffUserRole.staff_user_id == item.id).all())
        output.append({"id": str(item.id), "employee_code": item.employee_code, "full_name": item.full_name,
            "email": item.email, "phone": item.phone, "staff_type": item.staff_type,
            "status": item.status, "roles": [r[0] for r in role_rows]})
    return output


@app.get("/api/v1/admin/audit-logs", tags=["management-audit"], dependencies=[Depends(require_internal_token)])
def list_management_audit_logs(db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                               x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
                               limit: int = Query(100, ge=1, le=500)):
    _, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    audit_query = db.query(models.ManagementAuditLog)
    if "SYSTEM_ADMIN" not in roles:
        bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
        if not bank:
            raise HTTPException(404, "Bank scope not found")
        audit_query = audit_query.filter(models.ManagementAuditLog.bank_id == bank.id)
    rows = audit_query.order_by(models.ManagementAuditLog.created_at.desc()).limit(limit).all()
    return [{"id": str(r.id), "actor_staff_id": str(r.actor_staff_id) if r.actor_staff_id else None,
        "actor_external_id": r.actor_external_id, "action": r.action, "target_type": r.target_type,
        "target_id": r.target_id, "before_data": r.before_data, "after_data": r.after_data,
        "created_at": r.created_at} for r in rows]

@app.post("/api/v1/admin/banks", status_code=201, tags=["bank-management"], dependencies=[Depends(require_internal_token)])
def create_bank_organization(payload: BankOrganizationIn, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                            x_actor_roles: str | None = Header(default=None)):
    roles = {r.strip().upper() for r in (x_actor_roles or "").replace(";", ",").split(",") if r.strip()}
    if not x_actor_id:
        raise HTTPException(401, "Missing trusted actor")
    if "SYSTEM_ADMIN" not in roles:
        raise HTTPException(403, "System administrator role required")
    code = payload.bank_code.strip()
    name = payload.bank_name.strip()
    if not code or not name:
        raise HTTPException(422, "bank_code and bank_name are required")
    if db.query(models.BankOrganization).filter_by(bank_code=code).first():
        raise HTTPException(409, "bank_code already exists")
    bank = models.BankOrganization(bank_code=code, bank_name=name, status=payload.status)
    db.add(bank); db.flush()
    db.add(models.ManagementAuditLog(bank_id=bank.id, actor_external_id=x_actor_id, action="BANK_CREATED", target_type="bank", target_id=str(bank.id),
        after_data={"bank_code": code, "bank_name": name}))
    db.commit()
    return {"id": str(bank.id), "bank_code": bank.bank_code, "bank_name": bank.bank_name, "status": bank.status}


@app.post("/api/v1/admin/banks/{bank_id}/branches", status_code=201, tags=["bank-management"], dependencies=[Depends(require_internal_token)])
def create_bank_branch(bank_id: UUID, payload: BankBranchIn, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                       x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    actor, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    bank = db.query(models.BankOrganization).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(404, "Bank not found")
    if "SYSTEM_ADMIN" not in roles and bank.bank_code != bank_code:
        raise HTTPException(403, "Bank administrator cannot manage another bank")
    branch_code = payload.branch_code.strip()
    branch_name = payload.branch_name.strip()
    if not branch_code or not branch_name:
        raise HTTPException(422, "branch_code and branch_name are required")
    branch = models.BankBranch(bank_id=bank.id, branch_code=branch_code, branch_name=branch_name,
        address=payload.address, status=payload.status)
    db.add(branch); db.flush()
    db.add(models.ManagementAuditLog(bank_id=bank.id, actor_external_id=actor, action="BANK_BRANCH_CREATED", target_type="bank_branch",
        target_id=str(branch.id), after_data={"bank_id": str(bank.id), "branch_code": branch_code}))
    db.commit()
    return {"id": str(branch.id), "bank_id": str(bank.id), "branch_code": branch.branch_code,
        "branch_name": branch.branch_name, "status": branch.status}

# ---- DATA-AI operational visibility: source inventory, quality and lineage ----
@app.get("/api/v1/cases/{case_id}/quality-issues", tags=["data-quality"],
         dependencies=[Depends(require_internal_token)])
def case_quality_issues(case_id: UUID, limit: int = Query(100, ge=1, le=500),
                        db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                        x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    rows = (db.query(models.DataQualityIssue).filter_by(case_id=case_id)
            .order_by(models.DataQualityIssue.created_at.desc()).limit(limit).all())
    return [{"id": str(x.id), "document_id": str(x.document_id) if x.document_id else None,
        "issue_code": x.issue_code, "severity": x.severity, "description": x.description,
        "source_anchor": x.source_anchor, "issue_status": x.issue_status,
        "created_at": x.created_at.isoformat()} for x in rows]


@app.get("/api/v1/cases/{case_id}/pipeline-runs", tags=["data-lineage"],
         dependencies=[Depends(require_internal_token)])
def case_pipeline_runs(case_id: UUID, limit: int = Query(100, ge=1, le=500),
                       db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                       x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    rows = (db.query(models.PipelineRun).filter_by(case_id=case_id)
            .order_by(models.PipelineRun.started_at.desc()).limit(limit).all())
    return [{"id": str(x.id), "document_id": str(x.document_id) if x.document_id else None,
        "pipeline_version": x.pipeline_version, "status": x.status,
        "started_at": x.started_at.isoformat() if x.started_at else None,
        "completed_at": x.completed_at.isoformat() if x.completed_at else None,
        "metrics": x.metrics} for x in rows]


@app.get("/api/v1/admin/source-inventory", tags=["source-management"],
         dependencies=[Depends(require_internal_token)])
def list_source_inventory(db: Session = Depends(get_db)):
    rows = db.query(models.SourceInventory).order_by(models.SourceInventory.source_code).all()
    return [{"id": str(x.id), "source_code": x.source_code, "source_name": x.source_name,
        "source_type": x.source_type, "schema_version": x.schema_version,
        "approval_status": x.approval_status, "config": x.config} for x in rows]


@app.get("/api/v1/admin/field-mappings", tags=["source-management"],
         dependencies=[Depends(require_internal_token)])
def list_field_mappings(source_code: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.FieldMappingRegistry)
    if source_code:
        query = query.filter(models.FieldMappingRegistry.source_code == source_code)
    rows = query.order_by(models.FieldMappingRegistry.source_code,
                          models.FieldMappingRegistry.source_field).all()
    return [{"id": str(x.id), "source_code": x.source_code,
        "schema_version": x.schema_version, "source_field": x.source_field,
        "target_field": x.target_field, "transform_code": x.transform_code,
        "is_required": x.is_required, "approval_status": x.approval_status} for x in rows]


# ---- V9.3.2 evidence provenance, statement reconciliation and Maker review ----
from app.evidence_reconciliation import (
    reconcile_pdf_csv_candidates, verify_manifest_chain,
    manifest_matches_document_metadata, summarize_document_integrity,
)
from app.service import sha256_file


def _case_evidence_context(case_id: UUID, db: Session, x_actor_id, x_actor_roles, x_bank_id):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    return case, actor, roles


def _latest_review_map(db: Session, target_type: str, target_ids: list[UUID]):
    if not target_ids:
        return {}
    rows = (db.query(models.EvidenceReviewDecision)
            .filter(models.EvidenceReviewDecision.target_type == target_type,
                    models.EvidenceReviewDecision.target_id.in_(target_ids))
            .order_by(models.EvidenceReviewDecision.created_at.asc(), models.EvidenceReviewDecision.id.asc()).all())
    result = {}
    for row in rows:
        result[str(row.target_id)] = row
    return result


def _review_out(row):
    if row is None:
        return None
    return {"id": str(row.id), "decision_code": row.decision_code, "reason": row.reason,
            "reviewed_by": row.reviewed_by, "reviewer_role": row.reviewer_role,
            "evidence_refs": row.evidence_refs, "created_at": row.created_at}


@app.get("/api/v1/cases/{case_id}/evidence/provenance", tags=["evidence-provenance"],
         dependencies=[Depends(require_internal_token)])
def case_evidence_provenance(case_id: UUID, db: Session = Depends(get_db),
                             x_actor_id: str | None = Header(default=None),
                             x_actor_roles: str | None = Header(default=None),
                             x_bank_id: str | None = Header(default=None)):
    """Return source hashes and field/transaction anchors for authorized case reviewers."""
    case, _, _ = _case_evidence_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    entries = (db.query(models.EvidenceManifestEntry).filter_by(case_id=case_id)
               .order_by(models.EvidenceManifestEntry.sequence_no.asc()).all())
    chain = verify_manifest_chain(entries)
    docs = (db.query(models.Document).filter_by(case_id=case_id)
            .order_by(models.Document.created_at.asc()).all())
    manifest_by_document = {str(x.document_id): x for x in entries}
    document_rows = []
    for doc in docs:
        entry = manifest_by_document.get(str(doc.id))
        stored_path = Path(doc.stored_path)
        if not stored_path.is_file():
            storage_integrity = "MISSING"
        else:
            storage_integrity = "MATCH" if sha256_file(stored_path).lower() == doc.sha256.lower() else "MISMATCH"
        manifest_metadata_integrity = (
            "MATCH" if manifest_matches_document_metadata(entry, doc) else
            "MISMATCH" if entry else "UNMANIFESTED"
        )
        document_rows.append({
            "document_id": str(doc.id), "filename": doc.original_filename,
            "sha256": doc.sha256, "mime_type": doc.mime_type, "file_size": doc.file_size,
            "document_type": doc.document_type, "evidence_status": doc.evidence_status,
            "processing_status": doc.processing_status,
            "manifested": entry is not None,
            "manifest_sequence_no": entry.sequence_no if entry else None,
            "manifest_entry_hash": entry.entry_hash if entry else None,
            "manifest_metadata_integrity": manifest_metadata_integrity,
            "stored_bytes_integrity": storage_integrity,
        })
    fields = (db.query(models.ExtractedField)
              .join(models.Document, models.Document.id == models.ExtractedField.document_id)
              .filter(models.Document.case_id == case_id)
              .order_by(models.ExtractedField.created_at.asc()).all())
    field_rows = [{
        "field_id": str(field.id), "document_id": str(field.document_id),
        "field_name": field.field_name, "raw_value": field.raw_value,
        "normalized_value": field.normalized_value, "validation_status": field.validation_status,
        "extraction_decision": field.extraction_decision, "abstain_reason": field.abstain_reason,
        "confidence": str(field.confidence), "confidence_basis": field.confidence_basis,
        "extraction_method": field.extraction_method, "extraction_rule_version": field.extraction_rule_version,
        "page_number": field.page_number, "bbox": field.bbox,
        "coordinate_space": field.coordinate_space, "source_line": field.source_line,
        "review_status": field.review_status,
    } for field in fields]
    transaction_rows_all = (db.query(models.Transaction).filter_by(case_id=case_id)
                            .order_by(models.Transaction.transaction_date.asc(), models.Transaction.source_row.asc()).all())
    case_document_ids = {str(doc.id) for doc in docs}
    transaction_rows = [{
        "transaction_id": str(tx.id),
        "document_id": str(tx.document_id) if tx.document_id and str(tx.document_id) in case_document_ids else None,
        "source_document_integrity": (
            "MATCH" if tx.document_id and str(tx.document_id) in case_document_ids else
            "MISSING_OR_CROSS_CASE" if tx.document_id else "UNLINKED"
        ),
        "source_row": tx.source_row, "transaction_date": tx.transaction_date,
        "description": tx.description, "amount_vnd": str(tx.amount_vnd) if tx.amount_vnd is not None else None,
        "direction": tx.direction, "category": tx.category, "review_status": tx.review_status,
    } for tx in transaction_rows_all]
    return {
        "case_id": str(case_id),
        "manifest": {**chain, **summarize_document_integrity(document_rows),
            "legacy_unmanifested_document_count": sum(1 for d in document_rows if not d["manifested"]),
        },
        "manifest_entries": [{
            "id": str(entry.id), "sequence_no": entry.sequence_no,
            "document_id": str(entry.document_id), "original_filename": entry.original_filename,
            "sha256": entry.sha256, "mime_type": entry.mime_type, "file_size": entry.file_size,
            "previous_entry_hash": entry.previous_entry_hash, "entry_hash": entry.entry_hash,
            "hash_version": entry.hash_version, "received_by": entry.received_by,
            "received_at": entry.received_at,
        } for entry in entries],
        "documents": document_rows,
        "extracted_fields": field_rows,
        "transactions": transaction_rows,
        "interpretation": "The hash chain protects receipt metadata and per-file hashes. Stored-byte integrity is verified by re-hashing each object. Neither check proves document authenticity, account ownership, Maker approval or income eligibility.",
    }


@app.post("/api/v1/cases/{case_id}/evidence/reconciliations", tags=["evidence-reconciliation"],
          status_code=201, dependencies=[Depends(require_internal_token)])
def create_evidence_reconciliation(case_id: UUID, payload: EvidenceReconciliationIn,
                                   db: Session = Depends(get_db),
                                   x_actor_id: str | None = Header(default=None),
                                   x_actor_roles: str | None = Header(default=None),
                                   x_bank_id: str | None = Header(default=None)):
    case, actor, _ = _case_evidence_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    pdf_doc = db.query(models.Document).filter_by(id=payload.pdf_document_id, case_id=case_id).first()
    csv_doc = db.query(models.Document).filter_by(id=payload.csv_document_id, case_id=case_id).first()
    if not pdf_doc or not csv_doc:
        raise HTTPException(404, "Selected evidence document not found in case")
    if pdf_doc.id == csv_doc.id:
        raise HTTPException(422, "PDF and CSV must be distinct evidence documents")
    if Path(pdf_doc.original_filename).suffix.lower() != ".pdf" or Path(csv_doc.original_filename).suffix.lower() != ".csv":
        raise HTTPException(422, "Reconciliation requires one PDF statement and one CSV statement")
    if pdf_doc.processing_status != "COMPLETED" or pdf_doc.document_type != "BANK_STATEMENT":
        raise HTTPException(409, "PDF must be processed and classified as BANK_STATEMENT before reconciliation")
    if csv_doc.processing_status != "COMPLETED" or csv_doc.document_type != "BANK_STATEMENT":
        raise HTTPException(409, "CSV must be processed as BANK_STATEMENT before reconciliation")

    # Re-hash the stored bytes before using them; DB metadata alone is not a file integrity check.
    for doc in (pdf_doc, csv_doc):
        stored_path = Path(doc.stored_path)
        if not stored_path.is_file():
            raise HTTPException(409, f"Evidence storage object is missing: {doc.id}")
        if sha256_file(stored_path).lower() != doc.sha256.lower():
            raise HTTPException(409, f"Evidence storage hash mismatch: {doc.id}")

    manifests = (db.query(models.EvidenceManifestEntry).filter_by(case_id=case_id)
                 .order_by(models.EvidenceManifestEntry.sequence_no.asc()).all())
    chain = verify_manifest_chain(manifests)
    if not chain["valid"]:
        raise HTTPException(409, "Evidence manifest hash chain is invalid; reconciliation is blocked")
    manifest_by_document = {str(row.document_id): row for row in manifests}
    for selected in (pdf_doc, csv_doc):
        entry = manifest_by_document.get(str(selected.id))
        if entry and not manifest_matches_document_metadata(entry, selected):
            raise HTTPException(409, f"Evidence manifest metadata mismatch: {selected.id}")
    manifested_ids = set(manifest_by_document)

    pdf_fields = (db.query(models.ExtractedField).filter_by(document_id=pdf_doc.id)
                  .order_by(models.ExtractedField.created_at.asc()).all())
    csv_transactions = (db.query(models.Transaction).filter_by(case_id=case_id, document_id=csv_doc.id)
                        .order_by(models.Transaction.source_row.asc()).all())
    result = reconcile_pdf_csv_candidates(
        pdf_fields=pdf_fields, csv_transactions=csv_transactions,
        tolerance_vnd=payload.tolerance_vnd,
    )
    if str(pdf_doc.id) not in manifested_ids or str(csv_doc.id) not in manifested_ids:
        result["status"] = "INCOMPLETE"
        result.setdefault("errors", []).append("SOURCE_MANIFEST_MISSING_FOR_SELECTED_DOCUMENT")
    result["pdf_document_id"] = str(pdf_doc.id)
    result["csv_document_id"] = str(csv_doc.id)
    result["pdf_sha256"] = pdf_doc.sha256
    result["csv_sha256"] = csv_doc.sha256
    obj = models.EvidenceReconciliationRun(
        case_id=case_id, pdf_document_id=pdf_doc.id, csv_document_id=csv_doc.id,
        pdf_sha256=pdf_doc.sha256, csv_sha256=csv_doc.sha256,
        reconciliation_version=result.get("reconciliation_version", "V9.3.2.1"),
        result_status=result["status"], summary=result, created_by=actor,
    )
    db.add(obj)
    db.flush()
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="EVIDENCE_RECONCILIATION_CREATED",
        entity_type="evidence_reconciliation", entity_id=str(obj.id), details={
            "pdf_document_id": str(pdf_doc.id), "csv_document_id": str(csv_doc.id),
            "result_status": result["status"], "reconciliation_version": result.get("reconciliation_version"),
        }))
    db.commit()
    db.refresh(obj)
    return {"id": str(obj.id), "case_id": str(case_id), "result_status": obj.result_status,
            "summary": obj.summary, "created_by": obj.created_by, "created_at": obj.created_at,
            "maker_review_required": True, "camunda_task_completion_required": True}


@app.get("/api/v1/cases/{case_id}/evidence/reconciliations", tags=["evidence-reconciliation"],
         dependencies=[Depends(require_internal_token)])
def list_evidence_reconciliations(case_id: UUID, db: Session = Depends(get_db),
                                  x_actor_id: str | None = Header(default=None),
                                  x_actor_roles: str | None = Header(default=None),
                                  x_bank_id: str | None = Header(default=None)):
    _case_evidence_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    runs = (db.query(models.EvidenceReconciliationRun).filter_by(case_id=case_id)
            .order_by(models.EvidenceReconciliationRun.created_at.desc()).limit(100).all())
    reviews = _latest_review_map(db, "RECONCILIATION_RUN", [x.id for x in runs])
    return [{"id": str(x.id), "pdf_document_id": str(x.pdf_document_id),
             "csv_document_id": str(x.csv_document_id), "result_status": x.result_status,
             "summary": x.summary, "created_by": x.created_by, "created_at": x.created_at,
             "latest_maker_review": _review_out(reviews.get(str(x.id)))} for x in runs]


@app.get("/api/v1/cases/{case_id}/evidence/duplicate-candidates", tags=["evidence-reconciliation"],
         dependencies=[Depends(require_internal_token)])
def list_transaction_duplicate_candidates(case_id: UUID, db: Session = Depends(get_db),
                                           x_actor_id: str | None = Header(default=None),
                                           x_actor_roles: str | None = Header(default=None),
                                           x_bank_id: str | None = Header(default=None)):
    _case_evidence_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    candidates = (db.query(models.TransactionDuplicateCandidate).filter_by(case_id=case_id)
                  .order_by(models.TransactionDuplicateCandidate.created_at.desc()).limit(500).all())
    reviews = _latest_review_map(db, "TRANSACTION_DUPLICATE", [x.id for x in candidates])
    output = []
    case_document_ids = {str(row.id) for row in db.query(models.Document).filter_by(case_id=case_id).all()}
    transaction_ids = {transaction_id for candidate in candidates
                       for transaction_id in (candidate.left_transaction_id, candidate.right_transaction_id)}
    transaction_map = {row.id: row for row in db.query(models.Transaction).filter(
        models.Transaction.case_id == case_id, models.Transaction.id.in_(transaction_ids)).all()} if transaction_ids else {}
    for candidate in candidates:
        latest_review = reviews.get(str(candidate.id))
        left = transaction_map.get(candidate.left_transaction_id)
        right = transaction_map.get(candidate.right_transaction_id)
        def transaction_source_summary(tx):
            if tx is None:
                return None
            source_doc_in_case = bool(tx.document_id and str(tx.document_id) in case_document_ids)
            return {"id": str(tx.id), "document_id": str(tx.document_id) if source_doc_in_case else None,
                "source_document_integrity": "MATCH" if source_doc_in_case else "MISSING_OR_CROSS_CASE" if tx.document_id else "UNLINKED",
                "source_row": tx.source_row, "date": tx.transaction_date, "amount_vnd": str(tx.amount_vnd),
                "direction": tx.direction, "description": tx.description}
        review_status = (
            "PENDING_REVIEW" if latest_review is None else
            "NEEDS_MORE_EVIDENCE" if latest_review.decision_code == "NEEDS_MORE_EVIDENCE" else
            "REVIEWED"
        )
        output.append({"id": str(candidate.id), "fingerprint_sha256": candidate.fingerprint_sha256,
            "match_reasons": candidate.match_reasons, "review_status": review_status,
            "left_transaction": transaction_source_summary(left),
            "right_transaction": transaction_source_summary(right),
            "latest_maker_review": _review_out(latest_review)})
    return output


def _record_evidence_review(*, case_id: UUID, target_type: str, target_id: UUID,
                            payload: EvidenceReviewIn, db: Session, actor: str, roles: set[str]):
    require_governance_role(actor, roles, "MAKER")
    allowed_by_type = {
        "RECONCILIATION_RUN": {"CONFIRMED_MATCH", "CONFIRMED_VARIANCE", "REJECTED", "NEEDS_MORE_EVIDENCE"},
        "TRANSACTION_DUPLICATE": {"CONFIRMED_DUPLICATE", "NOT_DUPLICATE", "NEEDS_MORE_EVIDENCE"},
    }
    if payload.decision_code not in allowed_by_type[target_type]:
        raise HTTPException(422, f"Unsupported decision_code for {target_type}")
    refs = set(payload.evidence_refs)
    if refs:
        found = {row.id for row in db.query(models.Document).filter(
            models.Document.case_id == case_id, models.Document.id.in_(refs)).all()}
        if refs != found:
            raise HTTPException(422, "evidence_refs must point to documents in the same case")
    if target_type == "RECONCILIATION_RUN" and payload.decision_code in {"CONFIRMED_MATCH", "CONFIRMED_VARIANCE"}:
        target = db.query(models.EvidenceReconciliationRun).filter_by(id=target_id, case_id=case_id).first()
        required_refs = {target.pdf_document_id, target.csv_document_id}
        if not required_refs.issubset(refs):
            raise HTTPException(422, "Confirmed reconciliation review must reference both source documents")
    if target_type == "TRANSACTION_DUPLICATE" and payload.decision_code in {"CONFIRMED_DUPLICATE", "NOT_DUPLICATE"}:
        target = db.query(models.TransactionDuplicateCandidate).filter_by(id=target_id, case_id=case_id).first()
        transactions = db.query(models.Transaction).filter(
            models.Transaction.case_id == case_id,
            models.Transaction.id.in_([target.left_transaction_id, target.right_transaction_id])).all()
        if len(transactions) != 2 or any(tx.document_id is None for tx in transactions):
            raise HTTPException(409, "Cannot resolve duplicate candidate because one or both transactions lack a source document")
        required_refs = {tx.document_id for tx in transactions}
        if not required_refs.issubset(refs):
            raise HTTPException(422, "Resolved duplicate review must reference the source documents for both transactions")
    role = "MAKER"
    review = models.EvidenceReviewDecision(
        case_id=case_id, target_type=target_type, target_id=target_id,
        reconciliation_run_id=target_id if target_type == "RECONCILIATION_RUN" else None,
        duplicate_candidate_id=target_id if target_type == "TRANSACTION_DUPLICATE" else None,
        decision_code=payload.decision_code, reason=payload.reason.strip(),
        evidence_refs=[str(x) for x in payload.evidence_refs], reviewed_by=actor[:160], reviewer_role=role,
    )
    db.add(review)
    db.flush()
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="EVIDENCE_MAKER_REVIEW_RECORDED",
        entity_type=target_type.lower(), entity_id=str(target_id), details={
            "review_id": str(review.id), "decision_code": payload.decision_code,
            "reviewer_role": role, "evidence_refs": [str(x) for x in payload.evidence_refs],
        }))
    db.commit()
    db.refresh(review)
    return {"id": str(review.id), "target_type": target_type, "target_id": str(target_id),
            "decision_code": review.decision_code, "reviewed_by": review.reviewed_by,
            "reviewer_role": review.reviewer_role, "reason": review.reason,
            "evidence_refs": review.evidence_refs, "created_at": review.created_at,
            "camunda_task_completion_required": True,
            "note": "Đây là bản ghi review bất biến; Backend/Camunda vẫn quản lý task và chuyển trạng thái workflow."}


@app.post("/api/v1/cases/{case_id}/evidence/reconciliations/{run_id}/review", tags=["evidence-reconciliation"],
          status_code=201, dependencies=[Depends(require_internal_token)])
def review_evidence_reconciliation(case_id: UUID, run_id: UUID, payload: EvidenceReviewIn,
                                   db: Session = Depends(get_db),
                                   x_actor_id: str | None = Header(default=None),
                                   x_actor_roles: str | None = Header(default=None),
                                   x_bank_id: str | None = Header(default=None)):
    _, actor, roles = _case_evidence_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    run = db.query(models.EvidenceReconciliationRun).filter_by(id=run_id, case_id=case_id).first()
    if not run:
        raise HTTPException(404, "Reconciliation run not found")
    if payload.decision_code in {"CONFIRMED_MATCH", "CONFIRMED_VARIANCE"} and run.result_status == "INCOMPLETE":
        raise HTTPException(409, "Cannot confirm an incomplete reconciliation; repair missing evidence/manifest first")
    if payload.decision_code == "CONFIRMED_MATCH" and run.summary.get("arithmetic_candidate_status") != "BALANCE_MATCH_CANDIDATE":
        raise HTTPException(409, "Cannot confirm a match when the arithmetic candidate is incomplete or in variance")
    if payload.decision_code == "CONFIRMED_VARIANCE" and run.summary.get("arithmetic_candidate_status") != "BALANCE_VARIANCE_CANDIDATE":
        raise HTTPException(409, "Cannot confirm a variance when no arithmetic variance candidate exists")
    return _record_evidence_review(case_id=case_id, target_type="RECONCILIATION_RUN",
        target_id=run_id, payload=payload, db=db, actor=actor, roles=roles)


@app.post("/api/v1/cases/{case_id}/evidence/duplicate-candidates/{candidate_id}/review", tags=["evidence-reconciliation"],
          status_code=201, dependencies=[Depends(require_internal_token)])
def review_transaction_duplicate(case_id: UUID, candidate_id: UUID, payload: EvidenceReviewIn,
                                 db: Session = Depends(get_db),
                                 x_actor_id: str | None = Header(default=None),
                                 x_actor_roles: str | None = Header(default=None),
                                 x_bank_id: str | None = Header(default=None)):
    _, actor, roles = _case_evidence_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    candidate = db.query(models.TransactionDuplicateCandidate).filter_by(id=candidate_id, case_id=case_id).first()
    if not candidate:
        raise HTTPException(404, "Duplicate candidate not found")
    return _record_evidence_review(case_id=case_id, target_type="TRANSACTION_DUPLICATE",
        target_id=candidate_id, payload=payload, db=db, actor=actor, roles=roles)



# ---- V9.4.1 immutable analysis-input versions and Maker–Checker governance ----
def _case_governance_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, expected_role=None):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    if expected_role:
        require_governance_role(actor, roles, expected_role)
    elif (not roles.intersection({"MAKER", "CHECKER"})
          or roles.intersection({"DATA_AI_SERVICE", "BANK_ADMIN", "SYSTEM_ADMIN", "DATA_AI_STAFF"})
          or {"MAKER", "CHECKER"}.issubset(roles)):
        raise HTTPException(403, "Governance version access requires a separated Maker or Checker identity")
    return case, actor, roles


def _governance_event_out(event):
    return {
        "id": str(event.id), "case_id": str(event.case_id), "version_id": str(event.version_id),
        "event_type": event.event_type, "actor_id": event.actor_id,
        "actor_role": event.actor_role, "reason": event.reason,
        "details": event.details, "created_at": event.created_at.isoformat(),
    }


def _governance_version_out(db, version, *, include_snapshot=False):
    state, events = get_version_state(db, version.id)
    output = {
        "id": str(version.id), "case_id": str(version.case_id), "version_no": version.version_no,
        "based_on_version_id": str(version.based_on_version_id) if version.based_on_version_id else None,
        "snapshot_schema_version": version.snapshot_schema_version,
        "snapshot_sha256": version.snapshot_sha256, "created_by": version.created_by,
        "created_by_role": version.created_by_role, "created_at": version.created_at.isoformat(),
        "state": state, "readiness": version.readiness,
        "events": [_governance_event_out(event) for event in events],
    }
    if include_snapshot:
        if not verify_version_integrity(version):
            raise HTTPException(409, "Stored governance snapshot failed its SHA-256/readiness integrity check")
        output["snapshot_hash_verified"] = True
        output["snapshot"] = version.snapshot_data
    return output


@app.post("/api/v1/cases/{case_id}/governance/freeze", status_code=201,
          tags=["case-governance"], dependencies=[Depends(require_internal_token)])
def freeze_case_analysis_version(
    case_id: UUID, request: Request, payload: GovernanceFreezeIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, _ = _case_governance_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, expected_role="MAKER")
    # Serialize version creation against all case-owned data mutations (V14 DB trigger).
    case = (db.query(models.Case).filter_by(id=case_id)
            .populate_existing().with_for_update().first())
    if not case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_bank_scope(case, x_actor_id, x_actor_roles, x_bank_id)
    require_governance_role(actor, roles, "MAKER")
    latest = get_latest_case_version(db, case_id)
    previous_state = "DRAFT"
    open_reopen = None
    if latest:
        previous_state, _ = get_version_state(db, latest.id)
        if previous_state == "FROZEN":
            raise HTTPException(409, "The latest version is already frozen and awaiting Checker review")
        if previous_state == "CHECKER_CONFIRMED":
            open_reopen = (db.query(models.CaseWorkflowReopen)
                           .filter_by(case_id=case_id, based_on_version_id=latest.id, status="OPEN")
                           .with_for_update().first())
            if not open_reopen:
                raise HTTPException(409, "A Checker-confirmed version requires a recorded workflow reopen before creating a new version")
        elif previous_state != "RETURNED_TO_MAKER":
            raise HTTPException(409, "A new version requires an explicit Checker return or a governed post-completion reopen")

    snapshot, readiness = build_case_snapshot(db, case)
    digest = calculate_snapshot_sha256(snapshot)
    version = models.CaseAnalysisVersion(
        id=uuid4(), case_id=case_id, version_no=(latest.version_no + 1 if latest else 1),
        based_on_version_id=(latest.id if latest else None), snapshot_schema_version=snapshot["snapshot_schema_version"],
        snapshot_sha256=digest, snapshot_data=snapshot, readiness=readiness,
        created_by=actor, created_by_role="MAKER",
    )
    try:
        db.add(version)
        db.flush()
        if latest:
            db.add(models.CaseGovernanceEvent(
                case_id=case_id, version_id=latest.id, event_type="VERSION_SUPERSEDED",
                actor_id=actor, actor_role="MAKER",
                reason=f"Superseded by version {version.version_no}: {payload.reason}",
                details={"superseded_by_version_id": str(version.id), "superseded_by_version_no": version.version_no},
            ))
        db.add(models.CaseGovernanceEvent(
            case_id=case_id, version_id=version.id, event_type="FROZEN", actor_id=actor,
            actor_role="MAKER", reason=payload.reason,
            details={"snapshot_sha256": digest, "readiness_status": readiness["status"],
                     "review_scope": "DATA_AI_EVIDENCE_INPUTS_ONLY"},
        ))
        db.add(models.AuditEvent(
            case_id=case_id, actor=actor[:100], action="CASE_ANALYSIS_VERSION_FROZEN",
            entity_type="case_analysis_version", entity_id=str(version.id),
            details={"version_no": version.version_no, "snapshot_sha256": digest,
                     "readiness_status": readiness["status"]},
        ))
        db.flush()
        append_case_audit_entry(
            db, case=case, actor_id=actor, actor_role="MAKER", action_code="CASE_VERSION_FROZEN",
            entity_type="case_analysis_version", entity_id=str(version.id), version_id=version.id,
            request_id=getattr(request.state, "request_id", None), reason=payload.reason,
            after_sha256=digest,
            details={"version_no": version.version_no, "readiness_status": readiness["status"],
                     "review_scope": "DATA_AI_EVIDENCE_INPUTS_ONLY"},
        )
        if open_reopen:
            open_reopen.status = "CONSUMED"
            open_reopen.new_version_id = version.id
            open_reopen.consumed_at = datetime.now(timezone.utc)
        _enqueue_case_workflow_event(db, case, "ANALYSIS_VERSION_FROZEN", {
            "reason_code": "MAKER_SNAPSHOT_FROZEN", "external_gate_reference": str(version.id)},
            idempotency_key=f"ANALYSIS_VERSION_FROZEN:{version.id}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent or invalid governance version transition") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(version)
    return _governance_version_out(db, version)


@app.post("/api/v1/cases/{case_id}/governance/versions/{version_id}/checker-review", status_code=201,
          tags=["case-governance"], dependencies=[Depends(require_internal_token)])
def checker_review_case_analysis_version(
    case_id: UUID, version_id: UUID, request: Request, payload: GovernanceCheckerReviewIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, _ = _case_governance_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, expected_role="CHECKER")
    locked_case = (db.query(models.Case).filter_by(id=case_id)
                   .populate_existing().with_for_update().first())
    if not locked_case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_bank_scope(locked_case, x_actor_id, x_actor_roles, x_bank_id)
    require_governance_role(actor, roles, "CHECKER")
    version = db.query(models.CaseAnalysisVersion).filter_by(id=version_id, case_id=case_id).first()
    if not version:
        raise HTTPException(404, "Analysis version not found")
    state, _ = get_version_state(db, version.id)
    if state != "FROZEN":
        raise HTTPException(409, "Only a frozen version awaiting Checker review can be reviewed")
    if not verify_version_integrity(version):
        raise HTTPException(409, "Stored governance snapshot failed its SHA-256/readiness integrity check")
    if actor == version.created_by:
        raise HTTPException(403, "Maker cannot Checker-review their own version")
    if payload.decision == "CONFIRM":
        if not version.readiness.get("review_ready", False):
            raise HTTPException(409, {
                "message": "Version has unresolved technical readiness blockers",
                "readiness": version.readiness,
            })
        event_type = "CHECKER_CONFIRMED"
    else:
        event_type = "RETURNED_TO_MAKER"
    event = models.CaseGovernanceEvent(
        case_id=case_id, version_id=version_id, event_type=event_type, actor_id=actor,
        actor_role="CHECKER", reason=payload.reason,
        details={"decision": payload.decision, "snapshot_sha256": version.snapshot_sha256,
                 "review_scope": "DATA_AI_EVIDENCE_INPUTS_ONLY"},
    )
    try:
        db.add(event)
        db.add(models.AuditEvent(
            case_id=case_id, actor=actor[:100], action=f"CASE_ANALYSIS_{event_type}",
            entity_type="case_analysis_version", entity_id=str(version.id),
            details={"version_no": version.version_no, "snapshot_sha256": version.snapshot_sha256,
                     "decision": payload.decision},
        ))
        db.flush()
        append_case_audit_entry(
            db, case=locked_case, actor_id=actor, actor_role="CHECKER",
            action_code=f"CASE_VERSION_{event_type}", entity_type="case_analysis_version",
            entity_id=str(version.id), version_id=version.id,
            request_id=getattr(request.state, "request_id", None), reason=payload.reason,
            before_sha256=version.snapshot_sha256, after_sha256=version.snapshot_sha256,
            details={"version_no": version.version_no, "decision": payload.decision,
                     "review_scope": "DATA_AI_EVIDENCE_INPUTS_ONLY"},
        )
        _enqueue_case_workflow_event(db, locked_case, "CHECKER_CONFIRMED" if event_type == "CHECKER_CONFIRMED" else "CHECKER_RETURNED_TO_MAKER", {
            "reason_code": payload.decision, "external_gate_reference": str(version.id)},
            idempotency_key=f"CHECKER_REVIEW:{version.id}:{event_type}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Checker decision already exists or governance transition is invalid") from exc
    db.refresh(event)
    return {"version": _governance_version_out(db, version), "decision_event": _governance_event_out(event),
            "credit_decision": False, "camunda_task_completed": False}


@app.get("/api/v1/cases/{case_id}/governance/versions", tags=["case-governance"],
         dependencies=[Depends(require_internal_token)])
def list_case_analysis_versions(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _case_governance_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    versions = (db.query(models.CaseAnalysisVersion).filter_by(case_id=case.id)
                .order_by(models.CaseAnalysisVersion.version_no.desc()).all())
    return [_governance_version_out(db, item) for item in versions]


@app.get("/api/v1/cases/{case_id}/governance/versions/{version_id}", tags=["case-governance"],
         dependencies=[Depends(require_internal_token)])
def get_case_analysis_version(
    case_id: UUID, version_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _case_governance_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    version = db.query(models.CaseAnalysisVersion).filter_by(id=version_id, case_id=case.id).first()
    if not version:
        raise HTTPException(404, "Analysis version not found")
    return _governance_version_out(db, version, include_snapshot=True)


# ---- V9.4.2 hash-chained audit and Named Authority override governance ----
def _case_audit_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    actor, roles, bank_id = trusted_actor_context(
        x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    allowed = {"MAKER", "CHECKER", "NAMED_AUTHORITY", "BANK_POLICY_OWNER", "BANK_ADMIN", "SYSTEM_ADMIN"}
    if not roles.intersection(allowed) or roles.intersection({"DATA_AI_SERVICE", "DATA_AI_STAFF"}):
        raise HTTPException(403, "No authorized human audit/override access role")
    enforce_bank_scope(case.bank_id, bank_id, roles, not_found_message="Case not found")
    return case, actor, roles


def _case_override_reader_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id):
    """Limit proposal JSON access; broad audit administrators get hashes/events, not proposal payloads."""
    case, actor, roles = _case_audit_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    proposal_read_roles = {"MAKER", "CHECKER", "NAMED_AUTHORITY", "BANK_POLICY_OWNER"}
    if (not roles.intersection(proposal_read_roles)
            or {"MAKER", "CHECKER"}.issubset(roles)):
        raise HTTPException(403, "Role is not authorized to read override proposal details")
    return case, actor, roles


def _assert_case_named_authority_scope(case, x_actor_id, x_actor_roles, x_bank_id):
    """Revalidate the dedicated authority role and bank scope after acquiring the Case row lock."""
    actor, roles, bank_id = trusted_actor_context(
        x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    require_named_authority(actor, roles)
    enforce_bank_scope(case.bank_id, bank_id, roles, not_found_message="Case not found")
    return actor, roles


def _audit_entry_out(row):
    return {
        "id": str(row.id), "case_id": str(row.case_id), "bank_id": row.bank_id,
        "sequence_no": row.sequence_no, "actor_id": row.actor_id, "actor_role": row.actor_role,
        "action_code": row.action_code, "entity_type": row.entity_type, "entity_id": row.entity_id,
        "version_id": str(row.version_id) if row.version_id else None,
        "request_id": str(row.request_id) if row.request_id else None,
        "reason": row.reason, "before_sha256": row.before_sha256, "after_sha256": row.after_sha256,
        "details": row.details, "previous_entry_sha256": row.previous_entry_sha256,
        "entry_sha256": row.entry_sha256, "created_at": row.created_at.isoformat(),
    }


def _override_proposal_payload(payload_or_row, *, case_id=None, version_id=None, version_sha256=None, requested_by=None):
    if isinstance(payload_or_row, models.CaseOverrideRequest):
        row = payload_or_row
        return {
            "case_id": str(row.case_id), "version_id": str(row.version_id),
            "version_sha256": row.version_sha256, "request_kind": row.request_kind,
            "exception_code": row.exception_code, "policy_reference": row.policy_reference,
            "policy_version": row.policy_version, "requested_by": row.requested_by,
            "reason": row.reason, "requested_change": row.requested_change,
            "impact_summary": row.impact_summary, "evidence_refs": row.evidence_refs,
        }
    return {
        "case_id": str(case_id), "version_id": str(version_id),
        "version_sha256": version_sha256, "request_kind": payload_or_row.request_kind,
        "exception_code": payload_or_row.exception_code,
        "policy_reference": payload_or_row.policy_reference,
        "policy_version": payload_or_row.policy_version,
        "requested_by": requested_by, "reason": payload_or_row.reason,
        "requested_change": payload_or_row.requested_change,
        "impact_summary": payload_or_row.impact_summary,
        "evidence_refs": [str(item) for item in payload_or_row.evidence_refs],
    }


def _override_request_out(db, row, *, include_events=True):
    status, events = override_request_state(db, row)
    checker_actor = None
    version = db.query(models.CaseAnalysisVersion).filter_by(id=row.version_id, case_id=row.case_id).first()
    if version:
        checker_actor = (db.query(models.CaseGovernanceEvent.actor_id)
                         .filter_by(version_id=version.id, event_type="CHECKER_CONFIRMED").scalar())
    output = {
        "id": str(row.id), "case_id": str(row.case_id), "version_id": str(row.version_id),
        "bank_id": row.bank_id, "request_kind": row.request_kind,
        "exception_code": row.exception_code, "policy_reference": row.policy_reference,
        "policy_version": row.policy_version, "requested_by": row.requested_by,
        "reason": row.reason, "requested_change": row.requested_change,
        "impact_summary": row.impact_summary, "evidence_refs": row.evidence_refs,
        "version_sha256": row.version_sha256, "proposal_sha256": row.proposal_sha256,
        "created_at": row.created_at.isoformat(), "status": status,
        "checker_actor_id": checker_actor,
        "override_applied": False, "policy_engine_updated": False,
    }
    if include_events:
        output["events"] = [{
            "id": str(event.id), "event_type": event.event_type, "actor_id": event.actor_id,
            "actor_role": event.actor_role, "reason": event.reason,
            "authority_grant_ref": event.authority_grant_ref,
            "authority_scope_ref": event.authority_scope_ref,
            "valid_until": event.valid_until.isoformat() if event.valid_until else None,
            "proposal_sha256": event.proposal_sha256,
            "details": event.details, "created_at": event.created_at.isoformat(),
        } for event in events]
    return output


@app.post("/api/v1/cases/{case_id}/governance/versions/{version_id}/override-requests",
          status_code=201, tags=["override-governance"], dependencies=[Depends(require_internal_token)])
def create_case_override_request(
    case_id: UUID, version_id: UUID, request: Request, payload: OverrideRequestIn,
    db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _case_governance_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                                                   expected_role="MAKER")
    locked_case = (db.query(models.Case).filter_by(id=case_id)
                   .populate_existing().with_for_update().first())
    if not locked_case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_bank_scope(locked_case, x_actor_id, x_actor_roles, x_bank_id)
    require_governance_role(actor, roles, "MAKER")
    version = db.query(models.CaseAnalysisVersion).filter_by(id=version_id, case_id=case_id).first()
    if not version:
        raise HTTPException(404, "Analysis version not found")
    if actor != version.created_by:
        raise HTTPException(403, "Only the Maker who froze this version can submit its override proposal")
    from app.governance import get_version_state
    state, _ = get_version_state(db, version.id)
    if state not in {"FROZEN", "CHECKER_CONFIRMED"}:
        raise HTTPException(409, "Override proposal requires a current frozen or Checker-confirmed version")
    if not verify_version_integrity(version):
        raise HTTPException(409, "Stored governance snapshot failed its SHA-256/readiness integrity check")
    validate_case_evidence_refs(db, case_id, payload.evidence_refs)
    proposal_payload = _override_proposal_payload(
        payload, case_id=case_id, version_id=version_id, version_sha256=version.snapshot_sha256, requested_by=actor)
    proposal_hash = calculate_audit_entry_sha256(proposal_payload)
    record = models.CaseOverrideRequest(
        id=uuid4(), case_id=case_id, version_id=version_id, bank_id=locked_case.bank_id,
        request_kind=payload.request_kind, exception_code=payload.exception_code,
        policy_reference=payload.policy_reference, policy_version=payload.policy_version,
        requested_by=actor, reason=payload.reason, requested_change=payload.requested_change,
        impact_summary=payload.impact_summary,
        evidence_refs=[str(item) for item in payload.evidence_refs],
        version_sha256=version.snapshot_sha256, proposal_sha256=proposal_hash,
    )
    try:
        db.add(record)
        db.flush()
        db.add(models.CaseOverrideEvent(
            id=uuid4(), case_id=case_id, request_id=record.id, event_type="REQUESTED",
            actor_id=actor, actor_role="MAKER", reason=payload.reason,
            proposal_sha256=proposal_hash,
            details={"request_kind": payload.request_kind, "exception_code": payload.exception_code,
                     "version_no": version.version_no, "policy_reference": payload.policy_reference,
                     "policy_version": payload.policy_version},
        ))
        db.flush()
        append_case_audit_entry(
            db, case=locked_case, actor_id=actor, actor_role="MAKER",
            action_code="OVERRIDE_REQUESTED" if payload.request_kind == "OVERRIDE" else "POLICY_EXCEPTION_REQUESTED",
            entity_type="case_override_request", entity_id=str(record.id), version_id=version.id,
            request_id=getattr(request.state, "request_id", None), reason=payload.reason,
            before_sha256=version.snapshot_sha256, after_sha256=proposal_hash,
            details={"request_kind": payload.request_kind, "exception_code": payload.exception_code,
                     "policy_reference": payload.policy_reference, "policy_version": payload.policy_version,
                     "evidence_ref_count": len(payload.evidence_refs)},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Override proposal violates version, evidence or governance constraints") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return _override_request_out(db, record)


@app.post("/api/v1/cases/{case_id}/governance/override-requests/{request_id}/authority-review",
          status_code=201, tags=["override-governance"], dependencies=[Depends(require_internal_token)])
def review_case_override_request_by_authority(
    case_id: UUID, request_id: UUID, request: Request, payload: NamedAuthorityReviewIn,
    db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _case_audit_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    require_named_authority(actor, roles)
    locked_case = (db.query(models.Case).filter_by(id=case_id)
                   .populate_existing().with_for_update().first())
    if not locked_case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_named_authority_scope(locked_case, x_actor_id, x_actor_roles, x_bank_id)
    record = (db.query(models.CaseOverrideRequest)
              .filter_by(id=request_id, case_id=case_id, bank_id=locked_case.bank_id).first())
    if not record:
        raise HTTPException(404, "Override request not found")
    version = db.query(models.CaseAnalysisVersion).filter_by(id=record.version_id, case_id=case_id).first()
    if not version or not verify_version_integrity(version):
        raise HTTPException(409, "Linked version is missing or failed snapshot integrity verification")
    if not hmac_compare(record.version_sha256, version.snapshot_sha256):
        raise HTTPException(409, "Override proposal is bound to a different analysis version hash")
    expected_proposal_hash = calculate_audit_entry_sha256(_override_proposal_payload(record))
    if not hmac_compare(record.proposal_sha256, expected_proposal_hash):
        raise HTTPException(409, "Stored override proposal failed its SHA-256 integrity check")
    from app.governance import get_version_state
    state, version_events = get_version_state(db, version.id)
    if state != "CHECKER_CONFIRMED":
        raise HTTPException(409, "Named Authority review requires a Checker-confirmed technical version")
    checker_event = next((event for event in version_events if event.event_type == "CHECKER_CONFIRMED"), None)
    if actor in {record.requested_by, checker_event.actor_id if checker_event else None}:
        raise HTTPException(403, "Named Authority must be independent of the Maker and Checker")
    status, existing_events = override_request_state(db, record)
    if status != "PENDING_AUTHORITY":
        raise HTTPException(409, f"Override request is not awaiting authority decision (status={status})")
    event_type = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    decision_event = models.CaseOverrideEvent(
        id=uuid4(), case_id=case_id, request_id=record.id, event_type=event_type,
        actor_id=actor, actor_role="NAMED_AUTHORITY", reason=payload.reason,
        authority_grant_ref=payload.authority_grant_ref,
        authority_scope_ref=payload.authority_scope_ref,
        valid_until=payload.valid_until if event_type == "APPROVED" else None,
        proposal_sha256=record.proposal_sha256,
        details={"decision": payload.decision, "approved_proposal_sha256": record.proposal_sha256,
                 "application_effect": "NOT_APPLIED", "policy_engine_updated": False,
                 "authority_grant_validation": "ASSERTED_BY_BACKEND_NOT_REVALIDATED_BY_DATA_AI"},
    )
    try:
        db.add(decision_event)
        db.flush()
        append_case_audit_entry(
            db, case=locked_case, actor_id=actor, actor_role="NAMED_AUTHORITY",
            action_code="OVERRIDE_AUTHORITY_APPROVED" if event_type == "APPROVED" else "OVERRIDE_AUTHORITY_REJECTED",
            entity_type="case_override_request", entity_id=str(record.id), version_id=version.id,
            request_id=getattr(request.state, "request_id", None), reason=payload.reason,
            before_sha256=record.proposal_sha256,
            after_sha256=record.proposal_sha256 if event_type == "APPROVED" else None,
            details={"decision": payload.decision, "authority_grant_ref": payload.authority_grant_ref,
                     "authority_scope_ref": payload.authority_scope_ref,
                     "valid_until": payload.valid_until.isoformat() if payload.valid_until else None,
                     "application_effect": "NOT_APPLIED"},
        )
        _enqueue_case_workflow_event(db, locked_case, "NAMED_AUTHORITY_DECISION", {
            "reason_code": event_type, "authority_reference": payload.authority_grant_ref,
            "external_gate_reference": str(record.id)},
            idempotency_key=f"AUTHORITY_DECISION:{decision_event.id}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Authority decision already exists or violates approval governance constraints") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(decision_event)
    return {"override_request": _override_request_out(db, record),
            "decision_event_id": str(decision_event.id), "decision": payload.decision,
            "override_applied": False, "policy_engine_updated": False,
            "camunda_task_completed": False}


@app.post("/api/v1/cases/{case_id}/governance/override-requests/{request_id}/withdraw",
          status_code=201, tags=["override-governance"], dependencies=[Depends(require_internal_token)])
def withdraw_case_override_request(
    case_id: UUID, request_id: UUID, request: Request, payload: OverrideWithdrawIn,
    db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _case_governance_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                                                   expected_role="MAKER")
    locked_case = (db.query(models.Case).filter_by(id=case_id)
                   .populate_existing().with_for_update().first())
    if not locked_case:
        raise HTTPException(404, "Case not found")
    actor, roles = _assert_case_bank_scope(locked_case, x_actor_id, x_actor_roles, x_bank_id)
    require_governance_role(actor, roles, "MAKER")
    record = db.query(models.CaseOverrideRequest).filter_by(id=request_id, case_id=case_id).first()
    if not record:
        raise HTTPException(404, "Override request not found")
    if actor != record.requested_by:
        raise HTTPException(403, "Only the proposing Maker can withdraw this request")
    status, _ = override_request_state(db, record)
    if status not in {"PENDING_CHECKER", "PENDING_AUTHORITY"}:
        raise HTTPException(409, f"Override request cannot be withdrawn in state {status}")
    event = models.CaseOverrideEvent(
        id=uuid4(), case_id=case_id, request_id=record.id, event_type="WITHDRAWN",
        actor_id=actor, actor_role="MAKER", reason=payload.reason,
        proposal_sha256=record.proposal_sha256,
        details={"withdrawn_by_requester": True},
    )
    try:
        db.add(event)
        db.flush()
        append_case_audit_entry(
            db, case=locked_case, actor_id=actor, actor_role="MAKER", action_code="OVERRIDE_REQUEST_WITHDRAWN",
            entity_type="case_override_request", entity_id=str(record.id), version_id=record.version_id,
            request_id=getattr(request.state, "request_id", None), reason=payload.reason,
            before_sha256=record.proposal_sha256,
            details={"request_kind": record.request_kind, "exception_code": record.exception_code},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Override request already has a terminal decision") from exc
    except Exception:
        db.rollback()
        raise
    return {"override_request": _override_request_out(db, record), "withdrawn": True}


@app.get("/api/v1/cases/{case_id}/governance/override-requests",
         tags=["override-governance"], dependencies=[Depends(require_internal_token)])
def list_case_override_requests(
    case_id: UUID, db: Session = Depends(get_db), limit: int = Query(default=100, ge=1, le=200),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _case_override_reader_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    records = (db.query(models.CaseOverrideRequest).filter_by(case_id=case.id)
               .order_by(models.CaseOverrideRequest.created_at.desc()).limit(limit).all())
    return [_override_request_out(db, row) for row in records]


@app.get("/api/v1/cases/{case_id}/governance/override-requests/{request_id}",
         tags=["override-governance"], dependencies=[Depends(require_internal_token)])
def get_case_override_request(
    case_id: UUID, request_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _case_override_reader_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    record = db.query(models.CaseOverrideRequest).filter_by(id=request_id, case_id=case.id).first()
    if not record:
        raise HTTPException(404, "Override request not found")
    return _override_request_out(db, record)


@app.get("/api/v1/cases/{case_id}/governance/audit-trail",
         tags=["governance-audit"], dependencies=[Depends(require_internal_token)])
def list_case_audit_trail(
    case_id: UUID, db: Session = Depends(get_db), after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _case_audit_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    rows = (db.query(models.CaseAuditEntry).filter(models.CaseAuditEntry.case_id == case.id,
                                                   models.CaseAuditEntry.sequence_no > after_sequence)
            .order_by(models.CaseAuditEntry.sequence_no.asc()).limit(limit).all())
    next_sequence = rows[-1].sequence_no if rows else after_sequence
    return {"case_id": str(case.id), "entries": [_audit_entry_out(row) for row in rows],
            "next_after_sequence": next_sequence, "has_more": len(rows) == limit}


@app.get("/api/v1/cases/{case_id}/governance/audit-trail/verify",
         tags=["governance-audit"], dependencies=[Depends(require_internal_token)])
def verify_case_audit_trail(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _case_audit_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id)
    rows = (db.query(models.CaseAuditEntry).filter_by(case_id=case.id)
            .order_by(models.CaseAuditEntry.sequence_no.asc()).all())
    result = verify_audit_chain(rows)
    return {"case_id": str(case.id), **result,
            "tamper_evident_not_external_signature": True}


# ---- V9.5.1 Camunda 8 workflow integration boundary ----
_WORKFLOW_HUMAN_DENY = {"MAKER", "CHECKER", "NAMED_AUTHORITY", "BANK_POLICY_OWNER", "BANK_ADMIN", "SYSTEM_ADMIN"}
_WORKFLOW_EVENT_TYPES = {
    "PROCESS_STARTED", "TASK_ASSIGNED", "TASK_COMPLETED", "EVIDENCE_EXPIRED",
    "CASE_EXPIRED", "PROCESS_COMPLETED", "CAMUNDA_INCIDENT",
    "G3_SHADOW_GATE_PASSED", "G4_OPERATIONAL_GATE_PASSED",
}


def _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, allowed_roles):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    actor, roles, bank_id = trusted_actor_context(x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    if not roles.intersection(set(allowed_roles)):
        raise HTTPException(403, "Actor is not authorized for this workflow operation")
    if {"MAKER", "CHECKER"}.issubset(roles):
        raise HTTPException(403, "Maker and Checker identities must remain separated")
    enforce_bank_scope(case.bank_id, bank_id, roles, not_found_message="Case not found")
    return case, actor, roles


def _workflow_service_context(x_actor_id, x_actor_roles, x_bank_id):
    actor, roles, bank_id = trusted_actor_context(x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    if "WORKFLOW_ORCHESTRATOR" not in roles or roles.intersection(_WORKFLOW_HUMAN_DENY):
        raise HTTPException(403, "A dedicated WORKFLOW_ORCHESTRATOR service identity is required")
    return actor, roles, bank_id


def _enqueue_case_workflow_event(db, case, event_type: str, payload: dict, *, idempotency_key: str | None = None):
    """Insert a no-PII outbox event in the caller's transaction when a binding exists."""
    binding = (db.query(models.CaseWorkflowBinding)
               .filter_by(case_id=case.id, status="ACTIVE").first())
    if binding is None:
        return None
    safe_payload = sanitize_workflow_event_payload(payload)
    idem = idempotency_key or f"{event_type}:{uuid4()}"
    digest = sha256_json(safe_payload)
    existing = (db.query(models.WorkflowOutboxEvent)
                .filter_by(case_id=case.id, idempotency_key=idem).first())
    if existing:
        if existing.payload_sha256 != digest or existing.event_type != event_type:
            raise HTTPException(409, "Workflow outbox idempotency key conflicts with an existing event")
        return existing
    row = models.WorkflowOutboxEvent(
        case_id=case.id, binding_id=binding.id, event_type=event_type,
        idempotency_key=idem, correlation_id=uuid4(), payload=safe_payload,
        payload_sha256=digest, status="PENDING", attempts=0,
        available_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def _workflow_binding_out(row):
    return {
        "id": str(row.id), "case_id": str(row.case_id), "bank_id": row.bank_id,
        "engine_name": row.engine_name, "process_definition_key": row.process_definition_key,
        "process_instance_id": row.process_instance_id, "business_key": row.business_key,
        "status": row.status, "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _workflow_request_out(row):
    return {
        "id": str(row.id), "case_id": str(row.case_id), "request_no": row.request_no,
        "required_item_codes": row.required_item_codes, "reason": row.reason,
        "requested_by": row.requested_by,
        "based_on_version_id": str(row.based_on_version_id) if row.based_on_version_id else None,
        "due_at": row.due_at.isoformat(), "status": row.status,
        "created_at": row.created_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _workflow_reopen_out(row):
    return {
        "id": str(row.id), "case_id": str(row.case_id),
        "based_on_version_id": str(row.based_on_version_id) if row.based_on_version_id else None,
        "new_version_id": str(row.new_version_id) if row.new_version_id else None,
        "reason_code": row.reason_code, "reason": row.reason, "status": row.status,
        "requested_by": row.requested_by, "created_at": row.created_at.isoformat(),
        "consumed_at": row.consumed_at.isoformat() if row.consumed_at else None,
    }


def _workflow_outbox_out(row, binding=None):
    return {
        "event_id": str(row.id), "case_id": str(row.case_id),
        "process_instance_id": binding.process_instance_id if binding else None, "event_type": row.event_type,
        "correlation_id": str(row.correlation_id), "idempotency_key": row.idempotency_key,
        "payload": row.payload, "payload_sha256": row.payload_sha256,
        "attempts": row.attempts, "status": row.status,
        "available_at": row.available_at.isoformat(),
    }


@app.post("/api/v1/workflow/cases/{case_id}/binding", status_code=201,
          tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def register_case_workflow_binding(
    case_id: UUID, payload: WorkflowBindingIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, _ = _workflow_case_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"WORKFLOW_ORCHESTRATOR"})
    case = db.query(models.Case).filter_by(id=case_id).populate_existing().with_for_update().first()
    existing_process = db.query(models.CaseWorkflowBinding).filter_by(
        process_instance_id=payload.process_instance_id).first()
    if existing_process:
        if (existing_process.case_id == case_id and existing_process.process_definition_key == payload.process_definition_key
                and existing_process.business_key == payload.business_key):
            return _workflow_binding_out(existing_process)
        raise HTTPException(409, "Process instance is already bound to a different case or business key")
    active = db.query(models.CaseWorkflowBinding).filter_by(case_id=case_id, status="ACTIVE").first()
    if active:
        raise HTTPException(409, "Case already has an active Camunda process binding")
    row = models.CaseWorkflowBinding(
        case_id=case_id, bank_id=case.bank_id, engine_name="CAMUNDA_8",
        process_definition_key=payload.process_definition_key,
        process_instance_id=payload.process_instance_id, business_key=payload.business_key,
        status="ACTIVE",
    )
    db.add(row)
    try:
        db.flush()
        _enqueue_case_workflow_event(db, case, "DATA_AI_CASE_BOUND", {
            "task_type": "CASE_INTAKE", "reason_code": "PROCESS_CORRELATION_REGISTERED"},
            idempotency_key=f"CASE_BOUND:{row.id}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent workflow binding or duplicate process instance") from exc
    db.refresh(row)
    return _workflow_binding_out(row)


@app.get("/api/v1/workflow/cases/{case_id}/binding", tags=["workflow-integration"],
         dependencies=[Depends(require_internal_token)])
def get_case_workflow_binding(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                           {"WORKFLOW_ORCHESTRATOR", "MAKER", "CHECKER", "BANK_STAFF", "BANK_ADMIN", "SYSTEM_ADMIN"})
    rows = (db.query(models.CaseWorkflowBinding).filter_by(case_id=case_id)
            .order_by(models.CaseWorkflowBinding.created_at.desc()).all())
    return [_workflow_binding_out(row) for row in rows]


@app.post("/api/v1/workflow/outbox/claim", tags=["workflow-integration"],
          dependencies=[Depends(require_internal_token)])
def claim_workflow_outbox_events(
    payload: WorkflowOutboxClaimIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _, _, bank_id = _workflow_service_context(x_actor_id, x_actor_roles, x_bank_id)
    now = datetime.now(timezone.utc)
    eligible = db.query(models.WorkflowOutboxEvent).join(
        models.Case, models.Case.id == models.WorkflowOutboxEvent.case_id
    ).filter(models.Case.bank_id == bank_id).filter(
        ((models.WorkflowOutboxEvent.status == "PENDING") & (models.WorkflowOutboxEvent.available_at <= now)) |
        ((models.WorkflowOutboxEvent.status == "IN_FLIGHT") & (models.WorkflowOutboxEvent.locked_until <= now))
    ).order_by(models.WorkflowOutboxEvent.created_at.asc()).with_for_update(skip_locked=True).limit(payload.limit).all()
    claimed = []
    for row in eligible:
        if row.attempts >= 8:
            validate_outbox_transition(row.status, "DEAD_LETTER", attempts=row.attempts)
            row.status = "DEAD_LETTER"
            row.claimed_by = None
            row.locked_until = None
            row.last_error_code = row.last_error_code or "MAX_DELIVERY_ATTEMPTS"
            continue
        row.status = "IN_FLIGHT"
        row.attempts += 1
        row.claimed_by = payload.worker_id
        row.locked_until = now + timedelta(seconds=payload.lease_seconds)
        claimed.append(row)
    db.commit()
    return {"claimed_count": len(claimed), "worker_id": payload.worker_id,
            "events": [_workflow_outbox_out(row, db.get(models.CaseWorkflowBinding, row.binding_id)) for row in claimed]}


@app.post("/api/v1/workflow/outbox/{event_id}/ack", tags=["workflow-integration"],
          dependencies=[Depends(require_internal_token)])
def acknowledge_workflow_outbox_event(
    event_id: UUID, payload: WorkflowOutboxAckIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _, _, bank_id = _workflow_service_context(x_actor_id, x_actor_roles, x_bank_id)
    row = (db.query(models.WorkflowOutboxEvent).join(models.Case, models.Case.id == models.WorkflowOutboxEvent.case_id)
           .filter(models.WorkflowOutboxEvent.id == event_id, models.Case.bank_id == bank_id)
           .with_for_update().first())
    if not row:
        raise HTTPException(404, "Workflow outbox event not found")
    if row.status == "DELIVERED" and payload.decision == "DELIVERED":
        return {"event_id": str(row.id), "status": row.status, "idempotent": True}
    if row.status != "IN_FLIGHT" or row.claimed_by != payload.worker_id:
        raise HTTPException(409, "Outbox event is not leased by this worker")
    now = datetime.now(timezone.utc)
    if row.locked_until is None or row.locked_until <= now:
        raise HTTPException(409, "Outbox event lease has expired")
    target = {"DELIVERED": "DELIVERED", "RETRY": "PENDING", "DEAD_LETTER": "DEAD_LETTER"}[payload.decision]
    try:
        validate_outbox_transition(row.status, target)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    row.status = target
    row.last_error_code = payload.error_code
    if target == "DELIVERED":
        row.delivered_at = now
    elif target == "PENDING":
        if row.attempts >= 8:
            row.status = "DEAD_LETTER"
            row.last_error_code = "MAX_DELIVERY_ATTEMPTS"
        else:
            backoff_floor = min(3600, 5 * (2 ** max(0, row.attempts - 1)))
            row.available_at = now + timedelta(seconds=max(payload.retry_after_seconds, backoff_floor))
    row.claimed_by = None
    row.locked_until = None
    db.commit()
    return {"event_id": str(row.id), "status": row.status, "attempts": row.attempts}


@app.post("/api/v1/workflow/events", tags=["workflow-integration"],
          dependencies=[Depends(require_internal_token)])
def receive_camunda_workflow_event(
    payload: WorkflowInboxEventIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    actor, roles, bank_id = _workflow_service_context(x_actor_id, x_actor_roles, x_bank_id)
    binding = (db.query(models.CaseWorkflowBinding).filter_by(process_instance_id=payload.process_instance_id)
               .with_for_update().first())
    if not binding or binding.bank_id != bank_id:
        raise HTTPException(404, "Workflow process binding not found")
    safe_payload = sanitize_workflow_event_payload(payload.payload)
    payload_hash = sha256_json({"event_type": payload.event_type, "payload": safe_payload,
                                "process_sequence": payload.process_sequence,
                                "process_instance_id": payload.process_instance_id})
    prior = db.query(models.WorkflowInboxEvent).filter_by(external_event_id=str(payload.external_event_id)).first()
    if prior:
        if prior.payload_sha256 != payload_hash:
            raise HTTPException(409, "External event ID was reused with different content")
        return {"event_id": str(prior.id), "duplicate": True, "accepted": True}
    if binding.status != "ACTIVE":
        raise HTTPException(409, "Workflow process binding is already terminal")
    latest = (db.query(models.WorkflowInboxEvent).filter_by(binding_id=binding.id)
              .order_by(models.WorkflowInboxEvent.process_sequence.desc()).first())
    expected_sequence = (latest.process_sequence + 1) if latest else 1
    if payload.process_sequence != expected_sequence:
        raise HTTPException(409, {"message": "Camunda event sequence is not contiguous",
                                  "expected_sequence": expected_sequence,
                                  "received_sequence": payload.process_sequence})
    if payload.event_type not in _WORKFLOW_EVENT_TYPES:
        raise HTTPException(422, "Unsupported workflow event type")
    if payload.event_type == "EVIDENCE_EXPIRED":
        try:
            request_id = UUID(str(safe_payload.get("evidence_request_id")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "Invalid evidence_request_id") from exc
        evidence_request = (db.query(models.CaseEvidenceRequest).filter_by(id=request_id, case_id=binding.case_id)
                            .with_for_update().first())
        if not evidence_request:
            raise HTTPException(404, "Evidence request not found")
        if evidence_request.status != "AWAITING_EVIDENCE":
            raise HTTPException(409, "Evidence request is no longer awaiting evidence")
        if evidence_request.due_at > datetime.now(timezone.utc):
            raise HTTPException(409, "Camunda evidence timer callback arrived before the recorded due_at")
        evidence_request.status = "EXPIRED"
        evidence_request.updated_at = datetime.now(timezone.utc)
        evidence_request.resolved_at = datetime.now(timezone.utc)
    elif payload.event_type == "CASE_EXPIRED":
        # Expiry is a Camunda-owned lifecycle event. Do not rewrite the DATA-AI
        # Case row here: V14 may have frozen its source snapshot after Checker.
        # The append-only inbox event is the authoritative integration receipt.
        latest_version = get_latest_case_version(db, binding.case_id)
        if latest_version:
            latest_state, _ = get_version_state(db, latest_version.id)
            if latest_state not in {"CHECKER_CONFIRMED", "RETURNED_TO_MAKER", "SUPERSEDED"}:
                raise HTTPException(409, "CASE_EXPIRED is not valid while a DATA-AI review cycle is open")
    elif payload.event_type in {"G3_SHADOW_GATE_PASSED", "G4_OPERATIONAL_GATE_PASSED"}:
        expected_gate = "G3_SHADOW" if payload.event_type == "G3_SHADOW_GATE_PASSED" else "G4_OPERATIONAL"
        gate = db.query(models.CaseWorkflowReleaseGate).filter_by(
            case_id=binding.case_id, external_gate_reference=safe_payload.get("external_gate_reference"),
            gate_code=expected_gate).first()
        if not gate:
            raise HTTPException(409, "Release callback has no matching externally recorded release-gate reference")
    elif payload.event_type == "PROCESS_COMPLETED":
        binding.status = "COMPLETED"
        binding.updated_at = datetime.now(timezone.utc)
    row = models.WorkflowInboxEvent(
        case_id=binding.case_id, binding_id=binding.id,
        external_event_id=str(payload.external_event_id), process_sequence=payload.process_sequence,
        event_type=payload.event_type, payload=safe_payload, payload_sha256=payload_hash,
    )
    db.add(row)
    db.add(models.AuditEvent(case_id=binding.case_id, actor=actor[:100], action=f"WORKFLOW_{payload.event_type}",
        entity_type="workflow_inbox_event", entity_id=str(payload.external_event_id),
        details={"process_instance_id": payload.process_instance_id,
                 "process_sequence": payload.process_sequence, "payload_sha256": payload_hash,
                 "actor_roles": sorted(roles)}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Duplicate or out-of-order workflow callback") from exc
    return {"event_id": str(row.id), "duplicate": False, "accepted": True,
            "process_sequence": row.process_sequence, "payload_sha256": payload_hash}


@app.get("/api/v1/workflow/cases/{case_id}/events", tags=["workflow-integration"],
         dependencies=[Depends(require_internal_token)])
def get_case_workflow_event_trace(
    case_id: UUID, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                           {"WORKFLOW_ORCHESTRATOR", "MAKER", "CHECKER", "BANK_STAFF"})
    inbox = (db.query(models.WorkflowInboxEvent).filter_by(case_id=case_id)
             .order_by(models.WorkflowInboxEvent.received_at.desc()).limit(limit).all())
    outbox = (db.query(models.WorkflowOutboxEvent).filter_by(case_id=case_id)
              .order_by(models.WorkflowOutboxEvent.created_at.desc()).limit(limit).all())
    bindings = {str(row.id): row for row in db.query(models.CaseWorkflowBinding).filter_by(case_id=case_id).all()}
    return {
        "case_id": str(case_id),
        "inbox": [{"external_event_id": row.external_event_id, "process_sequence": row.process_sequence,
                   "event_type": row.event_type, "payload_sha256": row.payload_sha256,
                   "received_at": row.received_at.isoformat()} for row in inbox],
        "outbox": [_workflow_outbox_out(row, bindings.get(str(row.binding_id))) for row in outbox],
        "trace_is_delivery_evidence_not_camunda_task_authority": True,
    }


@app.post("/api/v1/cases/{case_id}/workflow/evidence-requests", status_code=201,
          tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def create_case_evidence_request(
    case_id: UUID, payload: WorkflowEvidenceRequestIn, request: Request, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER"})
    binding = db.query(models.CaseWorkflowBinding).filter_by(case_id=case_id, status="ACTIVE").first()
    if not binding:
        raise HTTPException(409, "Case has no active Camunda workflow binding")
    latest = get_latest_case_version(db, case_id)
    based_on = payload.based_on_version_id or (latest.id if latest else None)
    if payload.based_on_version_id and (not latest or payload.based_on_version_id != latest.id):
        raise HTTPException(409, "Evidence request must bind to the latest analysis version")
    if latest:
        state, _ = get_version_state(db, latest.id)
        if state == "FROZEN":
            raise HTTPException(409, "Checker review is in progress; evidence request cannot mutate this review cycle")
    last_no = (db.query(models.CaseEvidenceRequest.request_no).filter_by(case_id=case_id)
               .order_by(models.CaseEvidenceRequest.request_no.desc()).first())
    row = models.CaseEvidenceRequest(
        case_id=case_id, bank_id=case.bank_id, binding_id=binding.id,
        request_no=(last_no[0] + 1 if last_no else 1), required_item_codes=payload.required_item_codes,
        reason=payload.reason, requested_by=actor, based_on_version_id=based_on,
        due_at=payload.due_at, status="AWAITING_EVIDENCE",
    )
    db.add(row)
    try:
        db.flush()
        _enqueue_case_workflow_event(db, case, "EVIDENCE_REQUESTED", {
            "evidence_request_id": str(row.id), "reason_code": "AWAITING_EVIDENCE",
            "due_at": payload.due_at.isoformat()}, idempotency_key=f"EVIDENCE_REQUESTED:{row.id}")
        db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="EVIDENCE_REQUESTED",
            entity_type="case_evidence_request", entity_id=str(row.id),
            details={"request_no": row.request_no, "required_item_codes": row.required_item_codes,
                     "due_at": row.due_at.isoformat()}))
        append_case_audit_entry(db, case=case, actor_id=actor, actor_role="MAKER",
            action_code="EVIDENCE_REQUESTED", entity_type="case_evidence_request", entity_id=str(row.id),
            request_id=getattr(request.state, "request_id", None) if request else None,
            reason=payload.reason, details={"request_no": row.request_no,
                                            "required_item_codes": row.required_item_codes,
                                            "due_at": row.due_at.isoformat()})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent evidence request number or workflow conflict") from exc
    db.refresh(row)
    return _workflow_request_out(row)


@app.get("/api/v1/cases/{case_id}/workflow/evidence-requests", tags=["workflow-integration"],
         dependencies=[Depends(require_internal_token)])
def list_case_evidence_requests(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                           {"MAKER", "CHECKER", "BANK_STAFF", "BANK_ADMIN", "SYSTEM_ADMIN"})
    rows = (db.query(models.CaseEvidenceRequest).filter_by(case_id=case_id)
            .order_by(models.CaseEvidenceRequest.request_no.desc()).all())
    return [_workflow_request_out(row) for row in rows]


@app.post("/api/v1/cases/{case_id}/workflow/evidence-requests/{request_id}/resubmit", status_code=201,
          tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def resubmit_case_evidence(
    case_id: UUID, request_id: UUID, payload: WorkflowResubmissionIn, request: Request,
    db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    case, actor, _ = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER"})
    case = db.query(models.Case).filter_by(id=case_id).populate_existing().with_for_update().first()
    evidence_request = (db.query(models.CaseEvidenceRequest).filter_by(id=request_id, case_id=case_id)
                        .populate_existing().with_for_update().first())
    if not evidence_request:
        raise HTTPException(404, "Evidence request not found")
    if evidence_request.status != "AWAITING_EVIDENCE":
        raise HTTPException(409, "Evidence request is not awaiting evidence")
    latest = get_latest_case_version(db, case_id)
    latest_state, _ = get_version_state(db, latest.id) if latest else ("DRAFT", [])
    open_reopen = (db.query(models.CaseWorkflowReopen).filter_by(case_id=case_id, status="OPEN")
                   .with_for_update().first())
    if latest_state == "FROZEN":
        raise HTTPException(409, "Checker review is active; evidence cannot be appended")
    if latest_state == "CHECKER_CONFIRMED" and (not open_reopen or open_reopen.reason_code != "EVIDENCE_UPDATED"):
        raise HTTPException(409, "Open the confirmed case for evidence changes before uploading/resubmitting")
    if evidence_request.based_on_version_id and latest and evidence_request.based_on_version_id != latest.id:
        raise HTTPException(409, "Evidence request is based on a stale analysis version")
    documents = (db.query(models.Document).filter(models.Document.case_id == case_id,
                  models.Document.id.in_(payload.document_ids)).all())
    if len(documents) != len(payload.document_ids):
        raise HTTPException(422, "One or more evidence documents are missing or belong to another case")
    manifest_entries = (db.query(models.EvidenceManifestEntry).filter(
        models.EvidenceManifestEntry.case_id == case_id,
        models.EvidenceManifestEntry.document_id.in_(payload.document_ids)).all())
    if len(manifest_entries) != len(payload.document_ids):
        raise HTTPException(422, "Every resubmitted document must have a manifest entry")
    all_manifest = (db.query(models.EvidenceManifestEntry).filter_by(case_id=case_id)
                    .order_by(models.EvidenceManifestEntry.sequence_no.asc()).all())
    chain = verify_manifest_chain(all_manifest)
    if not chain.get("valid"):
        raise HTTPException(409, "Evidence manifest chain is invalid")
    from pathlib import Path as _Path
    manifest_by_doc = {str(m.document_id): m for m in manifest_entries}
    scan_events = (db.query(models.DocumentSecurityEvent).filter(
        models.DocumentSecurityEvent.document_id.in_(payload.document_ids)).all())
    for doc in documents:
        manifest = manifest_by_doc.get(str(doc.id))
        if not manifest or manifest.sha256 != doc.sha256 or manifest.file_size != doc.file_size:
            raise HTTPException(409, "Resubmitted document does not match its manifest entry")
        stored = _Path(doc.stored_path)
        if not stored.is_file() or service.sha256_file(stored) != doc.sha256:
            raise HTTPException(409, "Resubmitted evidence bytes are missing or hash-mismatched")
        matching_scan = [e for e in scan_events if e.document_id == doc.id
                         and e.scan_status == "CLEAN" and e.event_type == "SCAN_COMPLETED"
                         and e.recorded_by and e.engine_name == "ClamAV" and e.engine_version
                         and e.scanned_sha256 == doc.sha256
                         and e.attestation_version == "V1_CLAMAV"]
        if doc.malware_scan_status != "CLEAN" or not matching_scan:
            raise HTTPException(422, "Resubmitted file lacks a byte-bound ClamAV CLEAN attestation")
    field_count = (db.query(models.ExtractedField).join(models.Document,
        models.Document.id == models.ExtractedField.document_id).filter(
        models.Document.case_id == case_id, models.Document.id.in_(payload.document_ids)).count())
    transaction_count = db.query(models.Transaction).filter(
        models.Transaction.case_id == case_id, models.Transaction.document_id.in_(payload.document_ids)).count()
    next_version_no = (latest.version_no + 1) if latest else 1
    impact = build_resubmission_impact(
        case_id=str(case_id), request_id=str(evidence_request.id),
        document_ids=[str(v) for v in payload.document_ids],
        base_version_id=str(latest.id) if latest else None,
        next_version_no=next_version_no, field_count=field_count,
        transaction_count=transaction_count,
        manifest_sequence_numbers=[m.sequence_no for m in manifest_entries],
    )
    impact_hash = sha256_json(impact)
    row = models.CaseResubmission(
        case_id=case_id, evidence_request_id=evidence_request.id,
        based_on_version_id=latest.id if latest else None,
        received_document_ids=[str(v) for v in payload.document_ids], impact_list=impact,
        impact_sha256=impact_hash, requested_new_version_no=next_version_no, created_by=actor,
    )
    db.add(row)
    evidence_request.status = "RECEIVED"
    evidence_request.updated_at = datetime.now(timezone.utc)
    evidence_request.resolved_at = datetime.now(timezone.utc)
    try:
        db.flush()
        _enqueue_case_workflow_event(db, case, "EVIDENCE_RESUBMITTED", {
            "evidence_request_id": str(evidence_request.id), "resubmission_id": str(row.id),
            "impact_sha256": impact_hash, "analysis_version_id": str(latest.id) if latest else None,
            "reason_code": "NEW_EVIDENCE_RECEIVED"},
            idempotency_key=f"EVIDENCE_RESUBMITTED:{evidence_request.id}")
        db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="EVIDENCE_RESUBMITTED",
            entity_type="case_resubmission", entity_id=str(row.id),
            details={"impact_sha256": impact_hash, "requested_new_version_no": next_version_no,
                     "document_ids": [str(v) for v in payload.document_ids]}))
        append_case_audit_entry(db, case=case, actor_id=actor, actor_role="MAKER",
            action_code="EVIDENCE_RESUBMITTED", entity_type="case_resubmission", entity_id=str(row.id),
            version_id=latest.id if latest else None,
            request_id=getattr(request.state, "request_id", None), reason=payload.reason,
            before_sha256=latest.snapshot_sha256 if latest else None, after_sha256=impact_hash,
            details={"requested_new_version_no": next_version_no, "impact_sha256": impact_hash})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Evidence request has already been resubmitted or workflow data changed") from exc
    return {"resubmission_id": str(row.id), "evidence_request_id": str(evidence_request.id),
            "status": "RECEIVED", "impact_list": impact, "impact_sha256": impact_hash,
            "requested_new_version_no": next_version_no,
            "analysis_version_created": False,
            "next_step": "Maker reviews the impact list and freezes the next immutable analysis version"}


@app.get("/api/v1/cases/{case_id}/workflow/resubmissions", tags=["workflow-integration"],
         dependencies=[Depends(require_internal_token)])
def list_case_workflow_resubmissions(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER", "CHECKER"})
    rows = (db.query(models.CaseResubmission).filter_by(case_id=case_id)
            .order_by(models.CaseResubmission.created_at.desc()).all())
    return [{
        "resubmission_id": str(row.id), "evidence_request_id": str(row.evidence_request_id),
        "based_on_version_id": str(row.based_on_version_id) if row.based_on_version_id else None,
        "received_document_ids": row.received_document_ids, "impact_list": row.impact_list,
        "impact_sha256": row.impact_sha256, "requested_new_version_no": row.requested_new_version_no,
        "created_by": row.created_by, "created_at": row.created_at.isoformat(),
        "analysis_version_created": False,
    } for row in rows]


@app.post("/api/v1/cases/{case_id}/workflow/reopen", status_code=201,
          tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def reopen_case_workflow(
    case_id: UUID, payload: WorkflowReopenIn, request: Request, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    roles_needed = {"MAKER"} if payload.reason_code in {"EVIDENCE_UPDATED", "EXTERNAL_REVIEW_REOPEN"} else {"BANK_POLICY_OWNER"}
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, roles_needed)
    case = db.query(models.Case).filter_by(id=case_id).populate_existing().with_for_update().first()
    latest = get_latest_case_version(db, case_id)
    if not latest:
        raise HTTPException(409, "A case without an immutable analysis version cannot be reopened")
    state, _ = get_version_state(db, latest.id)
    if state != "CHECKER_CONFIRMED":
        raise HTTPException(409, "Only a Checker-confirmed version can enter post-completion reopen")
    if db.query(models.CaseWorkflowReopen).filter_by(case_id=case_id, status="OPEN").first():
        raise HTTPException(409, "Case already has an open reopen event")
    actor_role = "BANK_POLICY_OWNER" if "BANK_POLICY_OWNER" in roles else "MAKER"
    row = models.CaseWorkflowReopen(
        case_id=case_id, based_on_version_id=latest.id, reason_code=payload.reason_code,
        reason=payload.reason, policy_reference=payload.policy_reference,
        policy_version=payload.policy_version, product_code=payload.product_code,
        product_version=payload.product_version, evidence_refs=[], status="OPEN", requested_by=actor,
    )
    db.add(row)
    try:
        db.flush()
        case.status = "REOPENED"
        _enqueue_case_workflow_event(db, case, "CASE_REOPENED", {
            "reason_code": payload.reason_code, "policy_reference": payload.policy_reference,
            "policy_version": payload.policy_version, "product_code": payload.product_code,
            "product_version": payload.product_version}, idempotency_key=f"CASE_REOPENED:{row.id}")
        append_case_audit_entry(db, case=case, actor_id=actor, actor_role=actor_role,
            action_code="CASE_WORKFLOW_REOPENED", entity_type="case_workflow_reopen", entity_id=str(row.id),
            version_id=latest.id, request_id=getattr(request.state, "request_id", None),
            reason=payload.reason, before_sha256=latest.snapshot_sha256,
            details={"reason_code": payload.reason_code})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent or duplicate case reopen") from exc
    return _workflow_reopen_out(row)


@app.get("/api/v1/cases/{case_id}/workflow/reopen", tags=["workflow-integration"],
         dependencies=[Depends(require_internal_token)])
def list_case_workflow_reopens(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                           {"MAKER", "CHECKER", "BANK_POLICY_OWNER", "BANK_ADMIN", "SYSTEM_ADMIN"})
    rows = (db.query(models.CaseWorkflowReopen).filter_by(case_id=case_id)
            .order_by(models.CaseWorkflowReopen.created_at.desc()).all())
    return [_workflow_reopen_out(row) for row in rows]


def _validate_override_application_receipt(db: Session, case_id: UUID, proposal, *, required_policy_version: str | None = None):
    """Require Business Engine evidence before a Named Authority approval can enter G4/export."""
    proposal_state, _ = override_request_state(db, proposal)
    if proposal_state in {"PENDING_CHECKER", "PENDING_AUTHORITY", "STALE", "EXPIRED", "INTEGRITY_ERROR"}:
        raise HTTPException(409, f"Override proposal is not in a terminal valid state (status={proposal_state})")
    if proposal_state != "APPROVED":
        return None
    receipt = db.query(models.CaseOverrideApplicationReceipt).filter_by(
        case_id=case_id, request_id=proposal.id).first()
    if not receipt:
        raise HTTPException(409, "Named Authority approval has not been confirmed as applied by the Business Engine")
    version = db.query(models.CaseAnalysisVersion).filter_by(id=proposal.version_id, case_id=case_id).first()
    if (not version or not verify_version_integrity(version)
            or receipt.applied_proposal_sha256 != proposal.proposal_sha256
            or receipt.applied_version_sha256 != version.snapshot_sha256
            or receipt.policy_reference != proposal.policy_reference
            or receipt.policy_version != proposal.policy_version):
        raise HTTPException(409, "Business Engine application receipt does not match the approved proposal/version/policy")
    if required_policy_version and receipt.policy_version != required_policy_version:
        raise HTTPException(409, "G4 policy version does not match the Business Engine application receipt")
    return receipt


@app.post("/api/v1/cases/{case_id}/governance/override-requests/{request_id}/application-receipt",
          status_code=201, tags=["override-governance", "workflow-integration"],
          dependencies=[Depends(require_internal_token)])
def record_override_application_receipt(
    case_id: UUID, request_id: UUID, payload: OverrideApplicationReceiptIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    actor, roles, bank_id = trusted_actor_context(x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    if roles != {"BUSINESS_ENGINE"}:
        raise HTTPException(403, "A dedicated BUSINESS_ENGINE-only signed service identity is required")
    case = db.query(models.Case).filter_by(id=case_id).with_for_update().first()
    if not case:
        raise HTTPException(404, "Case not found")
    enforce_bank_scope(case.bank_id, bank_id, roles, not_found_message="Case not found")
    proposal = (db.query(models.CaseOverrideRequest).filter_by(
        id=request_id, case_id=case_id, bank_id=case.bank_id).first())
    if not proposal:
        raise HTTPException(404, "Override request not found")
    version = db.query(models.CaseAnalysisVersion).filter_by(id=proposal.version_id, case_id=case_id).first()
    if not version or not verify_version_integrity(version):
        raise HTTPException(409, "Approved proposal version is missing or failed snapshot integrity verification")
    if payload.applied_proposal_sha256 != proposal.proposal_sha256 or payload.applied_version_sha256 != version.snapshot_sha256:
        raise HTTPException(409, "Business Engine receipt hashes do not match the approved proposal and frozen version")
    if payload.policy_reference != proposal.policy_reference or payload.policy_version != proposal.policy_version:
        raise HTTPException(409, "Business Engine receipt policy reference/version does not match the proposal")
    state_name, _ = override_request_state(db, proposal)
    if state_name != "APPROVED":
        raise HTTPException(409, f"Only an active Named Authority approval can be applied (status={state_name})")
    existing = db.query(models.CaseOverrideApplicationReceipt).filter_by(request_id=proposal.id).first()
    if existing:
        same = (existing.external_application_reference == payload.external_application_reference
                and existing.applied_proposal_sha256 == payload.applied_proposal_sha256
                and existing.applied_version_sha256 == payload.applied_version_sha256
                and existing.policy_reference == payload.policy_reference
                and existing.policy_version == payload.policy_version)
        if same:
            return {"receipt_id": str(existing.id), "idempotent": True,
                    "external_application_reference": existing.external_application_reference,
                    "data_ai_applied_override": False}
        raise HTTPException(409, "A different Business Engine application receipt already exists for this proposal")
    row = models.CaseOverrideApplicationReceipt(
        case_id=case_id, request_id=proposal.id, bank_id=case.bank_id,
        external_application_reference=payload.external_application_reference,
        applied_proposal_sha256=payload.applied_proposal_sha256,
        applied_version_sha256=payload.applied_version_sha256,
        policy_reference=payload.policy_reference, policy_version=payload.policy_version,
        applied_by=actor, applied_at=payload.applied_at,
    )
    try:
        db.add(row)
        db.flush()
        append_case_audit_entry(
            db, case=case, actor_id=actor, actor_role="BUSINESS_ENGINE",
            action_code="OVERRIDE_APPLICATION_RECEIPT_RECORDED",
            entity_type="case_override_application_receipt", entity_id=str(row.id),
            version_id=version.id, before_sha256=proposal.proposal_sha256,
            after_sha256=payload.applied_proposal_sha256,
            details={"external_application_reference": payload.external_application_reference,
                     "policy_reference": payload.policy_reference, "policy_version": payload.policy_version,
                     "applied_version_sha256": payload.applied_version_sha256,
                     "data_ai_applied_override": False},
        )
        _enqueue_case_workflow_event(db, case, "OVERRIDE_APPLICATION_RECORDED", {
            "external_gate_reference": payload.external_application_reference,
            "authority_reference": str(proposal.id), "policy_reference": payload.policy_reference,
            "policy_version": payload.policy_version, "reason_code": "EXTERNAL_APPLICATION_RECEIPT"},
            idempotency_key=f"OVERRIDE_APPLICATION_RECEIPT:{proposal.id}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A Business Engine application receipt already exists or violates the proposal scope") from exc
    return {"receipt_id": str(row.id), "idempotent": False,
            "external_application_reference": row.external_application_reference,
            "proposal_sha256": row.applied_proposal_sha256, "version_sha256": row.applied_version_sha256,
            "data_ai_applied_override": False, "business_engine_attested_application": True}


@app.post("/api/v1/cases/{case_id}/workflow/release-gates", status_code=201,
          tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def record_case_workflow_release_gate(
    case_id: UUID, payload: WorkflowReleaseGateIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    required = {"RELEASE_AUTHORITY"} if payload.gate_code == "G4_OPERATIONAL" else {"BANK_POLICY_OWNER", "RELEASE_AUTHORITY"}
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, required)
    version = db.query(models.CaseAnalysisVersion).filter_by(id=payload.version_id, case_id=case_id).first()
    if not version or not verify_version_integrity(version):
        raise HTTPException(404 if not version else 409, "Analysis version not found or snapshot integrity failed")
    state, _ = get_version_state(db, version.id)
    if state != "CHECKER_CONFIRMED":
        raise HTTPException(409, "Release gate requires a Checker-confirmed technical evidence version")
    if db.query(models.CaseWorkflowReopen).filter_by(case_id=case_id, status="OPEN").first():
        raise HTTPException(409, "An open reopen event invalidates release eligibility")
    if payload.gate_code == "G4_OPERATIONAL":
        g3 = db.query(models.CaseWorkflowReleaseGate).filter_by(
            case_id=case_id, version_id=version.id, gate_code="G3_SHADOW").first()
        if not g3:
            raise HTTPException(409, "G4 Operational gate requires a prior G3 Shadow record for the same version")
        if (g3.product_code != payload.product_code or g3.product_version != payload.product_version
                or g3.policy_reference != payload.policy_reference or g3.policy_version != payload.policy_version
                or g3.snapshot_sha256 != version.snapshot_sha256):
            raise HTTPException(409, "G3 and G4 must reference identical product, policy and evidence snapshot versions")
        proposals = db.query(models.CaseOverrideRequest).filter_by(case_id=case_id, version_id=version.id).all()
        for proposal in proposals:
            _validate_override_application_receipt(db, case_id, proposal, required_policy_version=payload.policy_version)
    existing = db.query(models.CaseWorkflowReleaseGate).filter_by(
        case_id=case_id, version_id=version.id, gate_code=payload.gate_code).first()
    if existing:
        if existing.external_gate_reference == payload.external_gate_reference:
            return {"id": str(existing.id), "gate_code": existing.gate_code,
                    "status": "RECORDED_EXTERNAL_GATE", "idempotent": True}
        raise HTTPException(409, "A different external gate reference already exists for this version")
    row = models.CaseWorkflowReleaseGate(
        case_id=case_id, version_id=version.id, gate_code=payload.gate_code,
        actor_id=actor, actor_role="RELEASE_AUTHORITY" if payload.gate_code == "G4_OPERATIONAL" else (
            "BANK_POLICY_OWNER" if "BANK_POLICY_OWNER" in roles else "RELEASE_AUTHORITY"),
        external_gate_reference=payload.external_gate_reference,
        product_code=payload.product_code, product_version=payload.product_version,
        policy_reference=payload.policy_reference, policy_version=payload.policy_version,
        snapshot_sha256=version.snapshot_sha256,
    )
    db.add(row)
    try:
        db.flush()
        _enqueue_case_workflow_event(db, case, "RELEASE_GATE_RECORDED", {
            "external_gate_reference": payload.external_gate_reference,
            "reason_code": payload.gate_code, "product_code": payload.product_code,
            "product_version": payload.product_version, "policy_reference": payload.policy_reference,
            "policy_version": payload.policy_version}, idempotency_key=f"RELEASE_GATE:{row.id}")
        db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action=payload.gate_code,
            entity_type="case_workflow_release_gate", entity_id=str(row.id),
            details={"version_id": str(version.id), "snapshot_sha256": version.snapshot_sha256,
                     "external_gate_reference": payload.external_gate_reference}))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Release gate already exists or gate transition is invalid") from exc
    return {"id": str(row.id), "case_id": str(case_id), "version_id": str(version.id),
            "gate_code": row.gate_code, "status": "RECORDED_EXTERNAL_GATE",
            "external_gate_reference": row.external_gate_reference,
            "snapshot_sha256": row.snapshot_sha256,
            "credit_decision": False, "camunda_gate_completion": False}


@app.post("/api/v1/cases/{case_id}/workflow/export-packages", status_code=201,
          tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def create_case_workflow_export_package(
    case_id: UUID, payload: WorkflowExportPackageIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _workflow_case_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER", "CHECKER"})
    if {"MAKER", "CHECKER"}.issubset(roles):
        raise HTTPException(403, "Maker and Checker identities must remain separated")
    version = db.query(models.CaseAnalysisVersion).filter_by(id=payload.version_id, case_id=case_id).first()
    if not version:
        raise HTTPException(404, "Analysis version not found")
    if not verify_version_integrity(version):
        raise HTTPException(409, "Analysis snapshot hash verification failed")
    state, _ = get_version_state(db, version.id)
    if state != "CHECKER_CONFIRMED":
        raise HTTPException(409, "Evidence package export requires a Checker-confirmed version")
    latest_submission = (db.query(models.ApplicantSubmission).filter_by(case_id=case_id)
                         .order_by(models.ApplicantSubmission.submitted_at.desc()).first())
    if latest_submission is None:
        raise HTTPException(409, "No applicant submission snapshot exists for this case")
    applicant_hash = sha256_json({
        "applicant_ref": latest_submission.applicant_ref, "form_version": latest_submission.form_version,
        "form_data": latest_submission.form_data, "consent_reference": latest_submission.consent_reference,
        "submitted_at": latest_submission.submitted_at.isoformat() if latest_submission.submitted_at else None,
    })
    documents = db.query(models.Document).filter_by(case_id=case_id).order_by(models.Document.created_at).all()
    if not documents:
        raise HTTPException(409, "Export package requires at least one manifested evidence document")
    if db.query(models.CaseWorkflowReopen).filter_by(case_id=case_id, status="OPEN").first():
        raise HTTPException(409, "Export package is blocked while a governed reopen is pending")

    # Export must be tied to an external Business Engine receipt and the same
    # immutable DATA-AI snapshot. A version freeze without the matching engine
    # receipt is not an export-ready assessment package.
    latest_scope_attestation = _v10_latest_attestation(db, case_id)
    if (latest_scope_attestation is None or latest_scope_attestation.scope_status != "IN_SCOPE"
            or latest_scope_attestation.consent_status != "GRANTED"):
        raise HTTPException(409, "Export is blocked because current Backend scope/consent attestation is not granted")
    engine_receipt = (db.query(models.CaseBusinessEngineReceipt).filter_by(case_id=case_id)
        .order_by(models.CaseBusinessEngineReceipt.received_at.desc(), models.CaseBusinessEngineReceipt.id.desc()).first())
    if engine_receipt is None or engine_receipt.result_status != "COMPLETED":
        raise HTTPException(409, "Export requires the latest external Business Engine receipt to be COMPLETED")
    input_bundle = db.query(models.CaseFinancialInputBundle).filter_by(
        id=engine_receipt.bundle_id, case_id=case_id).first()
    if (input_bundle is None or input_bundle.readiness_status != "READY_FOR_BUSINESS_ENGINE"
            or sha256_json(input_bundle.bundle_data) != input_bundle.bundle_sha256
            or engine_receipt.input_bundle_sha256 != input_bundle.bundle_sha256):
        raise HTTPException(409, "Business Engine receipt input bundle is missing, not ready or hash-mismatched")
    application = db.query(models.LoanApplication).filter_by(case_id=case_id).first()
    schedule = (db.query(models.CaseProposedScheduleReference).filter_by(
        id=engine_receipt.schedule_reference_id, case_id=case_id, bundle_id=input_bundle.id,
        product_code=engine_receipt.product_code, product_version=engine_receipt.product_version).first()
        if engine_receipt.schedule_reference_id else None)
    if (application is None or schedule is None or schedule.term_months != application.requested_term_months
            or schedule.product_code != engine_receipt.product_code
            or schedule.product_version != engine_receipt.product_version):
        raise HTTPException(409, "Export requires a matching Business Engine proposed schedule for the submitted product and term")
    if (payload.product_code != engine_receipt.product_code
            or payload.product_version != engine_receipt.product_version
            or payload.product_sha256 != engine_receipt.product_sha256
            or payload.policy_reference != engine_receipt.policy_reference
            or payload.policy_version != engine_receipt.policy_version
            or payload.policy_sha256 != engine_receipt.policy_sha256
            or payload.calculation_reference != engine_receipt.calculation_reference
            or payload.calculation_version != engine_receipt.calculation_version
            or payload.calculation_sha256 != engine_receipt.output_sha256):
        raise HTTPException(409, "Export product/policy/calculation references or hashes do not match the Business Engine receipt")
    # Require that the confirmed Maker/Checker snapshot already contains the exact
    # bundle, schedule and Business Engine receipt; later external events require a new version.
    snap_bundles = {str(row.get("id")): row for row in version.snapshot_data.get("financial_input_bundles", [])}
    snap_schedules = {str(row.get("id")): row for row in version.snapshot_data.get("proposed_schedule_references", [])}
    snap_receipts = {str(row.get("id")): row for row in version.snapshot_data.get("business_engine_receipts", [])}
    if (str(input_bundle.id) not in snap_bundles
            or snap_bundles[str(input_bundle.id)].get("bundle_sha256") != input_bundle.bundle_sha256
            or str(schedule.id) not in snap_schedules
            or snap_schedules[str(schedule.id)].get("schedule_sha256") != schedule.schedule_sha256
            or str(engine_receipt.id) not in snap_receipts
            or snap_receipts[str(engine_receipt.id)].get("output_sha256") != engine_receipt.output_sha256):
        raise HTTPException(409, "Freeze a new Maker version after the matching Financial Engine receipt and schedule have been received")

    proposals = db.query(models.CaseOverrideRequest).filter_by(case_id=case_id, version_id=version.id).all()
    application_receipts = []
    for proposal in proposals:
        receipt = _validate_override_application_receipt(db, case_id, proposal)
        if receipt:
            application_receipts.append({
                "override_request_id": str(proposal.id),
                "external_application_reference": receipt.external_application_reference,
                "applied_proposal_sha256": receipt.applied_proposal_sha256,
                "applied_version_sha256": receipt.applied_version_sha256,
                "policy_reference": receipt.policy_reference, "policy_version": receipt.policy_version,
                "applied_at": receipt.applied_at.isoformat(),
                "attested_by": receipt.applied_by,
            })
    evidence_rows = []
    for doc in documents:
        from pathlib import Path as _Path
        stored = _Path(doc.stored_path)
        if not stored.is_file() or service.sha256_file(stored) != doc.sha256:
            raise HTTPException(409, f"Evidence file {doc.id} is missing or failed SHA-256 validation")
        evidence_rows.append({
            "document_id": str(doc.id), "filename": doc.original_filename, "mime_type": doc.mime_type,
            "file_size": doc.file_size, "sha256": doc.sha256, "document_type": doc.document_type,
            "evidence_status": doc.evidence_status, "processing_status": doc.processing_status,
        })
    manifest_entries = (db.query(models.EvidenceManifestEntry).filter_by(case_id=case_id)
                        .order_by(models.EvidenceManifestEntry.sequence_no).all())
    manifest_verification = verify_manifest_chain(manifest_entries)
    manifest_by_document = {str(entry.document_id): entry for entry in manifest_entries}
    if (not manifest_verification.get("valid") or len(manifest_entries) != len(documents)
            or any(not manifest_matches_document_metadata(manifest_by_document.get(str(doc.id)), doc)
                   for doc in documents)):
        raise HTTPException(409, "Evidence manifest chain is incomplete or does not match every document")
    audit_rows = (db.query(models.CaseAuditEntry).filter_by(case_id=case_id)
                  .order_by(models.CaseAuditEntry.sequence_no).all())
    audit_verification = verify_audit_chain(audit_rows)
    if not audit_verification.get("valid") or audit_verification.get("verified_entries", 0) < 1:
        raise HTTPException(409, "Case audit chain is empty or failed integrity verification")
    manifest = {
        "package_schema_version": "1.0", "package_kind": "DATA_AI_EVIDENCE_PACKAGE",
        "created_at": datetime.now(timezone.utc).isoformat(), "case_id": str(case_id),
        "bank_id": case.bank_id, "analysis_version_id": str(version.id),
        "analysis_version_no": version.version_no, "snapshot_sha256": version.snapshot_sha256,
        "applicant_snapshot_sha256": applicant_hash,
        "product_code": payload.product_code, "product_version": payload.product_version,
        "product_sha256": payload.product_sha256,
        "policy_reference": payload.policy_reference, "policy_version": payload.policy_version,
        "policy_sha256": payload.policy_sha256,
        "calculation_reference": payload.calculation_reference,
        "calculation_version": payload.calculation_version,
        "calculation_sha256": payload.calculation_sha256,
        "financial_engine_handoff": {
            "financial_input_bundle_id": str(input_bundle.id),
            "financial_input_bundle_sha256": input_bundle.bundle_sha256,
            "proposed_schedule_reference_id": str(schedule.id),
            "proposed_schedule_reference": schedule.schedule_reference,
            "proposed_schedule_sha256": schedule.schedule_sha256,
            "business_engine_receipt_id": str(engine_receipt.id),
            "business_engine_input_sha256": engine_receipt.input_bundle_sha256,
            "business_engine_output_sha256": engine_receipt.output_sha256,
            "scenario_references": engine_receipt.scenario_references,
            "result_status": engine_receipt.result_status,
        },
        "external_reference_verification_owner": "BACKEND_OR_BUSINESS_ENGINE",
        "evidence_document_count": len(evidence_rows),
        "evidence_manifest_head_sha256": manifest_verification.get("latest_entry_hash"),
        "audit_head_sha256": audit_verification.get("head_sha256"),
        "audit_verified_entries": audit_verification.get("verified_entries"),
        "external_override_application_receipts": application_receipts,
        "data_ai_scope": "EVIDENCE_AND_PROVENANCE_PACKAGE_ONLY_NOT_CREDIT_DECISION",
        "dsr_calculated_by_data_ai": False,
        "policy_evaluated_by_data_ai": False,
        "credit_decision_made": False,
    }
    package_bytes, final_manifest = build_export_zip(
        manifest=manifest, analysis_snapshot=version.snapshot_data, evidence_rows=evidence_rows)
    package_sha = sha256_bytes(package_bytes)
    package_id = uuid4()
    export_folder = settings.export_dir.resolve() / str(case_id)
    export_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        export_folder.chmod(0o700)
    except OSError:
        pass  # Platform may not expose POSIX permission semantics.
    package_path = export_folder / f"{package_id}.zip"
    tmp_path = package_path.with_suffix(".zip.tmp")
    try:
        tmp_path.write_bytes(package_bytes)
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        tmp_path.replace(package_path)
        row = models.CaseWorkflowExportPackage(
            id=package_id, case_id=case_id, version_id=version.id,
            package_kind="DATA_AI_EVIDENCE_PACKAGE", package_path=str(package_path),
            package_sha256=package_sha, package_manifest=final_manifest,
            snapshot_sha256=version.snapshot_sha256, requested_by=actor,
        )
        db.add(row)
        db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="WORKFLOW_EXPORT_PACKAGE_CREATED",
            entity_type="case_workflow_export_package", entity_id=str(package_id),
            details={"package_sha256": package_sha, "snapshot_sha256": version.snapshot_sha256,
                     "package_kind": "DATA_AI_EVIDENCE_PACKAGE"}))
        _enqueue_case_workflow_event(db, case, "EVIDENCE_PACKAGE_CREATED", {
            "reason_code": "DATA_AI_EVIDENCE_PACKAGE", "external_gate_reference": str(package_id)},
            idempotency_key=f"EXPORT_PACKAGE:{package_id}")
        db.commit()
    except Exception:
        db.rollback()
        tmp_path.unlink(missing_ok=True)
        package_path.unlink(missing_ok=True)
        raise
    return {"package_id": str(package_id), "case_id": str(case_id),
            "analysis_version_id": str(version.id), "package_sha256": package_sha,
            "snapshot_sha256": version.snapshot_sha256,
            "files": final_manifest.get("package_files", {}),
            "download_url": f"/api/v1/cases/{case_id}/workflow/export-packages/{package_id}/download",
            "package_kind": "DATA_AI_EVIDENCE_PACKAGE",
            "external_references_verified_by": "BACKEND_OR_BUSINESS_ENGINE",
            "credit_decision": False}


@app.get("/api/v1/cases/{case_id}/workflow/export-packages", tags=["workflow-integration"],
         dependencies=[Depends(require_internal_token)])
def list_case_workflow_export_packages(
    case_id: UUID, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER", "CHECKER"})
    rows = (db.query(models.CaseWorkflowExportPackage).filter_by(case_id=case_id)
            .order_by(models.CaseWorkflowExportPackage.created_at.desc()).all())
    return [{"id": str(r.id), "version_id": str(r.version_id), "package_kind": r.package_kind,
             "package_sha256": r.package_sha256, "snapshot_sha256": r.snapshot_sha256,
             "created_at": r.created_at.isoformat(), "requested_by": r.requested_by} for r in rows]


@app.get("/api/v1/cases/{case_id}/workflow/export-packages/{package_id}/download",
         tags=["workflow-integration"], dependencies=[Depends(require_internal_token)])
def download_case_workflow_export_package(
    case_id: UUID, package_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER", "CHECKER"})
    row = db.query(models.CaseWorkflowExportPackage).filter_by(id=package_id, case_id=case_id).first()
    if not row:
        raise HTTPException(404, "Export package not found")
    from pathlib import Path as _Path
    path = _Path(row.package_path).resolve()
    try:
        path.relative_to(settings.export_dir.resolve())
    except ValueError as exc:
        raise HTTPException(409, "Stored export path is outside the configured export directory") from exc
    if not path.is_file() or service.sha256_file(path) != row.package_sha256:
        raise HTTPException(409, "Stored export package is missing or failed SHA-256 validation")
    return FileResponse(path, media_type="application/zip", filename=f"DATA_AI_EVIDENCE_{case_id}_{package_id}.zip")



def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(str(left), str(right))


# Publish the optional idempotency contract on mutation operations without
# changing existing request/response schemas or requiring legacy clients to opt in.
_original_openapi = app.openapi

def _openapi_with_idempotency():
    if app.openapi_schema:
        return app.openapi_schema
    schema = _original_openapi()
    for path, methods in schema.get("paths", {}).items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in methods.items():
            if method.lower() not in {"post", "put", "patch", "delete"}:
                continue
            parameters = operation.setdefault("parameters", [])
            if not any(p.get("name", "").lower() == "idempotency-key" and p.get("in") == "header" for p in parameters):
                parameters.append({
                    "name": "Idempotency-Key", "in": "header", "required": False,
                    "description": "Stable key for safe replay of this mutation. Reuse the same key only for the same logical command and identical request.",
                    "schema": {"type": "string", "minLength": 8, "maxLength": 128,
                               "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"},
                })
            operation.setdefault("responses", {}).setdefault("409", {
                "description": "Idempotency key conflict, request in progress, or outcome requires reconciliation"
            })
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = _openapi_with_idempotency

# ---- V10.0 DATA-AI workflow completion: scope, declarations and Finance handoff ----

def _v10_exact_role(roles: set[str], expected: str) -> None:
    if roles != {expected}:
        raise HTTPException(403, f"A dedicated {expected} service identity is required")


def _v10_assert_case_mutable(db: Session, case_id: UUID) -> None:
    latest = get_latest_case_version(db, case_id)
    if latest is None:
        return
    state, _ = get_version_state(db, latest.id)
    if state in {"FROZEN", "CHECKER_CONFIRMED"}:
        reopen = db.query(models.CaseWorkflowReopen).filter_by(case_id=case_id, status="OPEN").first()
        if reopen is None:
            raise HTTPException(409, "Case input is frozen; use the governed reopen/resubmission workflow before changing data")


def _v10_get_trusted_evidence_docs(db: Session, case_id: UUID, document_ids: list[UUID]) -> list[models.Document]:
    docs = []
    for document_id in sorted(set(document_ids), key=str):
        doc = db.query(models.Document).filter_by(id=document_id, case_id=case_id).first()
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(422, f"Evidence document {document_id} does not belong to this case")
        if doc.malware_scan_status != "CLEAN" or doc.processing_status != "COMPLETED":
            raise HTTPException(409, f"Evidence document {document_id} is not scanned CLEAN and processed")
        scan = _latest_trusted_document_scan(db, doc)
        manifest = db.query(models.EvidenceManifestEntry).filter_by(
            case_id=case_id, document_id=doc.id, sha256=doc.sha256).first()
        if scan is None or manifest is None:
            raise HTTPException(409, f"Evidence document {document_id} has no matching scan attestation or manifest entry")
        docs.append(doc)
    return docs


def _v10_revision_out(row: models.CaseInputDeclarationRevision) -> dict:
    return {"id": str(row.id), "case_id": str(row.case_id), "section_code": row.section_code,
            "revision_no": row.revision_no, "payload_sha256": row.payload_sha256,
            "supersedes_revision_id": str(row.supersedes_revision_id) if row.supersedes_revision_id else None,
            "submitted_by": row.submitted_by, "source_channel": row.source_channel,
            "submitted_at": row.submitted_at.isoformat()}


@app.post("/api/v1/cases/{case_id}/scope-consent-attestations", status_code=201,
          tags=["data-ai-intake"], dependencies=[Depends(require_internal_token)])
def create_scope_consent_attestation(
    case_id: UUID, payload: ScopeConsentAttestationIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    """Persist a Backend/SSO decision mirror; legal consent and DMN remain external."""
    case, actor, roles = _workflow_case_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"BACKEND_SCOPE_ATTESTOR"})
    _v10_exact_role(roles, "BACKEND_SCOPE_ATTESTOR")
    if payload.attested_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(422, "attested_at cannot be materially in the future")
    attestation_data = {
        "case_id": str(case_id), "bank_id": case.bank_id, "scope_code": payload.scope_code,
        "scope_status": payload.scope_status, "consent_status": payload.consent_status,
        "consent_reference": payload.consent_reference, "purpose_code": payload.purpose_code,
        "notice_version": payload.notice_version,
        "backend_decision_reference": payload.backend_decision_reference,
        "attested_by": actor, "attested_at": payload.attested_at.isoformat(),
    }
    existing = (db.query(models.CaseScopeConsentAttestation)
                .filter_by(case_id=case_id, backend_decision_reference=payload.backend_decision_reference).first())
    if existing is not None:
        if existing.attestation_sha256 != sha256_json(attestation_data):
            raise HTTPException(409, "Backend decision reference was already used with different attestation content")
        return {"id": str(existing.id), "case_id": str(existing.case_id),
                "scope_status": existing.scope_status, "consent_status": existing.consent_status,
                "attestation_sha256": existing.attestation_sha256,
                "attested_at": existing.attested_at.isoformat(),
                "idempotent_replay": True,
                "legal_consent_validation_owner": "BACKEND_SSO_NOT_DATA_AI"}
    row = models.CaseScopeConsentAttestation(
        id=uuid4(), case_id=case_id, bank_id=case.bank_id, scope_code=payload.scope_code,
        scope_status=payload.scope_status, consent_status=payload.consent_status,
        consent_reference=payload.consent_reference, purpose_code=payload.purpose_code,
        notice_version=payload.notice_version, backend_decision_reference=payload.backend_decision_reference,
        attestation_sha256=sha256_json(attestation_data), attested_by=actor,
        attested_at=payload.attested_at,
    )
    db.add(row)
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="SCOPE_CONSENT_ATTESTATION_RECEIVED",
        entity_type="case_scope_consent_attestation", entity_id=str(row.id),
        details={"scope_status": payload.scope_status, "consent_status": payload.consent_status,
                 "attestation_sha256": row.attestation_sha256,
                 "authority": "BACKEND_SSO_AUTHORITATIVE"}))
    _enqueue_case_workflow_event(db, case, "SCOPE_CONSENT_ATTESTATION_RECEIVED", {
        "reason_code": f"{payload.scope_status}:{payload.consent_status}",
        "external_gate_reference": str(row.id)}, idempotency_key=f"SCOPE_ATTESTATION:{row.id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Scope/consent attestation could not be recorded") from exc
    db.refresh(row)
    return {"id": str(row.id), "case_id": str(row.case_id), "scope_status": row.scope_status,
            "consent_status": row.consent_status, "attestation_sha256": row.attestation_sha256,
            "attested_at": row.attested_at.isoformat(),
            "legal_consent_validation_owner": "BACKEND_SSO_NOT_DATA_AI"}


@app.post("/api/v1/cases/{case_id}/declarations/{section_code}/revisions", status_code=201,
          tags=["data-ai-intake"], dependencies=[Depends(require_internal_token)])
def create_case_input_declaration_revision(
    case_id: UUID, section_code: str, payload: InputDeclarationRevisionIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    """Ingest an immutable Backend declaration revision; never fills missing values."""
    case, actor, roles = _workflow_case_context(
        case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"BACKEND_DATA_INGESTOR"})
    _v10_exact_role(roles, "BACKEND_DATA_INGESTOR")
    if case.customer_id is None:
        raise HTTPException(409, "Case must be linked to a Backend customer before declaration intake")
    attestation = _v10_latest_attestation(db, case_id)
    if attestation is None or attestation.scope_status != "IN_SCOPE" or attestation.consent_status != "GRANTED":
        raise HTTPException(409, "Backend must attest in-scope and granted consent before declaration intake")
    _v10_assert_case_mutable(db, case_id)
    normalized_section = section_code.strip().upper()
    try:
        normalized_payload = _v10_validate_declaration_payload(normalized_section, payload.payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    evidence_ids = list(payload.evidence_document_ids)
    if normalized_section == "SALARY_ACCOUNTS":
        for account in normalized_payload["accounts"]:
            account["account_ref_id"] = str(uuid4())
        account_evidence_ids = [UUID(item["evidence_document_id"]) for item in normalized_payload["accounts"]]
        if not set(account_evidence_ids).issubset(set(evidence_ids)):
            raise HTTPException(422, "Every salary account statement must also appear in evidence_document_ids")
        evidence_ids.extend(account_evidence_ids)
    docs = _v10_get_trusted_evidence_docs(db, case_id, evidence_ids) if evidence_ids else []
    if normalized_section == "SALARY_ACCOUNTS":
        for account in normalized_payload["accounts"]:
            evidence_doc = next((d for d in docs if str(d.id) == account["evidence_document_id"]), None)
            if evidence_doc is None or evidence_doc.document_type != "BANK_STATEMENT":
                raise HTTPException(422, "Salary account evidence_document_id must reference a processed BANK_STATEMENT document")

    if payload.client_request_id is not None:
        existing = (db.query(models.CaseInputDeclarationRevision)
                    .filter_by(case_id=case_id, client_request_id=payload.client_request_id).first())
        if existing is not None:
            def _without_account_ref(value):
                data = json.loads(json.dumps(value))
                if normalized_section == "SALARY_ACCOUNTS":
                    for account in data.get("accounts", []):
                        account.pop("account_ref_id", None)
                return data
            existing_links = (db.query(models.CaseInputDeclarationEvidenceLink)
                              .filter_by(case_id=case_id, declaration_revision_id=existing.id)
                              .order_by(models.CaseInputDeclarationEvidenceLink.document_id).all())
            requested_links = sorted((str(d.id), d.sha256) for d in docs)
            stored_links = sorted((str(link.document_id), link.document_sha256) for link in existing_links)
            if (existing.section_code != normalized_section
                    or _without_account_ref(existing.payload) != _without_account_ref(normalized_payload)
                    or requested_links != stored_links):
                raise HTTPException(409, "client_request_id was already used with different declaration or evidence")
            return {**_v10_revision_out(existing), "idempotent_replay": True}

    latest = (db.query(models.CaseInputDeclarationRevision)
              .filter_by(case_id=case_id, section_code=normalized_section)
              .order_by(models.CaseInputDeclarationRevision.revision_no.desc()).first())
    revision_no = latest.revision_no + 1 if latest else 1
    digest = sha256_json(normalized_payload)
    row = models.CaseInputDeclarationRevision(
        id=uuid4(), case_id=case_id, customer_id=case.customer_id,
        section_code=normalized_section, revision_no=revision_no,
        payload=normalized_payload, payload_sha256=digest, submitted_by=actor,
        source_channel="BACKEND", client_request_id=payload.client_request_id,
        supersedes_revision_id=latest.id if latest else None,
    )
    db.add(row)
    db.flush()
    for doc in docs:
        db.add(models.CaseInputDeclarationEvidenceLink(
            id=uuid4(), case_id=case_id, declaration_revision_id=row.id,
            document_id=doc.id, document_sha256=doc.sha256,
            link_purpose="SALARY_STATEMENT" if normalized_section == "SALARY_ACCOUNTS" else "SUPPORTING_EVIDENCE"))
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="CASE_INPUT_DECLARATION_REVISION_RECEIVED",
        entity_type="case_input_declaration_revision", entity_id=str(row.id),
        details={"section_code": normalized_section, "revision_no": revision_no,
                 "payload_sha256": digest, "evidence_document_count": len(docs)}))
    _enqueue_case_workflow_event(db, case, "APPLICANT_DECLARATION_REVISION_RECEIVED", {
        "declaration_revision_id": str(row.id), "section_code": normalized_section,
        "revision_no": revision_no}, idempotency_key=f"DECLARATION_REVISION:{row.id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent declaration revision or same-case evidence link conflict") from exc
    db.refresh(row)
    return _v10_revision_out(row)


@app.get("/api/v1/cases/{case_id}/declarations", tags=["data-ai-intake"],
         dependencies=[Depends(require_internal_token)])
def list_case_input_declarations(
    case_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                           {"BACKEND_DATA_INGESTOR", "MAKER", "CHECKER", "DATA_AI_SERVICE"})
    rows = (db.query(models.CaseInputDeclarationRevision).filter_by(case_id=case_id)
            .order_by(models.CaseInputDeclarationRevision.section_code,
                      models.CaseInputDeclarationRevision.revision_no.desc()).all())
    return [_v10_revision_out(row) for row in rows]


@app.post("/api/v1/cases/{case_id}/input-reviews", status_code=201,
          tags=["data-ai-input-review"], dependencies=[Depends(require_internal_token)])
def create_case_input_review(
    case_id: UUID, payload: CaseInputReviewIn, request: Request, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"MAKER"})
    require_governance_role(actor, roles, "MAKER")
    _v10_assert_case_mutable(db, case_id)
    target = None
    declaration_revision_id = None
    required_source_document_ids: set[UUID] = set()
    if payload.target_type == "DECLARATION_REVISION":
        target = db.query(models.CaseInputDeclarationRevision).filter_by(id=payload.target_id, case_id=case_id).first()
        if target is None:
            raise HTTPException(404, "Declaration revision not found in this case")
        newest = (db.query(models.CaseInputDeclarationRevision).filter_by(case_id=case_id, section_code=target.section_code)
                  .order_by(models.CaseInputDeclarationRevision.revision_no.desc()).first())
        if newest is None or newest.id != target.id:
            raise HTTPException(409, "Only the latest declaration revision can receive a Maker decision")
        declaration_revision_id = target.id
        if target.section_code == "SALARY_ACCOUNTS" and payload.decision_code == "CONFIRMED":
            required_statement_ids = {str(item.get("evidence_document_id"))
                                      for item in target.payload.get("accounts", [])
                                      if item.get("evidence_document_id")}
            submitted_statement_ids = {str(item) for item in payload.evidence_document_ids}
            if not required_statement_ids or not required_statement_ids.issubset(submitted_statement_ids):
                raise HTTPException(422, "Maker confirmation of salary account ownership/period must cite every declared bank statement")
    elif payload.target_type == "EXTRACTED_FIELD":
        target = (db.query(models.ExtractedField).join(models.Document, models.ExtractedField.document_id == models.Document.id)
                  .filter(models.ExtractedField.id == payload.target_id, models.Document.case_id == case_id).first())
        if target is None:
            raise HTTPException(404, "Extracted field not found in this case")
        if target.document_id:
            required_source_document_ids.add(target.document_id)
        target.review_status = {"CONFIRMED": "APPROVED", "RETURNED": "NEEDS_REVIEW",
                                "UNABLE_TO_VERIFY": "NEEDS_REVIEW", "REJECTED": "REJECTED"}[payload.decision_code]
    elif payload.target_type == "PAYROLL_EVIDENCE":
        target = db.query(models.PayrollEvidence).filter_by(id=payload.target_id, case_id=case_id).first()
        if target is None:
            raise HTTPException(404, "Payroll evidence not found in this case")
        if target.document_id:
            required_source_document_ids.add(target.document_id)
        else:
            raise HTTPException(409, "Payroll evidence has no source document; Maker cannot confirm an unanchored candidate")
        target.evidence_status = {"CONFIRMED": "MAKER_CONFIRMED", "RETURNED": "NEEDS_REVIEW",
                                  "UNABLE_TO_VERIFY": "UNABLE_TO_VERIFY", "REJECTED": "REJECTED"}[payload.decision_code]
        target.reviewed_by = actor
        target.reviewed_at = datetime.now(timezone.utc)
    elif payload.target_type == "EARNING_MATCH":
        target = db.query(models.EarningMatchCandidate).filter_by(id=payload.target_id, case_id=case_id).first()
        if target is None:
            raise HTTPException(404, "Payroll match candidate not found in this case")
        payroll_source = db.query(models.PayrollEvidence).filter_by(
            id=target.payroll_evidence_id, case_id=case_id).first()
        transaction_source = db.query(models.Transaction).filter_by(
            id=target.transaction_id, case_id=case_id).first()
        if payroll_source is None or transaction_source is None or not payroll_source.document_id or not transaction_source.document_id:
            raise HTTPException(409, "Payroll-to-bank match is missing a same-case source document")
        required_source_document_ids.update({payroll_source.document_id, transaction_source.document_id})
        target.review_status = {"CONFIRMED": "MAKER_CONFIRMED", "RETURNED": "RETURNED",
                                "UNABLE_TO_VERIFY": "UNABLE_TO_VERIFY", "REJECTED": "MAKER_REJECTED"}[payload.decision_code]
    elif payload.target_type == "TRANSACTION":
        target = db.query(models.Transaction).filter_by(id=payload.target_id, case_id=case_id).first()
        if target is None:
            raise HTTPException(404, "Transaction not found in this case")
        if not target.document_id:
            raise HTTPException(409, "Transaction has no source statement document; Maker cannot confirm an unanchored row")
        required_source_document_ids.add(target.document_id)
        target.review_status = {"CONFIRMED": "MAKER_REVIEWED", "RETURNED": "NEEDS_REVIEW",
                                "UNABLE_TO_VERIFY": "UNABLE_TO_VERIFY", "REJECTED": "MAKER_REJECTED"}[payload.decision_code]
        # Intentionally do not set is_income_eligible; that is a separate policy authority.
    elif payload.target_type == "INCOME_LEDGER":
        target = db.query(models.IncomeLedgerMonth).filter_by(id=payload.target_id, case_id=case_id).first()
        if target is None:
            raise HTTPException(404, "Income ledger month not found in this case")
        month_key = target.period_month.strftime("%Y-%m")
        next_month = (target.period_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        # Payroll rows may be dated by the actual payment date or, when that is
        # unavailable, by the documented pay-period end. Keep the same month
        # semantics as readiness without inventing a date or amount.
        related_payroll = db.query(models.PayrollEvidence).filter(
            models.PayrollEvidence.case_id == case_id,
            or_(
                and_(models.PayrollEvidence.payment_date >= target.period_month,
                     models.PayrollEvidence.payment_date < next_month),
                and_(models.PayrollEvidence.payment_date.is_(None),
                     models.PayrollEvidence.pay_period_end >= target.period_month,
                     models.PayrollEvidence.pay_period_end < next_month),
            ),
        ).all()
        related_transactions = db.query(models.Transaction).filter(
            models.Transaction.case_id == case_id,
            models.Transaction.transaction_date.like(f"{month_key}%"),
        ).all()
        source_ids = {row.document_id for row in related_payroll if row.document_id}
        source_ids.update(row.document_id for row in related_transactions if row.document_id)
        if not source_ids:
            raise HTTPException(409, "Income ledger month has no linked payroll or statement source documents")
        required_source_document_ids.update(source_ids)
        target.month_status = {"CONFIRMED": "MAKER_REVIEWED", "RETURNED": "NEEDS_REVIEW",
                               "UNABLE_TO_VERIFY": "UNABLE_TO_VERIFY", "REJECTED": "REJECTED"}[payload.decision_code]
        target.reviewed_by = actor
        target.reviewed_at = datetime.now(timezone.utc)
        # accepted_amount remains NULL; Maker's evidence review is not eligible-income approval.

    docs = _v10_get_trusted_evidence_docs(db, case_id, payload.evidence_document_ids) if payload.evidence_document_ids else []
    submitted_document_ids = {d.id for d in docs}
    if not required_source_document_ids.issubset(submitted_document_ids):
        raise HTTPException(422, "Maker review must cite every source document linked to the reviewed OCR, payroll, transaction or ledger target")
    evidence_refs = [{"document_id": str(d.id), "sha256": d.sha256} for d in docs]
    row = models.CaseInputReviewDecision(
        id=uuid4(), case_id=case_id, declaration_revision_id=declaration_revision_id,
        target_type=payload.target_type, target_id=payload.target_id,
        decision_code=payload.decision_code, reason=payload.reason, evidence_refs=evidence_refs,
        reviewed_by=actor, reviewer_role="MAKER")
    db.add(row)
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="CASE_INPUT_MAKER_REVIEWED",
        entity_type=payload.target_type.lower(), entity_id=str(payload.target_id),
        details={"decision_code": payload.decision_code, "review_id": str(row.id),
                 "evidence_document_count": len(docs)}))
    _enqueue_case_workflow_event(db, case, "MAKER_INPUT_REVIEW_RECORDED", {
        "external_gate_reference": str(row.id), "reason_code": payload.decision_code,
        "section_code": payload.target_type},
        idempotency_key=f"INPUT_REVIEW:{row.id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Maker input review could not be persisted") from exc
    db.refresh(row)
    return {"id": str(row.id), "case_id": str(row.case_id), "target_type": row.target_type,
            "target_id": str(row.target_id), "decision_code": row.decision_code,
            "reviewed_by": row.reviewed_by, "reviewer_role": row.reviewer_role,
            "created_at": row.created_at.isoformat(),
            "credit_eligibility_changed": False, "financial_calculation_performed": False}


@app.get("/api/v1/cases/{case_id}/data-readiness", tags=["data-ai-readiness"],
         dependencies=[Depends(require_internal_token)])
def get_case_data_readiness(
    case_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, _, _ = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                                         {"MAKER", "CHECKER", "DATA_AI_SERVICE", "BACKEND_DATA_INGESTOR", "BUSINESS_ENGINE"})
    return _v10_evaluate_data_readiness(db, case)


@app.post("/api/v1/cases/{case_id}/financial-input-bundles", status_code=201,
          tags=["financial-engine-handoff"], dependencies=[Depends(require_internal_token)])
def create_financial_input_bundle(
    case_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"DATA_AI_SERVICE"})
    _v10_exact_role(roles, "DATA_AI_SERVICE")
    case = db.query(models.Case).filter_by(id=case_id).populate_existing().with_for_update().first()
    if not case:
        raise HTTPException(404, "Case not found")
    _v10_assert_case_mutable(db, case_id)
    readiness = _v10_evaluate_data_readiness(db, case)
    bundle_payload = _v10_build_financial_input_payload(db, case, readiness)
    digest = sha256_json(bundle_payload)
    existing_bundle = (db.query(models.CaseFinancialInputBundle)
                       .filter_by(case_id=case_id, bundle_sha256=digest).first())
    if existing_bundle is not None:
        return {"bundle_id": str(existing_bundle.id), "bundle_no": existing_bundle.bundle_no,
                "readiness_status": existing_bundle.readiness_status,
                "bundle_sha256": existing_bundle.bundle_sha256,
                "download_contract": "BUSINESS_ENGINE_SERVICE_READ_ONLY",
                "calculations_performed_by_data_ai": False, "idempotent_replay": True}
    last = (db.query(models.CaseFinancialInputBundle.bundle_no).filter_by(case_id=case_id)
            .order_by(models.CaseFinancialInputBundle.bundle_no.desc()).first())
    row = models.CaseFinancialInputBundle(
        id=uuid4(), case_id=case_id, bundle_no=(last[0] + 1 if last else 1),
        readiness_status=readiness["status"], readiness=readiness,
        bundle_data=bundle_payload, bundle_sha256=digest, created_by=actor)
    db.add(row)
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="FINANCIAL_INPUT_BUNDLE_CREATED",
        entity_type="case_financial_input_bundle", entity_id=str(row.id),
        details={"bundle_no": row.bundle_no, "bundle_sha256": digest,
                 "contract_version": "DATA_AI_FINANCIAL_INPUT_V1"}))
    _enqueue_case_workflow_event(db, case, "FINANCIAL_INPUT_BUNDLE_READY", {
        "financial_input_bundle_id": str(row.id), "readiness_status": row.readiness_status},
        idempotency_key=f"FINANCIAL_INPUT_BUNDLE:{row.id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent Financial Engine bundle sequence conflict") from exc
    db.refresh(row)
    return {"bundle_id": str(row.id), "bundle_no": row.bundle_no,
            "readiness_status": row.readiness_status, "bundle_sha256": row.bundle_sha256,
            "download_contract": "BUSINESS_ENGINE_SERVICE_READ_ONLY",
            "calculations_performed_by_data_ai": False}


@app.get("/api/v1/cases/{case_id}/financial-input-bundles/{bundle_id}", tags=["financial-engine-handoff"],
         dependencies=[Depends(require_internal_token)])
def get_financial_input_bundle_for_business_engine(
    case_id: UUID, bundle_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"BUSINESS_ENGINE"})
    _, roles, _ = trusted_actor_context(x_actor_id, x_actor_roles, x_bank_id, require_bank=True)
    _v10_exact_role(roles, "BUSINESS_ENGINE")
    row = db.query(models.CaseFinancialInputBundle).filter_by(id=bundle_id, case_id=case_id).first()
    if row is None:
        raise HTTPException(404, "Financial input bundle not found")
    if row.readiness_status != "READY_FOR_BUSINESS_ENGINE" or sha256_json(row.bundle_data) != row.bundle_sha256:
        raise HTTPException(409, "Financial input bundle is not ready or failed SHA-256 verification")
    return {"bundle_id": str(row.id), "case_id": str(row.case_id), "bundle_no": row.bundle_no,
            "bundle_sha256": row.bundle_sha256, "bundle_data": row.bundle_data,
            "authority_boundary": "BUSINESS_ENGINE_OWNS_ALL_FINANCIAL_CALCULATIONS_AND_POLICY"}


@app.post("/api/v1/cases/{case_id}/proposed-schedule-references", status_code=201,
          tags=["financial-engine-handoff"], dependencies=[Depends(require_internal_token)])
def create_proposed_schedule_reference(
    case_id: UUID, payload: ProposedScheduleReferenceIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"BUSINESS_ENGINE"})
    _v10_exact_role(roles, "BUSINESS_ENGINE")
    _v10_assert_case_mutable(db, case_id)
    bundle = db.query(models.CaseFinancialInputBundle).filter_by(id=payload.bundle_id, case_id=case_id).first()
    if bundle is None or bundle.readiness_status != "READY_FOR_BUSINESS_ENGINE" or sha256_json(bundle.bundle_data) != bundle.bundle_sha256:
        raise HTTPException(409, "Schedule reference must bind to a verified ready Financial Engine input bundle")
    application = db.query(models.LoanApplication).filter_by(case_id=case_id).first()
    if application is None or application.product_code != payload.product_code or application.requested_term_months != payload.term_months:
        raise HTTPException(409, "Schedule product/term metadata does not match the submitted loan request")
    existing_schedule = db.query(models.CaseProposedScheduleReference).filter_by(
        schedule_reference=payload.schedule_reference).first()
    if existing_schedule is not None:
        if (existing_schedule.case_id != case_id or existing_schedule.bundle_id != bundle.id
                or existing_schedule.schedule_sha256 != payload.schedule_sha256
                or existing_schedule.product_code != payload.product_code
                or existing_schedule.product_version != payload.product_version
                or existing_schedule.term_months != payload.term_months):
            raise HTTPException(409, "Schedule reference was already used with different bundle or schedule content")
        return {"id": str(existing_schedule.id), "bundle_id": str(existing_schedule.bundle_id),
                "schedule_reference": existing_schedule.schedule_reference,
                "schedule_sha256": existing_schedule.schedule_sha256,
                "product_code": existing_schedule.product_code, "product_version": existing_schedule.product_version,
                "term_months": existing_schedule.term_months, "provided_by": existing_schedule.provided_by,
                "repayment_schedule_calculated_by_data_ai": False, "idempotent_replay": True}
    row = models.CaseProposedScheduleReference(
        id=uuid4(), case_id=case_id, bundle_id=bundle.id,
        schedule_reference=payload.schedule_reference, schedule_sha256=payload.schedule_sha256,
        product_code=payload.product_code, product_version=payload.product_version,
        term_months=payload.term_months, currency=payload.currency, provided_by=actor)
    db.add(row)
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="PROPOSED_SCHEDULE_REFERENCE_RECEIVED",
        entity_type="case_proposed_schedule_reference", entity_id=str(row.id),
        details={"bundle_id": str(bundle.id), "schedule_sha256": row.schedule_sha256,
                 "product_code": row.product_code, "product_version": row.product_version,
                 "calculation_owner": "BUSINESS_ENGINE"}))
    _enqueue_case_workflow_event(db, case, "PROPOSED_SCHEDULE_REFERENCE_RECEIVED", {
        "external_gate_reference": str(row.id), "reason_code": "SCHEDULE_REFERENCE_RECEIVED"},
        idempotency_key=f"SCHEDULE_REFERENCE:{row.id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Schedule reference already exists or failed case/bundle constraints") from exc
    db.refresh(row)
    return {"id": str(row.id), "bundle_id": str(row.bundle_id),
            "schedule_reference": row.schedule_reference, "schedule_sha256": row.schedule_sha256,
            "product_code": row.product_code, "product_version": row.product_version,
            "term_months": row.term_months, "provided_by": row.provided_by,
            "repayment_schedule_calculated_by_data_ai": False}


@app.post("/api/v1/cases/{case_id}/business-engine-receipts", status_code=201,
          tags=["financial-engine-handoff"], dependencies=[Depends(require_internal_token)])
def receive_business_engine_receipt(
    case_id: UUID, payload: BusinessEngineReceiptIn, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    case, actor, roles = _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id, {"BUSINESS_ENGINE"})
    _v10_exact_role(roles, "BUSINESS_ENGINE")
    _v10_assert_case_mutable(db, case_id)
    bundle = db.query(models.CaseFinancialInputBundle).filter_by(id=payload.bundle_id, case_id=case_id).first()
    if bundle is None or bundle.readiness_status != "READY_FOR_BUSINESS_ENGINE" or sha256_json(bundle.bundle_data) != bundle.bundle_sha256:
        raise HTTPException(409, "Business Engine receipt references an unknown or tampered input bundle")
    if payload.input_bundle_sha256 != bundle.bundle_sha256:
        raise HTTPException(409, "Business Engine receipt input hash does not match the consumed DATA-AI bundle")
    if payload.received_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(422, "Business Engine receipt received_at cannot be materially in the future")
    application = db.query(models.LoanApplication).filter_by(case_id=case_id).first()
    schedule_query = db.query(models.CaseProposedScheduleReference).filter_by(
        id=payload.schedule_reference_id, case_id=case_id, bundle_id=bundle.id,
        product_code=payload.product_code, product_version=payload.product_version)
    if application is not None:
        schedule_query = schedule_query.filter_by(term_months=application.requested_term_months)
    schedule = schedule_query.first() if payload.schedule_reference_id else None
    if payload.schedule_reference_id is not None and schedule is None:
        raise HTTPException(409, "Business Engine receipt schedule_reference_id does not match the same-case bundle, product and requested term")
    if payload.result_status == "COMPLETED" and (schedule is None or application is None):
        raise HTTPException(409, "Completed calculation receipt requires a schedule reference matching the submitted product and term")
    if payload.result_status == "COMPLETED" and payload.scenario_references.keys() != {"BASELINE", "STRESS_1", "STRESS_2"}:
        raise HTTPException(422, "Completed receipt must contain the baseline and two stress scenario references")
    existing_receipt = db.query(models.CaseBusinessEngineReceipt).filter_by(
        calculation_reference=payload.calculation_reference).first()
    if existing_receipt is not None:
        same = (existing_receipt.case_id == case_id and existing_receipt.bundle_id == bundle.id
                and existing_receipt.schedule_reference_id == payload.schedule_reference_id
                and existing_receipt.input_bundle_sha256 == payload.input_bundle_sha256
                and existing_receipt.calculation_version == payload.calculation_version
                and existing_receipt.policy_reference == payload.policy_reference
                and existing_receipt.policy_version == payload.policy_version
                and existing_receipt.product_code == payload.product_code
                and existing_receipt.product_version == payload.product_version
                and existing_receipt.product_sha256 == payload.product_sha256
                and existing_receipt.policy_sha256 == payload.policy_sha256
                and existing_receipt.result_status == payload.result_status
                and existing_receipt.scenario_references == payload.scenario_references
                and existing_receipt.output_sha256 == payload.output_sha256)
        if not same:
            raise HTTPException(409, "Calculation reference was already used with a different receipt payload")
        return {"id": str(existing_receipt.id), "case_id": str(existing_receipt.case_id),
                "bundle_id": str(existing_receipt.bundle_id),
                "schedule_reference_id": str(existing_receipt.schedule_reference_id) if existing_receipt.schedule_reference_id else None,
                "calculation_reference": existing_receipt.calculation_reference,
                "calculation_version": existing_receipt.calculation_version,
                "policy_reference": existing_receipt.policy_reference, "policy_version": existing_receipt.policy_version,
                "product_code": existing_receipt.product_code, "product_version": existing_receipt.product_version,
                "product_sha256": existing_receipt.product_sha256, "policy_sha256": existing_receipt.policy_sha256,
                "result_status": existing_receipt.result_status,
                "scenario_references": existing_receipt.scenario_references,
                "output_sha256": existing_receipt.output_sha256, "idempotent_replay": True,
                "credit_decision_made_by_data_ai": False}
    row = models.CaseBusinessEngineReceipt(
        id=uuid4(), case_id=case_id, bundle_id=bundle.id,
        schedule_reference_id=schedule.id if schedule else None,
        input_bundle_sha256=payload.input_bundle_sha256,
        calculation_reference=payload.calculation_reference,
        calculation_version=payload.calculation_version,
        policy_reference=payload.policy_reference, policy_version=payload.policy_version,
        product_code=payload.product_code, product_version=payload.product_version,
        product_sha256=payload.product_sha256, policy_sha256=payload.policy_sha256,
        result_status=payload.result_status, scenario_references=payload.scenario_references,
        output_sha256=payload.output_sha256, received_by=actor, received_at=payload.received_at)
    db.add(row)
    db.add(models.AuditEvent(case_id=case_id, actor=actor[:100], action="BUSINESS_ENGINE_RECEIPT_RECEIVED",
        entity_type="case_business_engine_receipt", entity_id=str(row.id),
        details={"bundle_id": str(bundle.id), "calculation_reference": row.calculation_reference,
                 "policy_reference": row.policy_reference, "policy_version": row.policy_version,
                 "result_status": row.result_status, "output_sha256": row.output_sha256}))
    _enqueue_case_workflow_event(db, case, "BUSINESS_ENGINE_RECEIPT_RECEIVED", {
        "business_engine_receipt_id": str(row.id), "financial_input_bundle_id": str(bundle.id),
        "readiness_status": row.result_status}, idempotency_key=f"BUSINESS_ENGINE_RECEIPT:{row.id}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Duplicate calculation reference or Business Engine receipt constraint conflict") from exc
    db.refresh(row)
    return {"id": str(row.id), "case_id": str(row.case_id), "bundle_id": str(row.bundle_id),
            "schedule_reference_id": str(row.schedule_reference_id) if row.schedule_reference_id else None,
            "calculation_reference": row.calculation_reference, "calculation_version": row.calculation_version,
            "policy_reference": row.policy_reference, "policy_version": row.policy_version,
            "product_code": row.product_code, "product_version": row.product_version,
            "product_sha256": row.product_sha256, "policy_sha256": row.policy_sha256,
            "result_status": row.result_status, "scenario_references": row.scenario_references,
            "output_sha256": row.output_sha256, "credit_decision_made_by_data_ai": False}


@app.get("/api/v1/cases/{case_id}/business-engine-receipts", tags=["financial-engine-handoff"],
         dependencies=[Depends(require_internal_token)])
def list_business_engine_receipts(
    case_id: UUID, db: Session = Depends(get_db),
    x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    _workflow_case_context(case_id, db, x_actor_id, x_actor_roles, x_bank_id,
                           {"MAKER", "CHECKER", "BUSINESS_ENGINE", "DATA_AI_SERVICE"})
    rows = (db.query(models.CaseBusinessEngineReceipt).filter_by(case_id=case_id)
            .order_by(models.CaseBusinessEngineReceipt.received_at.desc()).all())
    return [{"id": str(r.id), "bundle_id": str(r.bundle_id),
             "schedule_reference_id": str(r.schedule_reference_id) if r.schedule_reference_id else None,
             "calculation_reference": r.calculation_reference,
             "calculation_version": r.calculation_version, "policy_reference": r.policy_reference,
             "policy_version": r.policy_version, "product_code": r.product_code,
             "product_version": r.product_version, "product_sha256": r.product_sha256,
             "policy_sha256": r.policy_sha256, "result_status": r.result_status,
             "scenario_references": r.scenario_references, "output_sha256": r.output_sha256,
             "received_at": r.received_at.isoformat()} for r in rows]
