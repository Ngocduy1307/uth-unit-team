import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test-export.db")
from io import BytesIO
from openpyxl import load_workbook
from app.export_service import _safe_cell, build_data_workbook

class EmptyQuery:
    def filter(self, *args, **kwargs): return self
    def order_by(self, *args, **kwargs): return self
    def all(self): return []

class EmptySession:
    def query(self, *args, **kwargs): return EmptyQuery()


def test_excel_formula_injection_is_escaped():
    assert _safe_cell("=HYPERLINK(\"https://bad\")").startswith("'")
    assert _safe_cell("ordinary text") == "ordinary text"
    assert _safe_cell(None) is None


def test_workbook_contains_both_customer_and_data_ai_sheets():
    stream, counts = build_data_workbook(EmptySession(), "BANK-TEST")
    wb = load_workbook(BytesIO(stream.getvalue()), read_only=True)
    expected = {
        "Cases", "Applicant Submissions", "Applicant Form Data", "Documents",
        "Customers", "Customer Addresses", "Customer Employment", "Loan Applications",
        "Extracted Fields", "Transactions", "Processing Summary", "Pipeline Runs",
        "Source Inventory", "Field Mapping", "Data Quality",
        "Payroll Evidence", "Earning Match Candidates", "Income Ledger"
    }
    assert expected.issubset(set(wb.sheetnames))
    assert "Applicant Form Data" in counts
