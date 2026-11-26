from app.normalizer import parse_vnd, normalize_date
from app.classifier import classify_transaction

def test_parse_vnd():
    assert str(parse_vnd("18.500.000")) == "18500000"
    assert str(parse_vnd("18,50")) == "18.50"

def test_date():
    assert normalize_date("31/10/2026") == "2026-10-31"

def test_borrowing_is_not_income():
    category, confidence, eligible = classify_transaction("GIAI NGAN KHOAN VAY", 10000000, "CREDIT")
    assert category == "borrowing"
    assert eligible is False

def test_unknown_credit_not_income():
    category, confidence, eligible = classify_transaction("NOI DUNG KHONG RO", 1000000, "CREDIT")
    assert category == "unknown"
    assert eligible is False


def test_document_family_classifier_is_suggestion_only():
    from app.document_intelligence import classify_document
    result = classify_document("NGAN HANG ABC SAO KE TAI KHOAN LICH SU GIAO DICH")
    assert result["document_type"] == "BANK_STATEMENT"
    assert result["classification_status"] == "SUGGESTED"
    assert result["layout_code"] == "GENERIC_BANK_STATEMENT"


def test_unknown_document_is_not_forced_into_a_family():
    from app.document_intelligence import classify_document
    result = classify_document("noi dung khong lien quan")
    assert result["document_type"] == "UNKNOWN"
    assert result["confidence"] == 0


def test_labeled_field_extraction_keeps_source_anchor():
    from app.document_intelligence import extract_labeled_fields
    words = []
    for i, token in enumerate("Chu tai khoan: Nguyen Van An".split()):
        words.append({"text": token, "confidence": .95, "page_number": 1,
                      "bbox": {"x": i * 10, "y": 20, "width": 8, "height": 10}})
    fields = extract_labeled_fields(words)
    holder = next(x for x in fields if x["field_name"] == "account_holder_name")
    assert "Nguyen" in holder["raw_value"]
    assert holder["page_number"] == 1
    assert holder["bbox"]["width"] > 0


def test_field_extraction_does_not_invent_missing_values():
    from app.document_intelligence import extract_labeled_fields
    words = [{"text": "Noi dung giao dich", "confidence": .99, "page_number": 1,
              "bbox": {"x": 0, "y": 0, "width": 20, "height": 10}}]
    assert extract_labeled_fields(words) == []


def test_payroll_matching_is_suggestion_and_requires_exact_amount():
    from datetime import date
    from decimal import Decimal
    from app.ledger import payroll_transaction_match_score
    score, reasons = payroll_transaction_match_score(
        Decimal("15000000"), date(2026, 10, 5), Decimal("15000000"), date(2026, 10, 7))
    assert score > 0
    assert "EXACT_AMOUNT" in reasons
    mismatch, _ = payroll_transaction_match_score(
        Decimal("15000000"), date(2026, 10, 5), Decimal("14000000"), date(2026, 10, 5))
    assert mismatch == 0


def test_digital_pdf_uses_native_text_layer_without_ocr(tmp_path, monkeypatch):
    import fitz
    from app import ocr

    pdf_path = tmp_path / "statement.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Chu tai khoan: Nguyen Van An")
    pdf.save(pdf_path)
    pdf.close()

    def fail_ocr(*args, **kwargs):
        raise AssertionError("OCR should not run for a page with a usable native text layer")

    monkeypatch.setattr(ocr, "_ocr_image", fail_ocr)
    words, page_count = ocr.extract_words(pdf_path)
    assert page_count == 1
    assert "Nguyen" in " ".join(w["text"] for w in words)
    assert all(w["extraction_method"] == "PDF_TEXT_LAYER" for w in words)
    assert all(w["coordinate_space"] == "PDF_POINT" for w in words)


def test_encrypted_pdf_is_rejected(tmp_path):
    import fitz
    from app.ocr import extract_words

    pdf_path = tmp_path / "encrypted.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(pdf_path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    pdf.close()
    try:
        extract_words(pdf_path)
        assert False, "Encrypted PDF must be rejected for controlled handling"
    except ValueError as exc:
        assert "mã hóa" in str(exc)


def test_field_extraction_preserves_coordinate_provenance():
    from app.document_intelligence import extract_labeled_fields
    words = []
    for i, token in enumerate("Chu tai khoan: Nguyen Van An".split()):
        words.append({"text": token, "confidence": .99, "page_number": 1,
                      "bbox": {"x": i * 10, "y": 20, "width": 8, "height": 10},
                      "coordinate_space": "PDF_POINT", "extraction_method": "PDF_TEXT_LAYER"})
    holder = next(x for x in extract_labeled_fields(words) if x["field_name"] == "account_holder_name")
    assert holder["coordinate_space"] == "PDF_POINT"
    assert holder["extraction_method"] == "PDF_TEXT_LAYER"
