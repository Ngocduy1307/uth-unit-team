from __future__ import annotations
import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session
from app import models
from app.config import settings


def _safe_cell(value):
    """Prevent spreadsheet formula injection in untrusted customer/source strings."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (datetime, date, Decimal, int, float, bool)):
        return value
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _add_sheet(wb, title, headers, rows, row_counts):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    limit = settings.export_max_rows_per_sheet
    count = 0
    for row in rows:
        if count >= limit:
            ws.append([f"TRUNCATED: export row limit {limit} reached. Refine export filters."] + [None] * (len(headers)-1))
            row_counts[f"{title}__truncated"] = True
            break
        ws.append([_safe_cell(v) for v in row])
        count += 1
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col_idx, column in enumerate(ws.columns, start=1):
        values = [len(str(c.value or "")) for c in list(column)[:200]]
        width = min(max(max(values or [10]) + 2, 12), 42)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    row_counts[title] = count
    return ws


def build_data_workbook(db: Session, bank_id: str, case_id: UUID | None = None):
    cases_q = db.query(models.Case).filter(models.Case.bank_id == bank_id)
    if case_id:
        cases_q = cases_q.filter(models.Case.id == case_id)
    cases = cases_q.order_by(models.Case.created_at).all()
    case_ids = [c.id for c in cases]
    wb = Workbook()
    wb.remove(wb.active)
    counts = {}

    _add_sheet(wb, "Cases", ["case_id", "external_case_id", "bank_id", "analysis_date", "status", "created_at"],
        ((c.id, c.external_case_id, c.bank_id, c.analysis_date, c.status, c.created_at) for c in cases), counts)

    customer_ids = list({c.customer_id for c in cases if getattr(c, "customer_id", None)})
    customers = db.query(models.CustomerProfile).filter(models.CustomerProfile.id.in_(customer_ids)).all() if customer_ids else []
    _add_sheet(wb, "Customers", ["customer_id", "customer_code", "full_name", "date_of_birth", "gender", "nationality", "phone", "email", "identity_type", "identity_last4", "marital_status", "dependents_count", "preferred_contact_method", "customer_status", "created_at", "updated_at"],
        ((c.id,c.customer_code,c.full_name,c.date_of_birth,c.gender,c.nationality,c.phone,c.email,c.identity_type,c.identity_last4,c.marital_status,c.dependents_count,c.preferred_contact_method,c.customer_status,c.created_at,c.updated_at) for c in customers), counts)
    addresses = db.query(models.CustomerAddress).filter(models.CustomerAddress.customer_id.in_(customer_ids)).all() if customer_ids else []
    _add_sheet(wb, "Customer Addresses", ["address_id", "customer_id", "address_type", "country_code", "province_code", "province_name", "district_name", "ward_name", "street_address", "is_primary"],
        ((a.id,a.customer_id,a.address_type,a.country_code,a.province_code,a.province_name,a.district_name,a.ward_name,a.street_address,a.is_primary) for a in addresses), counts)
    employments = db.query(models.CustomerEmployment).filter(models.CustomerEmployment.customer_id.in_(customer_ids)).all() if customer_ids else []
    _add_sheet(wb, "Customer Employment", ["employment_id", "customer_id", "employment_type", "employer_name", "employer_tax_code", "job_title", "industry", "work_phone", "work_address", "start_date", "end_date", "monthly_income_declared", "income_currency", "is_current"],
        ((e.id,e.customer_id,e.employment_type,e.employer_name,e.employer_tax_code,e.job_title,e.industry,e.work_phone,e.work_address,e.start_date,e.end_date,e.monthly_income_declared,e.income_currency,e.is_current) for e in employments), counts)
    applications = db.query(models.LoanApplication).filter(models.LoanApplication.case_id.in_(case_ids)).all() if case_ids else []
    _add_sheet(wb, "Loan Applications", ["application_id", "case_id", "customer_id", "product_code", "requested_amount", "requested_term_months", "loan_purpose", "preferred_account_last4", "application_status", "submitted_at", "updated_at"],
        ((a.id,a.case_id,a.customer_id,a.product_code,a.requested_amount,a.requested_term_months,a.loan_purpose,a.preferred_disbursement_account_last4,a.application_status,a.submitted_at,a.updated_at) for a in applications), counts)

    submissions = db.query(models.ApplicantSubmission).filter(models.ApplicantSubmission.case_id.in_(case_ids)).order_by(models.ApplicantSubmission.submitted_at).all() if case_ids else []
    _add_sheet(wb, "Applicant Submissions", ["submission_id", "case_id", "applicant_ref", "form_version", "consent_reference", "submitted_by", "submitted_at"],
        ((s.id, s.case_id, s.applicant_ref, s.form_version, s.consent_reference, s.submitted_by, s.submitted_at) for s in submissions), counts)
    form_rows = []
    for s in submissions:
        for key, value in (s.form_data or {}).items():
            form_rows.append((s.case_id, s.applicant_ref, s.form_version, key, value))
    _add_sheet(wb, "Applicant Form Data", ["case_id", "applicant_ref", "form_version", "field_name", "field_value"], form_rows, counts)

    docs = db.query(models.Document).filter(models.Document.case_id.in_(case_ids)).order_by(models.Document.created_at).all() if case_ids else []
    _add_sheet(wb, "Documents", ["document_id", "case_id", "filename", "mime_type", "file_size_bytes", "sha256", "document_type", "layout_code", "evidence_status", "processing_status", "page_count", "created_at"],
        ((d.id,d.case_id,d.original_filename,d.mime_type,d.file_size,d.sha256,d.document_type,d.layout_code,d.evidence_status,d.processing_status,d.page_count,d.created_at) for d in docs), counts)
    doc_ids = [d.id for d in docs]
    fields = db.query(models.ExtractedField).filter(models.ExtractedField.document_id.in_(doc_ids)).order_by(models.ExtractedField.created_at).all() if doc_ids else []
    _add_sheet(wb, "Extracted Fields", ["field_id", "document_id", "field_name", "raw_value", "normalized_value", "confidence", "page_number", "bbox", "source_line", "review_status", "created_at"],
        ((f.id,f.document_id,f.field_name,f.raw_value,f.normalized_value,f.confidence,f.page_number,f.bbox,f.source_line,f.review_status,f.created_at) for f in fields), counts)

    txs = db.query(models.Transaction).filter(models.Transaction.case_id.in_(case_ids)).order_by(models.Transaction.case_id, models.Transaction.source_row).all() if case_ids else []
    _add_sheet(wb, "Transactions", ["transaction_id", "case_id", "document_id", "source_row", "transaction_date", "description", "amount_vnd", "direction", "category", "classification_confidence", "is_income_eligible", "review_status", "created_at"],
        ((t.id,t.case_id,t.document_id,t.source_row,t.transaction_date,t.description,t.amount_vnd,t.direction,t.category,t.classification_confidence,t.is_income_eligible,t.review_status,t.created_at) for t in txs), counts)

    case_set = set(case_ids)
    processing = db.query(models.ProcessingResult).filter(models.ProcessingResult.case_id.in_(case_ids)).order_by(models.ProcessingResult.created_at).all() if case_ids else []
    _add_sheet(wb, "Processing Summary", ["result_id", "case_id", "document_id", "pipeline_version", "result_status", "summary", "error_message", "created_at"],
        ((p.id,p.case_id,p.document_id,p.pipeline_version,p.result_status,p.summary,p.error_message,p.created_at) for p in processing), counts)

    pipeline_runs = db.query(models.PipelineRun).filter(models.PipelineRun.case_id.in_(case_ids)).order_by(models.PipelineRun.started_at).all() if case_ids else []
    _add_sheet(wb, "Pipeline Runs", ["run_id", "case_id", "document_id", "idempotency_key", "pipeline_version", "status", "started_at", "completed_at", "metrics"],
        ((r.id,r.case_id,r.document_id,r.idempotency_key,r.pipeline_version,r.status,r.started_at,r.completed_at,r.metrics) for r in pipeline_runs), counts)

    sources = db.query(models.SourceInventory).order_by(models.SourceInventory.source_code).all()
    _add_sheet(wb, "Source Inventory", ["source_id", "source_code", "source_name", "source_type", "schema_version", "approval_status", "config", "created_at"],
        ((r.id,r.source_code,r.source_name,r.source_type,r.schema_version,r.approval_status,r.config,r.created_at) for r in sources), counts)
    mappings = db.query(models.FieldMappingRegistry).order_by(models.FieldMappingRegistry.source_code, models.FieldMappingRegistry.source_field).all()
    _add_sheet(wb, "Field Mapping", ["mapping_id", "source_code", "schema_version", "source_field", "target_field", "transform_code", "is_required", "approval_status"],
        ((r.id,r.source_code,r.schema_version,r.source_field,r.target_field,r.transform_code,r.is_required,r.approval_status) for r in mappings), counts)

    quality = db.query(models.DataQualityIssue).filter(models.DataQualityIssue.case_id.in_(case_ids)).order_by(models.DataQualityIssue.created_at).all() if case_ids and hasattr(models, "DataQualityIssue") else []
    _add_sheet(wb, "Data Quality", ["issue_id", "case_id", "document_id", "issue_code", "severity", "description", "source_anchor", "issue_status", "created_at", "resolved_at"],
        ((q.id,q.case_id,q.document_id,q.issue_code,q.severity,q.description,q.source_anchor,q.issue_status,q.created_at,q.resolved_at) for q in quality), counts)

    payroll = db.query(models.PayrollEvidence).filter(models.PayrollEvidence.case_id.in_(case_ids)).order_by(models.PayrollEvidence.created_at).all() if case_ids and hasattr(models, "PayrollEvidence") else []
    _add_sheet(wb, "Payroll Evidence", ["payroll_evidence_id", "case_id", "document_id", "pay_period_start", "pay_period_end", "payment_date", "gross_amount", "net_amount", "currency", "evidence_status", "source_anchor", "created_at"],
        ((p.id,p.case_id,p.document_id,p.pay_period_start,p.pay_period_end,p.payment_date,p.gross_amount,p.net_amount,p.currency,p.evidence_status,p.source_anchor,p.created_at) for p in payroll), counts)

    matches = db.query(models.EarningMatchCandidate).filter(models.EarningMatchCandidate.case_id.in_(case_ids)).order_by(models.EarningMatchCandidate.created_at).all() if case_ids else []
    _add_sheet(wb, "Earning Match Candidates", ["candidate_id", "case_id", "payroll_evidence_id", "transaction_id", "similarity_score", "match_reasons", "review_status", "created_at"],
        ((m.id,m.case_id,m.payroll_evidence_id,m.transaction_id,m.similarity_score,m.match_reasons,m.review_status,m.created_at) for m in matches), counts)

    ledgers = db.query(models.IncomeLedgerMonth).filter(models.IncomeLedgerMonth.case_id.in_(case_ids)).order_by(models.IncomeLedgerMonth.period_month).all() if case_ids and hasattr(models, "IncomeLedgerMonth") else []
    _add_sheet(wb, "Income Ledger", ["ledger_id", "case_id", "period_month", "observed_amount", "accepted_amount", "excluded_amount", "month_status", "exclusion_reasons", "reviewed_by", "reviewed_at"],
        ((l.id,l.case_id,l.period_month,l.observed_amount,l.accepted_amount,l.excluded_amount,l.month_status,l.exclusion_reasons,l.reviewed_by,l.reviewed_at) for l in ledgers), counts)

    truncated = [name[:-11] for name, value in counts.items() if name.endswith("__truncated") and value]
    if truncated:
        _add_sheet(wb, "Export Notices", ["notice_type", "affected_sheet", "message"],
            (("ROW_LIMIT_REACHED", name, f"Sheet exceeded {settings.export_max_rows_per_sheet} rows. Export was visibly marked; apply narrower filters to retrieve all rows in separate exports.") for name in truncated), counts)
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output, counts
