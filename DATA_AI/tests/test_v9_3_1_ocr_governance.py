from app import models
from app.document_intelligence import (
    FIELD_CONFIDENCE_THRESHOLD,
    FIELD_PATTERNS,
    LAYOUT_PROFILES,
    classify_document,
    extract_labeled_fields,
    get_ocr_catalog,
)


def _words(text: str, *, confidence: float = 0.97, method: str = "TESSERACT_OCR"):
    result = []
    for index, token in enumerate(text.split()):
        result.append({
            "text": token,
            "confidence": confidence,
            "page_number": 1,
            "bbox": {"x": index * 12, "y": 20, "width": 10, "height": 9},
            "coordinate_space": "IMAGE_PIXEL",
            "extraction_method": method,
        })
    return result


def test_catalog_exposes_six_provisional_profiles_and_twenty_pending_fields():
    catalog = get_ocr_catalog()
    assert catalog["layout_profile_count"] == 6
    assert catalog["field_count"] == 20
    assert len(FIELD_PATTERNS) == 20
    assert all(x["approval_status"] == "PENDING_BANK_PO_SIGNOFF" for x in catalog["layout_profiles"])
    assert all(x["approval_status"] == "PENDING_SRS_PO_SIGNOFF" for x in catalog["field_catalog"])
    assert len(LAYOUT_PROFILES) == 6


def test_ambiguous_document_family_abstains_instead_of_picking_first_match():
    result = classify_document("bank statement transaction history payslip salary slip")
    assert result["document_type"] == "UNKNOWN"
    assert result["classification_status"] == "ABSTAINED"
    assert result["abstain_reason"] == "AMBIGUOUS_DOCUMENT_FAMILY"


def test_low_classification_signal_abstains():
    result = classify_document("statement")
    assert result["classification_status"] == "ABSTAINED"
    assert result["abstain_reason"] == "LOW_CLASSIFICATION_CONFIDENCE"


def test_classification_suggests_generic_profile_not_approved_layout():
    result = classify_document("SAO KE TAI KHOAN LICH SU GIAO DICH NGAN HANG")
    assert result["document_type"] == "BANK_STATEMENT"
    assert result["layout_profile_id"] == "GENERIC_BANK_STATEMENT_PDF"
    assert result["classification_status"] == "SUGGESTED"


def test_native_pdf_text_layer_is_not_misrepresented_as_calibrated_confidence():
    words = _words("Chu tai khoan: Nguyen Van An", confidence=1.0, method="PDF_TEXT_LAYER")
    field = next(x for x in extract_labeled_fields(words) if x["field_name"] == "account_holder_name")
    assert field["confidence"] == 1.0
    assert field["confidence_basis"] == "NATIVE_TEXT_LAYER_UNCALIBRATED"
    assert field["extraction_decision"] == "ABSTAIN"
    assert "CONFIDENCE_NOT_CALIBRATED" in field["abstain_reason"]
    assert field["review_status"] == "NEEDS_REVIEW"
    assert field["extraction_rule_version"]


def test_low_confidence_field_abstains_even_when_value_pattern_matches():
    words = _words("Net salary: 15000000", confidence=FIELD_CONFIDENCE_THRESHOLD - 0.01)
    field = next(x for x in extract_labeled_fields(words) if x["field_name"] == "net_salary")
    assert field["normalized_value"] == {"amount_vnd": "15000000"}
    assert field["extraction_decision"] == "ABSTAIN"
    assert "LOW_CONFIDENCE" in field["abstain_reason"]


def test_invalid_date_is_abstained_not_silently_normalized():
    words = _words("Payment date: 31/02/2026")
    field = next(x for x in extract_labeled_fields(words) if x["field_name"] == "payment_date")
    assert field["validation_status"] == "INVALID_FORMAT"
    assert field["normalized_value"] is None
    assert field["extraction_decision"] == "ABSTAIN"
    assert "INVALID_FORMAT" in field["abstain_reason"]


def test_valid_date_is_normalized_but_remains_suggestion_only():
    words = _words("Payment date: 28/02/2026")
    field = next(x for x in extract_labeled_fields(words) if x["field_name"] == "payment_date")
    assert field["validation_status"] == "VALID"
    assert field["normalized_value"] == {"date": "2026-02-28"}
    assert field["extraction_decision"] == "SUGGEST"
    assert field["review_status"] == "SUGGESTED"


def test_unanchored_candidate_abstains_and_never_fabricates_bbox():
    words = [{"text": "Net", "confidence": .99, "page_number": 1,
              "coordinate_space": "IMAGE_PIXEL", "extraction_method": "TESSERACT_OCR"},
             {"text": "salary:", "confidence": .99, "page_number": 1,
              "coordinate_space": "IMAGE_PIXEL", "extraction_method": "TESSERACT_OCR"},
             {"text": "15000000", "confidence": .99, "page_number": 1,
              "coordinate_space": "IMAGE_PIXEL", "extraction_method": "TESSERACT_OCR"}]
    field = next(x for x in extract_labeled_fields(words) if x["field_name"] == "net_salary")
    assert field["bbox"] is None
    assert field["extraction_decision"] == "ABSTAIN"
    assert "SOURCE_ANCHOR_NOT_FOUND" in field["abstain_reason"]


def test_v12_extraction_governance_columns_are_mapped():
    columns = set(models.Base.metadata.tables["extracted_fields"].columns.keys())
    assert {
        "confidence_basis", "validation_status", "extraction_decision",
        "abstain_reason", "extraction_rule_version",
    } <= columns


def test_field_catalog_does_not_mark_any_field_required_without_signoff():
    catalog = get_ocr_catalog()
    assert all(item["required"] is None for item in catalog["field_catalog"])
