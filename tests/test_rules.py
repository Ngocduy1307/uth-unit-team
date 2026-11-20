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
