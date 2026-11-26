import csv, hashlib, shutil, uuid, re, json
import io
import unicodedata
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from app.config import settings
from app import models
from app.ocr import extract_words
from app.classifier import classify_transaction
from app.normalizer import parse_vnd, normalize_date
from app.document_intelligence import (
    classify_document, extract_labeled_fields, PIPELINE_VERSION,
    FIELD_CATALOG_VERSION, LAYOUT_CATALOG_VERSION,
)
from app.evidence_reconciliation import (
    calculate_manifest_entry_hash, transaction_fingerprint, duplicate_pair_key, verify_manifest_chain,
)

ALLOWED = {".pdf", ".jpg", ".jpeg", ".png", ".csv"}
MAX_IMAGE_PIXELS = 40_000_000


class EvidenceIntegrityError(ValueError):
    """Stored evidence cannot be proven identical to the scanned bytes."""


def validate_upload_content(filename: str, content: bytes) -> tuple[str, str]:
    """Validate the file signature and return a safe display name + detected MIME.

    Extension/MIME metadata supplied by a browser is never treated as proof of
    file type. Malware scanning remains a separate workflow step.
    """
    normalized = (filename or "upload").replace("\\", "/").split("/")[-1]
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) not in {"Cc", "Cf"})
    normalized = normalized.strip(" .")[:255]
    if not normalized or normalized in {".", ".."}:
        normalized = "upload"
    suffix = Path(normalized).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Định dạng không được hỗ trợ. Chỉ nhận PDF/JPG/PNG/CSV.")
    if not content:
        raise ValueError("Tệp rỗng.")

    signatures = {
        ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
        ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
        ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    }
    if suffix == ".pdf":
        if b"%PDF-" not in content[:1024]:
            raise ValueError("Nội dung tệp không khớp định dạng PDF.")
        detected = "application/pdf"
    elif suffix in signatures:
        signature, detected = signatures[suffix]
        if not content.startswith(signature):
            raise ValueError("Nội dung tệp không khớp định dạng ảnh khai báo.")
        try:
            import warnings
            from PIL import Image
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(io.BytesIO(content))
                if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions exceed the configured pixel limit")
                image.verify()
        except Exception as exc:
            raise ValueError("Tệp ảnh bị lỗi, vượt giới hạn pixel hoặc không hợp lệ.") from exc
    else:
        if b"\x00" in content:
            raise ValueError("CSV không được chứa byte NUL hoặc nội dung nhị phân.")
        try:
            content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV phải sử dụng UTF-8 hoặc UTF-8 BOM.") from exc
        detected = "text/csv"
    return normalized, detected

def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def append_evidence_manifest_entry(db: Session, case: models.Case, doc: models.Document, received_by: str):
    """Append one case-scoped hash-chain entry while holding the case row lock."""
    stored_path = Path(doc.stored_path)
    if not stored_path.is_file() or sha256_file(stored_path).lower() != doc.sha256.lower():
        raise ValueError("Cannot manifest evidence whose stored bytes are missing or hash-mismatched")
    db.query(models.Case).filter(models.Case.id == case.id).with_for_update().one()
    entries = (db.query(models.EvidenceManifestEntry)
               .filter_by(case_id=case.id)
               .order_by(models.EvidenceManifestEntry.sequence_no.asc()).all())
    chain_status = verify_manifest_chain(entries)
    if not chain_status["valid"]:
        raise ValueError("Cannot append evidence to an invalid manifest hash chain")
    if any(str(entry.document_id) == str(doc.id) for entry in entries):
        raise ValueError("Evidence document already has a manifest entry")
    latest = entries[-1] if entries else None
    sequence_no = (latest.sequence_no + 1) if latest else 1
    previous_hash = latest.entry_hash if latest else None
    received_at = datetime.now(timezone.utc)
    actor = (received_by or "data-ai-service")[:160]
    entry_hash = calculate_manifest_entry_hash(
        case_id=case.id, sequence_no=sequence_no, document_id=doc.id,
        original_filename=doc.original_filename, sha256=doc.sha256,
        mime_type=doc.mime_type, file_size=doc.file_size,
        previous_entry_hash=previous_hash, received_at=received_at, received_by=actor,
    )
    entry = models.EvidenceManifestEntry(
        case_id=case.id, document_id=doc.id, sequence_no=sequence_no,
        original_filename=doc.original_filename, sha256=doc.sha256,
        mime_type=doc.mime_type, file_size=doc.file_size,
        previous_entry_hash=previous_hash, entry_hash=entry_hash,
        hash_version="1", received_by=actor, received_at=received_at,
    )
    db.add(entry)
    db.flush()
    return entry


def save_upload(db: Session, case: models.Case, filename: str, content: bytes, actor_id: str | None = None, *, commit: bool = True):
    filename, detected_mime = validate_upload_content(filename, content)
    suffix = Path(filename).suffix.lower()
    if len(content) > settings.max_file_mb * 1024 * 1024:
        raise ValueError(f"Tệp vượt giới hạn {settings.max_file_mb} MiB.")
    existing_count = db.query(models.Document).filter_by(case_id=case.id).count()
    if existing_count >= settings.max_files_per_case:
        raise ValueError("Hồ sơ đã đạt giới hạn số tệp.")
    case_dir = settings.storage_dir / str(case.id)
    case_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        case_dir.chmod(0o700)
    except OSError:
        pass
    temp = case_dir / f"{uuid.uuid4()}{suffix}"
    try:
        temp.write_bytes(content)
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        digest = sha256_file(temp)
        duplicate = db.query(models.Document).filter_by(case_id=case.id, sha256=digest).first()
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    if duplicate:
        temp.unlink(missing_ok=True)
        raise ValueError("Tệp trùng SHA-256 trong cùng hồ sơ.")
    # Each upload attempt owns a unique storage object. Concurrent uploads of
    # identical bytes can race on the DB uniqueness constraint; a losing
    # transaction must never delete the winning transaction's evidence file.
    stored = case_dir / f"{digest}-{uuid.uuid4().hex}{suffix}"
    temp.replace(stored)
    try:
        stored.chmod(0o600)
    except OSError:
        pass
    mime = detected_mime
    doc_type = "BANK_STATEMENT" if suffix == ".csv" else "UNKNOWN"
    obj = models.Document(case_id=case.id, original_filename=Path(filename).name[:255],
        stored_path=str(stored), mime_type=mime, file_size=len(content), sha256=digest,
        detected_mime_type=detected_mime,
        document_type=doc_type, evidence_status="RECEIVED", processing_status="PENDING")
    try:
        db.add(obj)
        db.flush()
        append_evidence_manifest_entry(db, case, obj, actor_id or "data-ai-service")
        db.add(models.AuditEvent(case_id=case.id, actor=(actor_id or "data-ai-service")[:100],
            action="DOCUMENT_RECEIVED", entity_type="document", entity_id=digest,
            details={"filename": obj.original_filename, "size": len(content), "manifested": True}))
        if commit:
            db.commit()
    except Exception as commit_error:
        # The filesystem write precedes the DB commit. Compensate on a failed
        # transaction so an unreferenced evidence object is not left behind.
        db.rollback()
        try:
            stored.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise RuntimeError(
                "Database commit failed and uploaded evidence cleanup also failed; reconcile storage for this case"
            ) from commit_error
        raise
    if commit:
        db.refresh(obj)
    return obj

def _ensure_source_inventory(db: Session, source_code: str, source_name: str, source_type: str, config: dict):
    source = db.query(models.SourceInventory).filter_by(source_code=source_code).first()
    if source is None:
        source = models.SourceInventory(source_code=source_code, source_name=source_name,
            source_type=source_type, schema_version="1.0", approval_status="PENDING_APPROVAL", config=config)
        db.add(source)
    return source


def _quality_issue(db: Session, case_id, document_id, code: str, severity: str,
                   description: str, anchor: dict):
    db.add(models.DataQualityIssue(case_id=case_id, document_id=document_id,
        issue_code=code, severity=severity, description=description,
        source_anchor=anchor, issue_status="OPEN"))


def _verified_processing_copy(doc: models.Document) -> Path:
    """Create a private, hash-verified copy so OCR never follows a mutable path.

    The scanner attests the stored bytes. Processing reads a fresh copy from a
    no-follow file descriptor and verifies that exact copy against the same
    digest before any parser sees it, closing the scan-to-OCR path replacement
    window.
    """
    source = Path(doc.stored_path)
    if source.is_symlink():
        raise EvidenceIntegrityError("Evidence storage path is a symbolic link")
    root = settings.storage_dir.resolve()
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise EvidenceIntegrityError("Evidence storage object is missing or outside the protected storage root") from exc
    processing_dir = root / "_processing"
    processing_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if processing_dir.is_symlink():
        raise EvidenceIntegrityError("Processing temp directory must not be a symbolic link")
    processing_dir = processing_dir.resolve(strict=True)
    try:
        processing_dir.relative_to(root)
    except ValueError as exc:
        raise EvidenceIntegrityError("Processing temp directory is outside protected storage") from exc
    try:
        processing_dir.chmod(0o700)
    except OSError:
        pass

    suffix = Path(doc.original_filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Document extension is not supported for processing")
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(str(resolved), source_flags)
    except OSError as exc:
        raise EvidenceIntegrityError("Evidence storage object cannot be opened safely") from exc
    temp_fd = -1
    temp_path: Path | None = None
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise EvidenceIntegrityError("Evidence storage object is not a regular file")
        if doc.file_size is not None and source_stat.st_size != doc.file_size:
            raise EvidenceIntegrityError("Evidence file size changed after malware scanning")
        temp_fd, temp_name = tempfile.mkstemp(prefix=f"{doc.id}-", suffix=suffix, dir=processing_dir)
        temp_path = Path(temp_name)
        digest = hashlib.sha256()
        copied = 0
        with os.fdopen(source_fd, "rb", closefd=True) as source_file:
            source_fd = -1
            with os.fdopen(temp_fd, "wb", closefd=True) as target_file:
                temp_fd = -1
                while True:
                    chunk = source_file.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    target_file.write(chunk)
                    copied += len(chunk)
                target_file.flush()
                os.fsync(target_file.fileno())
        if copied != source_stat.st_size or digest.hexdigest().lower() != str(doc.sha256).lower():
            raise EvidenceIntegrityError("Evidence bytes changed after the ClamAV scan; OCR is blocked")
        temp_path.chmod(0o400)
        return temp_path
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if temp_fd >= 0:
            os.close(temp_fd)



def create_payroll_evidence_candidate(db: Session, doc: models.Document, extracted_fields: list[models.ExtractedField]):
    """Persist OCR-derived payslip evidence as an unverified candidate only.

    A candidate is never accepted income. Every amount/date retains its source
    ExtractedField ID and anchor; Maker review is required before handoff.
    """
    from datetime import date as date_type
    from decimal import Decimal, InvalidOperation

    if doc.document_type != "PAYSLIP":
        return None
    existing = db.query(models.PayrollEvidence).filter_by(case_id=doc.case_id, document_id=doc.id).first()
    if existing:
        return existing
    by_name = {}
    for item in extracted_fields:
        if item.field_name in {"gross_salary", "net_salary", "payment_date"}:
            # Keep first deterministic extraction per field; other candidates remain
            # available in extracted_fields for the Maker to inspect.
            by_name.setdefault(item.field_name, item)
    date_field = by_name.get("payment_date")
    if not date_field or not isinstance(date_field.normalized_value, dict):
        return None
    raw_date = date_field.normalized_value.get("date")
    try:
        payment_date = date_type.fromisoformat(str(raw_date))
    except (TypeError, ValueError):
        return None

    amounts = {}
    for key, column in (("gross_salary", "gross_amount"), ("net_salary", "net_amount")):
        field = by_name.get(key)
        raw_amount = field.normalized_value.get("amount_vnd") if field and isinstance(field.normalized_value, dict) else None
        if raw_amount is not None:
            try:
                amount = Decimal(str(raw_amount))
                if amount.is_finite() and amount > 0:
                    amounts[column] = amount
            except (InvalidOperation, ValueError):
                pass
    if not amounts:
        return None

    anchor = {}
    for key, field in by_name.items():
        anchor[key] = {
            "field_id": str(field.id), "page_number": field.page_number,
            "source_line": field.source_line, "bbox": field.bbox,
            "coordinate_space": field.coordinate_space,
            "extraction_method": field.extraction_method,
            "confidence": float(field.confidence or 0),
            "confidence_basis": field.confidence_basis,
            "extraction_decision": field.extraction_decision,
            "validation_status": field.validation_status,
        }
    obj = models.PayrollEvidence(
        case_id=doc.case_id, document_id=doc.id, payment_date=payment_date,
        currency="VND", evidence_status="OCR_CANDIDATE", source_anchor=anchor,
        gross_amount=amounts.get("gross_amount"), net_amount=amounts.get("net_amount"),
        gross_amount_field_id=by_name.get("gross_salary").id if by_name.get("gross_salary") else None,
        net_amount_field_id=by_name.get("net_salary").id if by_name.get("net_salary") else None,
        payment_date_field_id=date_field.id, extraction_version=PIPELINE_VERSION,
    )
    db.add(obj)
    db.flush()
    from app.ledger import generate_payroll_match_candidates
    generate_payroll_match_candidates(db, doc.case_id)
    return obj

def process_document(db: Session, case: models.Case, doc: models.Document):
    if settings.require_scope_consent:
        attestation = (db.query(models.CaseScopeConsentAttestation).filter_by(case_id=case.id)
                      .order_by(models.CaseScopeConsentAttestation.attested_at.desc(),
                                models.CaseScopeConsentAttestation.id.desc()).first())
        if attestation is None or attestation.scope_status != "IN_SCOPE" or attestation.consent_status != "GRANTED":
            raise ValueError("OCR/processing is blocked until Backend attests the case is in-scope and consent is GRANTED")
    trusted_scan = (db.query(models.DocumentSecurityEvent)
                    .filter(models.DocumentSecurityEvent.document_id == doc.id,
                            models.DocumentSecurityEvent.event_type == "SCAN_COMPLETED",
                            models.DocumentSecurityEvent.scan_status == "CLEAN",
                            models.DocumentSecurityEvent.scanned_sha256 == doc.sha256,
                            models.DocumentSecurityEvent.attestation_version == "V1_CLAMAV",
                            models.DocumentSecurityEvent.engine_name == "ClamAV",
                            models.DocumentSecurityEvent.engine_version.isnot(None)).first())
    if doc.malware_scan_status != "CLEAN" or trusted_scan is None:
        raise ValueError("OCR/processing is blocked until a byte-bound ClamAV CLEAN attestation exists")
    idempotency_key = f"document:{doc.id}:{doc.sha256}:{PIPELINE_VERSION}"
    previous = db.query(models.PipelineRun).filter_by(idempotency_key=idempotency_key).first()
    if previous and previous.status == "COMPLETED":
        # Even an idempotent replay must not trust mutable storage bytes. The
        # stored result is stable, but a storage integrity check is still due.
        verified_path = _verified_processing_copy(doc)
        verified_path.unlink(missing_ok=True)
        return {"document_id": str(doc.id), "status": "COMPLETED", "already_processed": True,
                **(previous.metrics or {})}

    path = _verified_processing_copy(doc)
    run = previous or models.PipelineRun(case_id=case.id, document_id=doc.id,
        idempotency_key=idempotency_key, pipeline_version=PIPELINE_VERSION, status="RUNNING", metrics={})
    if previous is None:
        db.add(run)
        db.flush()

    try:
        if path.suffix.lower() == ".csv":
            result = process_csv(db, case, doc, path)
            run.status = "COMPLETED"
            run.metrics = {k: v for k, v in result.items() if k != "document_id"}
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return result

        words, page_count = extract_words(path)
        doc.page_count = page_count
        page_text = "\n".join(" ".join(w["text"] for w in words if w["page_number"] == page)
                               for page in range(1, page_count + 1))
        classification = classify_document(page_text, doc.original_filename)
        doc.document_type = classification["document_type"]
        doc.layout_code = classification["layout_code"]
        for word in words:
            db.add(models.ExtractedField(document_id=doc.id, field_name="ocr_token",
                raw_value=word["text"], normalized_value=None, confidence=word["confidence"],
                page_number=word["page_number"], bbox=word["bbox"],
                coordinate_space=word.get("coordinate_space"),
                extraction_method=word.get("extraction_method"),
                confidence_basis=("NATIVE_TEXT_LAYER_UNCALIBRATED" if word.get("extraction_method") == "PDF_TEXT_LAYER"
                                   else "OCR_ENGINE_UNCALIBRATED" if word.get("extraction_method") == "TESSERACT_OCR" else "UNKNOWN"),
                validation_status="NOT_ASSESSED", extraction_decision="ABSTAIN",
                abstain_reason="RAW_OCR_TOKEN_REQUIRES_FIELD_MAPPING_AND_MAKER_REVIEW",
                extraction_rule_version=PIPELINE_VERSION, review_status="NEEDS_REVIEW"))

        extracted = extract_labeled_fields(words)
        persisted_fields = []
        for item in extracted:
            field_row = models.ExtractedField(document_id=doc.id, **item)
            db.add(field_row)
            persisted_fields.append(field_row)
        db.flush()
        payroll_candidate = create_payroll_evidence_candidate(db, doc, persisted_fields)
        source_code = f"GENERIC_{doc.document_type}"
        _ensure_source_inventory(db, source_code, f"Generic {doc.document_type} OCR source",
            "OCR_DOCUMENT", {"layout_code": doc.layout_code, "approval": "provisional heuristic"})
        if not words:
            _quality_issue(db, case.id, doc.id, "OCR_NO_TEXT", "HIGH",
                "Không trích xuất được văn bản từ tài liệu; cần kiểm tra chất lượng ảnh hoặc OCR.",
                {"document_id": str(doc.id), "page_count": page_count})
        if classification["document_type"] == "UNKNOWN":
            _quality_issue(db, case.id, doc.id, "DOCUMENT_TYPE_UNKNOWN", "MEDIUM",
                "Chưa nhận diện được loại chứng từ; cần Maker xác minh.",
                {"document_id": str(doc.id), "page_count": page_count})
        low_confidence = sum(1 for w in words if w["confidence"] < 0.85)
        if low_confidence:
            _quality_issue(db, case.id, doc.id, "OCR_LOW_CONFIDENCE", "MEDIUM",
                f"Có {low_confidence}/{len(words)} token OCR có confidence dưới 0.85.",
                {"document_id": str(doc.id), "low_confidence_tokens": low_confidence})
        if not extracted and words:
            _quality_issue(db, case.id, doc.id, "NO_LABELED_FIELDS", "MEDIUM",
                "OCR có văn bản nhưng chưa trích xuất được trường có nhãn theo bộ quy tắc hiện tại.",
                {"document_id": str(doc.id), "page_count": page_count})

        doc.processing_status = "COMPLETED"
        abstained_fields = [item for item in extracted if item.get("extraction_decision") == "ABSTAIN"]
        summary = {"ocr_word_count": len(words), "page_count": page_count,
            "document_type": classification["document_type"], "layout_code": classification["layout_code"],
            "layout_profile_id": classification.get("layout_profile_id"),
            "classification_confidence": classification["confidence"],
            "classification_confidence_basis": classification.get("confidence_basis"),
            "classification_status": classification["classification_status"],
            "classification_abstain_reason": classification.get("abstain_reason"),
            "extracted_field_count": len(extracted), "abstained_field_count": len(abstained_fields),
            "suggested_field_count": len(extracted) - len(abstained_fields),
            "field_catalog_version": FIELD_CATALOG_VERSION,
            "layout_catalog_version": LAYOUT_CATALOG_VERSION,
            "maker_review_required": True,
            "payroll_evidence_candidate_id": str(payroll_candidate.id) if payroll_candidate else None,
            "payroll_evidence_status": "OCR_CANDIDATE" if payroll_candidate else None,
            "automation_decision": "ABSTAIN" if classification["classification_status"] == "ABSTAINED" or abstained_fields else "SUGGEST_ONLY",
            "layout_approval": "PENDING_BANK_PO_SIGNOFF"}
        if classification["classification_status"] == "ABSTAINED":
            _quality_issue(db, case.id, doc.id, "DOCUMENT_CLASSIFICATION_ABSTAINED", "MEDIUM",
                "Không đủ tín hiệu phân loại đáng tin cậy; chuyển Maker xác minh loại chứng từ.",
                {"document_id": str(doc.id), "reason": classification.get("abstain_reason"),
                 "candidate_document_type": classification.get("candidate_document_type")})
        if abstained_fields:
            _quality_issue(db, case.id, doc.id, "FIELD_EXTRACTION_ABSTAINED", "MEDIUM",
                f"Có {len(abstained_fields)} trường không đủ điều kiện gợi ý tự động; cần Maker review.",
                {"document_id": str(doc.id), "field_names": [x["field_name"] for x in abstained_fields],
                 "reasons": sorted({r for x in abstained_fields for r in (x.get("abstain_reason") or "").split(",") if r})})
        db.add(models.ProcessingResult(case_id=case.id, document_id=doc.id,
            pipeline_version=PIPELINE_VERSION, result_status="COMPLETED", summary=summary))
        run.status = "COMPLETED"
        run.metrics = summary
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {"document_id": str(doc.id), **summary}
    except Exception:
        db.rollback()
        failed_run = db.query(models.PipelineRun).filter_by(idempotency_key=idempotency_key).first()
        if failed_run is not None:
            failed_run.status = "FAILED"
            failed_run.completed_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        path.unlink(missing_ok=True)

def process_csv(db: Session, case: models.Case, doc: models.Document, path: Path):
    inserted = 0
    duplicate_candidates = 0
    missing_date = 0
    missing_amount = 0
    _ensure_source_inventory(db, "GENERIC_BANK_CSV", "Generic bank CSV adapter",
        "BANK_STATEMENT_CSV", {"approval": "PENDING_BANK_SCHEMA_SIGNOFF",
        "supported_headers": ["date", "transaction_date", "description", "credit", "debit", "amount"]})
    existing_rows = (db.query(models.Transaction).filter(models.Transaction.case_id == case.id)
                     .order_by(models.Transaction.transaction_date.asc(), models.Transaction.source_row.asc(),
                               models.Transaction.id.asc()).all())
    fingerprint_transactions: dict[str, list[models.Transaction]] = {}
    for tx in existing_rows:
        fingerprint = transaction_fingerprint(tx.transaction_date, tx.amount_vnd, tx.direction, tx.description)
        if fingerprint:
            fingerprint_transactions.setdefault(fingerprint, []).append(tx)
    existing_candidate_keys = {x.candidate_key for x in db.query(models.TransactionDuplicateCandidate)
                               .filter_by(case_id=case.id).all()}

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096); f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV không có header.")
        aliases = {h.strip().lower(): h for h in reader.fieldnames if h}
        def pick(row, names):
            for n in names:
                if n in aliases:
                    return row.get(aliases[n])
            return None
        date_header = any(n in aliases for n in ["date", "transaction_date", "ngay", "ngày"])
        amount_header = any(n in aliases for n in ["amount", "so tien", "số tiền", "credit", "ghi co", "ghi có", "debit", "ghi no", "ghi nợ"])
        if not date_header:
            _quality_issue(db, case.id, doc.id, "CSV_DATE_COLUMN_MISSING", "HIGH",
                "CSV không có cột ngày giao dịch được nhận diện.", {"document_id": str(doc.id), "source_row": 1})
        if not amount_header:
            _quality_issue(db, case.id, doc.id, "CSV_AMOUNT_COLUMN_MISSING", "HIGH",
                "CSV không có cột số tiền được nhận diện.", {"document_id": str(doc.id), "source_row": 1})

        for row_no, row in enumerate(reader, start=2):
            if row_no - 1 > settings.max_csv_rows:
                raise ValueError(f"CSV vượt giới hạn {settings.max_csv_rows} dòng dữ liệu.")
            date_raw = pick(row, ["date", "transaction_date", "ngay", "ngày"])
            desc = pick(row, ["description", "details", "content", "noi dung", "nội dung"]) or ""
            credit_raw = pick(row, ["credit", "ghi co", "ghi có"])
            debit_raw = pick(row, ["debit", "ghi no", "ghi nợ"])
            amount_raw = pick(row, ["amount", "so tien", "số tiền"])
            direction = "UNKNOWN"
            amount = parse_vnd(amount_raw)
            if credit_raw not in (None, ""):
                amount, direction = parse_vnd(credit_raw), "CREDIT"
            elif debit_raw not in (None, ""):
                amount, direction = parse_vnd(debit_raw), "DEBIT"
            elif amount is not None:
                direction = "CREDIT" if amount > 0 else "DEBIT"
            normalized_date = normalize_date(date_raw)
            if not normalized_date:
                missing_date += 1
                _quality_issue(db, case.id, doc.id, "TRANSACTION_DATE_MISSING_OR_INVALID", "MEDIUM",
                    "Ngày giao dịch thiếu hoặc không đúng định dạng hỗ trợ.",
                    {"document_id": str(doc.id), "source_row": row_no, "source_column": "date"})
            if amount is None:
                missing_amount += 1
                _quality_issue(db, case.id, doc.id, "TRANSACTION_AMOUNT_MISSING_OR_INVALID", "HIGH",
                    "Số tiền giao dịch thiếu hoặc không đọc được.",
                    {"document_id": str(doc.id), "source_row": row_no, "source_column": "amount"})
            category, confidence, _ = classify_transaction(desc, float(amount) if amount is not None else None, direction)
            fingerprint = transaction_fingerprint(normalized_date, amount, direction, str(desc))
            matching_transactions = list(fingerprint_transactions.get(fingerprint, [])) if fingerprint else []
            is_duplicate = bool(matching_transactions)
            if is_duplicate:
                category = "duplicate_candidate"
            transaction = models.Transaction(case_id=case.id, document_id=doc.id, source_row=row_no,
                transaction_date=normalized_date, description=str(desc)[:2000],
                amount_vnd=abs(amount) if amount is not None else None, direction=direction,
                category=category, classification_confidence=confidence,
                is_income_eligible=False, review_status="NEEDS_REVIEW")
            db.add(transaction)
            db.flush()
            if is_duplicate and fingerprint:
                candidate_pair_count = 0
                candidate_match_limit = 10
                for matched in matching_transactions[:candidate_match_limit]:
                    left_id, right_id, candidate_key = duplicate_pair_key(case.id, matched.id, transaction.id)
                    if candidate_key in existing_candidate_keys:
                        continue
                    db.add(models.TransactionDuplicateCandidate(
                        case_id=case.id, left_transaction_id=uuid.UUID(left_id),
                        right_transaction_id=uuid.UUID(right_id), fingerprint_sha256=fingerprint,
                        candidate_key=candidate_key,
                        match_reasons=["EXACT_DATE", "EXACT_ABSOLUTE_AMOUNT", "EXACT_DIRECTION", "NORMALIZED_DESCRIPTION"],
                        review_status="PENDING_REVIEW"))
                    existing_candidate_keys.add(candidate_key)
                    candidate_pair_count += 1
                if candidate_pair_count:
                    duplicate_candidates += candidate_pair_count
                    _quality_issue(db, case.id, doc.id, "TRANSACTION_DUPLICATE_CANDIDATE", "MEDIUM",
                        "Giao dịch trùng fingerprint với dòng đã nhập; tạo cặp ứng viên cho Maker, không tự động xóa hoặc loại khỏi tổng.",
                        {"document_id": str(doc.id), "source_row": row_no,
                         "transaction_id": str(transaction.id), "matched_transaction_ids": [str(x.id) for x in matching_transactions[:candidate_match_limit]],
                         "fingerprint_sha256": fingerprint, "total_exact_matches": len(matching_transactions),
                         "candidate_match_limit": candidate_match_limit})
                if len(matching_transactions) > candidate_match_limit:
                    _quality_issue(db, case.id, doc.id, "DUPLICATE_CANDIDATE_FANOUT_LIMIT", "HIGH",
                        "Số dòng trùng fingerprint vượt giới hạn liên kết tự động; cần Maker review toàn bộ nhóm trước khi xử lý.",
                        {"document_id": str(doc.id), "source_row": row_no,
                         "total_exact_matches": len(matching_transactions), "candidate_match_limit": candidate_match_limit,
                         "fingerprint_sha256": fingerprint})
            if fingerprint:
                fingerprint_transactions.setdefault(fingerprint, []).append(transaction)
            inserted += 1

    doc.document_type = "BANK_STATEMENT"
    doc.layout_code = "GENERIC_BANK_CSV"
    doc.processing_status = "COMPLETED"
    summary = {"transaction_rows_imported": inserted, "duplicate_candidates": duplicate_candidates,
        "missing_or_invalid_dates": missing_date, "missing_or_invalid_amounts": missing_amount,
        "layout_profile_id": "GENERIC_BANK_STATEMENT_CSV",
        "layout_catalog_version": LAYOUT_CATALOG_VERSION,
        "field_catalog_version": FIELD_CATALOG_VERSION,
        "automation_decision": "SUGGEST_ONLY", "maker_review_required": True,
        "schema_approval": "PENDING_BANK_SIGNOFF",
        "note": "Classification is advisory; income eligibility remains false pending authorized review."}
    db.add(models.ProcessingResult(case_id=case.id, document_id=doc.id,
        pipeline_version=PIPELINE_VERSION, result_status="COMPLETED", summary=summary))
    from app.ledger import rebuild_observed_income_ledger, generate_payroll_match_candidates
    ledger_months = rebuild_observed_income_ledger(db, case.id)
    match_candidates = generate_payroll_match_candidates(db, case.id)
    summary["observed_income_ledger_months"] = ledger_months
    summary["payroll_match_candidates_created"] = match_candidates
    # Parent process_document() commits the CSV rows, quality findings, ledger,
    # ProcessingResult, and PipelineRun status as one database transaction.
    return {"document_id": str(doc.id), **summary}

