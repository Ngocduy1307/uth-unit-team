"""Provisional document classification and evidence-aware field extraction.

All outputs are suggestions. The six generic profiles and 20-field catalogue are
versioned integration scaffolding; none is bank-approved until PO/bank sign-off.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from typing import Any

PIPELINE_VERSION = "0.4.0"
FIELD_CATALOG_VERSION = "2026-11-26.1"
LAYOUT_CATALOG_VERSION = "2026-11-26.1"
FIELD_CONFIDENCE_THRESHOLD = 0.85
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.65

# Provisional document families, not bank-approved layouts.
DOCUMENT_FAMILIES = {
    "BANK_STATEMENT": ("sao ke", "statement", "transaction history", "lich su giao dich", "lịch sử giao dịch"),
    "PAYSLIP": ("phieu luong", "bảng lương", "bang luong", "payslip", "salary slip"),
    "EMPLOYMENT_CERTIFICATE": ("xac nhan cong tac", "xác nhận công tác", "employment certificate"),
    "IDENTITY_DOCUMENT": ("can cuoc cong dan", "căn cước công dân", "chung minh nhan dan", "identity card"),
    "LOAN_DOCUMENT": ("hop dong tin dung", "hợp đồng tín dụng", "loan agreement"),
}

# These six generic integration profiles are deliberately NOT represented as
# six bank-approved layouts. The actual bank-specific templates are pending.
LAYOUT_PROFILES: tuple[dict[str, Any], ...] = (
    {"profile_id": "GENERIC_BANK_STATEMENT_PDF", "document_family": "BANK_STATEMENT", "format": "PDF",
     "approval_status": "PENDING_BANK_PO_SIGNOFF", "profile_status": "PROVISIONAL"},
    {"profile_id": "GENERIC_BANK_STATEMENT_CSV", "document_family": "BANK_STATEMENT", "format": "CSV",
     "approval_status": "PENDING_BANK_PO_SIGNOFF", "profile_status": "PROVISIONAL"},
    {"profile_id": "GENERIC_PAYSLIP", "document_family": "PAYSLIP", "format": "PDF_OR_IMAGE",
     "approval_status": "PENDING_BANK_PO_SIGNOFF", "profile_status": "PROVISIONAL"},
    {"profile_id": "GENERIC_EMPLOYMENT_CERTIFICATE", "document_family": "EMPLOYMENT_CERTIFICATE", "format": "PDF_OR_IMAGE",
     "approval_status": "PENDING_BANK_PO_SIGNOFF", "profile_status": "PROVISIONAL"},
    {"profile_id": "GENERIC_IDENTITY_DOCUMENT", "document_family": "IDENTITY_DOCUMENT", "format": "PDF_OR_IMAGE",
     "approval_status": "PENDING_BANK_PO_SIGNOFF", "profile_status": "PROVISIONAL"},
    {"profile_id": "GENERIC_LOAN_DOCUMENT", "document_family": "LOAN_DOCUMENT", "format": "PDF_OR_IMAGE",
     "approval_status": "PENDING_BANK_PO_SIGNOFF", "profile_status": "PROVISIONAL"},
)

# Provisional labels. The PO/bank must confirm the exact SRS 20-field list.
FIELD_PATTERNS: dict[str, list[str]] = {
    "account_holder_name": [r"(?:chu tai khoan|chủ tài khoản|account holder|customer name)\s*[:：-]\s*([\wÀ-ỹ .'-]{3,100})"],
    "account_number": [r"(?:so tai khoan|số tài khoản|account number|account no\.?|a/c no\.?)\s*[:：-]?\s*([0-9*Xx -]{6,30})"],
    "bank_name": [r"(?:ngan hang|ngân hàng|bank)\s*[:：-]\s*([\wÀ-ỹ .'-]{2,100})"],
    "statement_period": [r"(?:ky sao ke|kỳ sao kê|statement period|period)\s*[:：-]\s*([^\n]{5,80})"],
    "statement_start_date": [r"(?:tu ngay|từ ngày|from)\s*[:：-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})"],
    "statement_end_date": [r"(?:den ngay|đến ngày|to)\s*[:：-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})"],
    "opening_balance": [r"(?:so du dau ky|số dư đầu kỳ|opening balance)\s*[:：-]?\s*([0-9.,]+)"],
    "closing_balance": [r"(?:so du cuoi ky|số dư cuối kỳ|closing balance)\s*[:：-]?\s*([0-9.,]+)"],
    "gross_salary": [r"(?:luong gross|lương gross|gross salary|tong thu nhap|tổng thu nhập)\s*[:：-]?\s*([0-9.,]+)"],
    "net_salary": [r"(?:luong net|lương net|net salary|thuc linh|thực lĩnh)\s*[:：-]?\s*([0-9.,]+)"],
    "payment_date": [r"(?:ngay thanh toan|ngày thanh toán|payment date|ngay nhan luong|ngày nhận lương)\s*[:：-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})"],
    "employer_name": [r"(?:cong ty|công ty|employer|company)\s*[:：-]\s*([^\n]{3,120})"],
    "employee_name": [r"(?:ho va ten|họ và tên|employee name|nhan vien|nhân viên)\s*[:：-]\s*([^\n]{3,100})"],
    "employee_id": [r"(?:ma nhan vien|mã nhân viên|employee id)\s*[:：-]?\s*([A-Za-z0-9_-]{2,40})"],
    "tax_code": [r"(?:ma so thue|mã số thuế|tax code)\s*[:：-]?\s*([0-9-]{8,20})"],
    "identity_number_masked": [r"(?:so can cuoc|số căn cước|cccd|identity no\.?)\s*[:：-]?\s*([0-9Xx* -]{8,20})"],
    "document_date": [r"(?:ngay lap|ngày lập|date)\s*[:：-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})"],
    "currency": [r"\b(VND|VNĐ|USD)\b"],
    "phone_number": [r"(?:dien thoai|điện thoại|phone|mobile)\s*[:：-]?\s*(0\d{9,10})"],
    "branch_name": [r"(?:chi nhanh|chi nhánh|branch)\s*[:：-]\s*([^\n]{2,100})"],
}

FIELD_TYPES: dict[str, str] = {
    "account_holder_name": "PERSON_NAME", "account_number": "ACCOUNT_IDENTIFIER",
    "bank_name": "ORGANIZATION", "statement_period": "PERIOD_TEXT",
    "statement_start_date": "DATE", "statement_end_date": "DATE",
    "opening_balance": "MONEY", "closing_balance": "MONEY", "gross_salary": "MONEY",
    "net_salary": "MONEY", "payment_date": "DATE", "employer_name": "ORGANIZATION",
    "employee_name": "PERSON_NAME", "employee_id": "IDENTIFIER", "tax_code": "TAX_IDENTIFIER",
    "identity_number_masked": "IDENTITY_IDENTIFIER", "document_date": "DATE",
    "currency": "CURRENCY", "phone_number": "PHONE", "branch_name": "ORGANIZATION",
}


def get_ocr_catalog() -> dict[str, Any]:
    """Return the provisional profile and field catalogue for Backend/PO review."""
    return {
        "layout_catalog_version": LAYOUT_CATALOG_VERSION,
        "field_catalog_version": FIELD_CATALOG_VERSION,
        "authority": "PROVISIONAL_DATA_AI_CANDIDATES",
        "bank_approval_status": "PENDING_BANK_PO_SIGNOFF",
        "layout_profiles": [dict(item) for item in LAYOUT_PROFILES],
        "field_catalog": [
            {"field_name": name, "data_type": FIELD_TYPES[name], "required": None,
             "approval_status": "PENDING_SRS_PO_SIGNOFF", "extraction_rule_count": len(patterns)}
            for name, patterns in FIELD_PATTERNS.items()
        ],
        "field_count": len(FIELD_PATTERNS),
        "layout_profile_count": len(LAYOUT_PROFILES),
    }


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", value).strip()


def classify_document(text: str, filename: str = "") -> dict[str, Any]:
    haystack = normalize_text(f"{filename} {text}").casefold()
    scores = {family: sum(1 for keyword in keywords if keyword.casefold() in haystack)
              for family, keywords in DOCUMENT_FAMILIES.items()}
    max_score = max(scores.values(), default=0)
    winners = [family for family, score in scores.items() if score == max_score and score > 0]
    if max_score == 0:
        return {"document_type": "UNKNOWN", "layout_code": "UNKNOWN", "layout_profile_id": None,
                "confidence": 0.0, "classification_status": "ABSTAINED",
                "abstain_reason": "NO_CLASSIFICATION_SIGNAL", "confidence_basis": "KEYWORD_HEURISTIC",
                "scores": scores}
    if len(winners) != 1:
        return {"document_type": "UNKNOWN", "layout_code": "UNKNOWN", "layout_profile_id": None,
                "confidence": 0.0, "classification_status": "ABSTAINED",
                "abstain_reason": "AMBIGUOUS_DOCUMENT_FAMILY", "confidence_basis": "KEYWORD_HEURISTIC",
                "candidate_families": winners, "scores": scores}
    family = winners[0]
    confidence = min(0.85, 0.45 + 0.12 * max_score)
    if confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return {"document_type": "UNKNOWN", "layout_code": "UNKNOWN", "layout_profile_id": None,
                "candidate_document_type": family, "confidence": round(confidence, 4),
                "classification_status": "ABSTAINED", "abstain_reason": "LOW_CLASSIFICATION_CONFIDENCE",
                "confidence_basis": "KEYWORD_HEURISTIC", "scores": scores}
    profile_id = f"GENERIC_{family}"
    if family == "BANK_STATEMENT":
        profile_id = "GENERIC_BANK_STATEMENT_PDF"
    return {"document_type": family, "layout_code": f"GENERIC_{family}",
            "layout_profile_id": profile_id, "confidence": round(confidence, 4),
            "classification_status": "SUGGESTED", "abstain_reason": None,
            "confidence_basis": "KEYWORD_HEURISTIC", "scores": scores}


def _parse_amount(value: str) -> Decimal | None:
    from app.normalizer import parse_vnd
    return parse_vnd(value)


def _normalize_field(field_name: str, raw: str) -> tuple[dict[str, Any] | None, str]:
    from app.normalizer import normalize_date
    amount_fields = {"opening_balance", "closing_balance", "gross_salary", "net_salary"}
    date_fields = {"statement_start_date", "statement_end_date", "payment_date", "document_date"}
    identifier_fields = {"account_number", "identity_number_masked"}
    if field_name in amount_fields:
        amount = _parse_amount(raw)
        return ({"amount_vnd": str(amount)}, "VALID") if amount is not None else (None, "INVALID_FORMAT")
    if field_name in date_fields:
        date_value = normalize_date(raw)
        return ({"date": date_value}, "VALID") if date_value else (None, "INVALID_FORMAT")
    if field_name in identifier_fields:
        digits = re.sub(r"\D", "", raw)
        return ({"last4": digits[-4:]}, "VALID") if len(digits) >= 4 else (None, "INVALID_FORMAT")
    if field_name == "phone_number":
        digits = re.sub(r"\D", "", raw)
        if len(digits) not in {10, 11} or not digits.startswith("0"):
            return None, "INVALID_FORMAT"
        return {"value": digits}, "VALID"
    if field_name == "tax_code":
        digits = re.sub(r"\D", "", raw)
        if len(digits) not in {10, 13}:
            return None, "INVALID_FORMAT"
        return {"value": digits}, "VALID"
    if field_name == "currency":
        code = raw.upper().replace("Đ", "D")
        if code not in {"VND", "USD"}:
            return None, "INVALID_FORMAT"
        return {"code": code}, "VALID"
    return {"value": raw}, "FORMAT_UNCHECKED"


def extract_labeled_fields(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract candidate values with anchors, validation, confidence basis and abstention."""
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        by_page[int(word.get("page_number") or 1)].append(word)

    output: list[dict[str, Any]] = []
    for page_number, page_words in by_page.items():
        text = " ".join(str(w.get("text", "")) for w in page_words)
        for field_name, patterns in FIELD_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if not match:
                    continue
                raw = normalize_text(match.group(1) if match.lastindex else match.group(0)).strip(" :：-")
                if not raw:
                    continue
                value_tokens = [t.casefold() for t in re.findall(r"[\wÀ-ỹ*]+", raw) if len(t) > 1]
                matched_words = [w for w in page_words if any(t in str(w.get("text", "")).casefold() for t in value_tokens)]
                boxes = [w.get("bbox") for w in matched_words
                         if isinstance(w.get("bbox"), dict) and w.get("bbox")]
                anchor_found = bool(boxes)
                if anchor_found:
                    xs = [float(b.get("x", 0)) for b in boxes]
                    ys = [float(b.get("y", 0)) for b in boxes]
                    rights = [float(b.get("x", 0)) + float(b.get("width", 0)) for b in boxes]
                    bottoms = [float(b.get("y", 0)) + float(b.get("height", 0)) for b in boxes]
                    bbox = {"x": min(xs), "y": min(ys), "width": max(rights)-min(xs), "height": max(bottoms)-min(ys)}
                    anchored_words = [w for w in matched_words if isinstance(w.get("bbox"), dict) and w.get("bbox")]
                    coordinate_space = anchored_words[0].get("coordinate_space", "IMAGE_PIXEL")
                    extraction_method = anchored_words[0].get("extraction_method", "UNKNOWN")
                    confidence_values = [float(w.get("confidence", 0)) for w in matched_words]
                    confidence = min(confidence_values) if confidence_values else 0.0
                else:
                    bbox = None
                    coordinate_space = None
                    extraction_method = "UNKNOWN"
                    confidence = 0.0

                normalized, validation_status = _normalize_field(field_name, raw)
                confidence_basis = {
                    "TESSERACT_OCR": "OCR_ENGINE_UNCALIBRATED",
                    "PDF_TEXT_LAYER": "NATIVE_TEXT_LAYER_UNCALIBRATED",
                    "CSV_IMPORT": "CSV_IMPORT",
                    "MANUAL": "MANUAL",
                }.get(extraction_method, "UNKNOWN")
                abstain_reasons: list[str] = []
                if validation_status == "INVALID_FORMAT":
                    abstain_reasons.append("INVALID_FORMAT")
                if not anchor_found:
                    abstain_reasons.append("SOURCE_ANCHOR_NOT_FOUND")
                if confidence_basis == "NATIVE_TEXT_LAYER_UNCALIBRATED":
                    abstain_reasons.append("CONFIDENCE_NOT_CALIBRATED")
                elif confidence < FIELD_CONFIDENCE_THRESHOLD:
                    abstain_reasons.append("LOW_CONFIDENCE")

                extraction_decision = "ABSTAIN" if abstain_reasons else "SUGGEST"
                review_status = "NEEDS_REVIEW" if extraction_decision == "ABSTAIN" or validation_status != "VALID" else "SUGGESTED"
                output.append({
                    "field_name": field_name, "raw_value": raw, "normalized_value": normalized,
                    "confidence": confidence, "page_number": page_number, "bbox": bbox,
                    "coordinate_space": coordinate_space, "extraction_method": extraction_method,
                    "confidence_basis": confidence_basis, "validation_status": validation_status,
                    "extraction_decision": extraction_decision,
                    "abstain_reason": ",".join(abstain_reasons) if abstain_reasons else None,
                    "extraction_rule_version": FIELD_CATALOG_VERSION,
                    "review_status": review_status,
                })
                break
    return output
