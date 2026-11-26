"""V10.0 DATA-AI input readiness and Financial Engine handoff.

This module assembles evidence-backed inputs only. It does NOT compute eligible
income, expense floors, debt consolidation, proposed installments, residual,
DSR, stress results, policy labels or credit decisions.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.governance import assess_snapshot_readiness, build_case_snapshot


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_json(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _validate_iso_date(value: Any, field: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO YYYY-MM-DD date") from exc


def _validate_vnd_amount(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required; missing values must not be replaced with zero")
        return None
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be a decimal VND amount") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError(f"{field} must be a finite non-negative VND amount with at most two decimal places")
    return format(amount, "f")


def validate_declaration_payload(section: str, payload: dict) -> dict:
    """Strictly validate the Backend's versioned customer-declaration shape.

    Do not infer zero for omitted/NULL amounts, and never accept a full salary
    account number in the declaration API; the immutable source document and
    string OCR field retain original identifiers including leading zeros.
    """
    section = section.upper()
    if not isinstance(payload, dict) or not payload:
        raise ValueError("declaration payload must be a non-empty JSON object")

    if section == "HOUSEHOLD":
        allowed = {"household_size", "dependents_count", "housing_status", "residence_since", "household_notes"}
        if set(payload) - allowed:
            raise ValueError("HOUSEHOLD contains unsupported fields")
        household = payload.get("household_size")
        dependents = payload.get("dependents_count")
        if not isinstance(household, int) or isinstance(household, bool) or not 1 <= household <= 30:
            raise ValueError("household_size must be an integer from 1 to 30")
        if not isinstance(dependents, int) or isinstance(dependents, bool) or not 0 <= dependents <= household:
            raise ValueError("dependents_count must be an integer between 0 and household_size")
        result = dict(payload)
        if result.get("residence_since") is not None:
            result["residence_since"] = _validate_iso_date(result["residence_since"], "residence_since")
        if result.get("household_notes") is not None:
            result["household_notes"] = str(result["household_notes"])[:1000]
        return result

    if section == "EMPLOYMENT":
        allowed = {"employment_type", "employer_name", "employer_tax_code", "job_title", "industry",
                   "start_date", "end_date", "is_current", "monthly_income_declared", "income_basis", "currency"}
        if set(payload) - allowed:
            raise ValueError("EMPLOYMENT contains unsupported fields")
        if payload.get("employment_type") != "SALARIED":
            raise ValueError("Only SALARIED employment is supported by the approved product scope")
        if payload.get("currency", "VND") != "VND":
            raise ValueError("Only VND salary declarations are in scope")
        if payload.get("income_basis") not in {"NET", "GROSS"}:
            raise ValueError("income_basis must explicitly be NET or GROSS")
        if payload.get("is_current") is not True:
            raise ValueError("Current salaried employment is required in this scope")
        result = dict(payload)
        result["currency"] = "VND"
        if result.get("monthly_income_declared") is not None:
            result["monthly_income_declared"] = _validate_vnd_amount(result["monthly_income_declared"], "monthly_income_declared", required=True)
            if Decimal(result["monthly_income_declared"]) <= 0:
                raise ValueError("monthly_income_declared must be greater than zero when supplied")
        for key in ("start_date", "end_date"):
            if result.get(key) is not None:
                result[key] = _validate_iso_date(result[key], key)
        for key in ("employer_name", "employer_tax_code", "job_title", "industry"):
            if result.get(key) is not None:
                result[key] = str(result[key]).strip()[:200]
        return result

    if section in {"EXPENSES", "LIABILITIES"}:
        allowed_top = {"answer", "items"}
        if set(payload) - allowed_top or payload.get("answer") not in {"HAS_ITEMS", "NONE"}:
            raise ValueError(f"{section} must explicitly declare answer=HAS_ITEMS or NONE")
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > 50:
            raise ValueError(f"{section}.items must be a list of at most 50 items")
        if payload["answer"] == "NONE" and items:
            raise ValueError(f"{section} answer NONE must have an empty items list")
        if payload["answer"] == "HAS_ITEMS" and not items:
            raise ValueError(f"{section} answer HAS_ITEMS must include at least one item")
        normalized_items = []
        if section == "EXPENSES":
            allowed_item = {"category", "amount_vnd", "frequency", "description"}
            for item in items:
                if not isinstance(item, dict) or set(item) - allowed_item:
                    raise ValueError("EXPENSES item contains unsupported fields")
                category = str(item.get("category", "")).strip().upper()
                if not category or len(category) > 40:
                    raise ValueError("EXPENSES item category is required")
                frequency = str(item.get("frequency", "MONTHLY")).upper()
                if frequency not in {"MONTHLY", "WEEKLY", "ANNUAL", "ONE_OFF"}:
                    raise ValueError("EXPENSES frequency is invalid")
                normalized_items.append({"category": category,
                    "amount_vnd": _validate_vnd_amount(item.get("amount_vnd"), "amount_vnd"),
                    "frequency": frequency, "description": str(item.get("description") or "")[:500]})
        else:
            allowed_item = {"liability_type", "creditor_ref_last4", "outstanding_balance_vnd",
                            "monthly_payment_vnd", "due_day", "start_date", "expected_end_date",
                            "is_overdue", "overdue_amount_vnd"}
            for item in items:
                if not isinstance(item, dict) or set(item) - allowed_item:
                    raise ValueError("LIABILITIES item contains unsupported fields")
                kind = str(item.get("liability_type", "")).strip().upper()
                if not kind or len(kind) > 40:
                    raise ValueError("LIABILITIES item liability_type is required")
                last4 = item.get("creditor_ref_last4")
                if last4 is not None and (not isinstance(last4, str) or not __import__("re").fullmatch(r"\d{4}", last4)):
                    raise ValueError("creditor_ref_last4 must be a four-character string; leading zeros are preserved")
                row = {"liability_type": kind, "creditor_ref_last4": last4,
                    "outstanding_balance_vnd": _validate_vnd_amount(item.get("outstanding_balance_vnd"), "outstanding_balance_vnd"),
                    "monthly_payment_vnd": _validate_vnd_amount(item.get("monthly_payment_vnd"), "monthly_payment_vnd"),
                    "due_day": item.get("due_day"), "is_overdue": item.get("is_overdue"),
                    "overdue_amount_vnd": _validate_vnd_amount(item.get("overdue_amount_vnd"), "overdue_amount_vnd")}
                if row["due_day"] is not None and (not isinstance(row["due_day"], int) or not 1 <= row["due_day"] <= 31):
                    raise ValueError("due_day must be between 1 and 31")
                for key in ("start_date", "expected_end_date"):
                    if item.get(key) is not None:
                        row[key] = _validate_iso_date(item[key], key)
                normalized_items.append(row)
        return {"answer": payload["answer"], "items": normalized_items}

    if section == "SALARY_ACCOUNTS":
        if set(payload) != {"accounts"} or not isinstance(payload.get("accounts"), list):
            raise ValueError("SALARY_ACCOUNTS must contain only an accounts list")
        accounts = payload["accounts"]
        if not 1 <= len(accounts) <= 3:
            raise ValueError("Between one and three salary accounts must be declared")
        allowed_account = {"bank_name", "bank_code", "account_holder_name", "account_number_last4",
                           "currency", "statement_start", "statement_end", "evidence_document_id"}
        normalized_accounts = []
        for account in accounts:
            if not isinstance(account, dict) or set(account) - allowed_account:
                raise ValueError("SALARY_ACCOUNTS account has unsupported fields; full account numbers are not accepted")
            if not account.get("bank_name") or account.get("currency", "VND") != "VND":
                raise ValueError("Salary account bank_name and VND currency are required")
            last4 = account.get("account_number_last4")
            if not isinstance(last4, str) or not __import__("re").fullmatch(r"\d{4}", last4):
                raise ValueError("account_number_last4 must be a four-character string; leading zeros are preserved")
            start = _validate_iso_date(account.get("statement_start"), "statement_start")
            end = _validate_iso_date(account.get("statement_end"), "statement_end")
            if start > end:
                raise ValueError("statement_start must not be after statement_end")
            try:
                evidence_id = str(UUID(str(account.get("evidence_document_id"))))
            except (TypeError, ValueError) as exc:
                raise ValueError("evidence_document_id is required for each salary account") from exc
            normalized_accounts.append({"bank_name": str(account["bank_name"]).strip()[:160],
                "bank_code": str(account.get("bank_code") or "")[:30],
                "account_holder_name": str(account.get("account_holder_name") or "")[:200],
                "account_number_last4": last4, "currency": "VND",
                "statement_start": start, "statement_end": end, "evidence_document_id": evidence_id,
                "ownership_status": "UNVERIFIED"})
        return {"accounts": normalized_accounts}

    raise ValueError("Unsupported declaration section")


def latest_attestation(db: Session, case_id):
    return (db.query(models.CaseScopeConsentAttestation)
            .filter_by(case_id=case_id)
            .order_by(models.CaseScopeConsentAttestation.attested_at.desc(),
                      models.CaseScopeConsentAttestation.id.desc()).first())


def latest_declarations(db: Session, case_id) -> dict[str, models.CaseInputDeclarationRevision]:
    rows = (db.query(models.CaseInputDeclarationRevision)
            .filter_by(case_id=case_id)
            .order_by(models.CaseInputDeclarationRevision.section_code,
                      models.CaseInputDeclarationRevision.revision_no.desc()).all())
    result: dict[str, models.CaseInputDeclarationRevision] = {}
    for row in rows:
        result.setdefault(row.section_code, row)
    return result


def latest_review_map(db: Session, case_id, *, target_type: str | None = None) -> dict[str, models.CaseInputReviewDecision]:
    query = db.query(models.CaseInputReviewDecision).filter_by(case_id=case_id)
    if target_type:
        query = query.filter_by(target_type=target_type)
    rows = query.order_by(models.CaseInputReviewDecision.created_at.desc(),
                          models.CaseInputReviewDecision.id.desc()).all()
    result = {}
    for row in rows:
        result.setdefault(str(row.target_id), row)
    return result


def _six_month_window(case: models.Case) -> list[tuple[date, date]]:
    if not case.analysis_date:
        return []
    anchor = case.analysis_date.date() if isinstance(case.analysis_date, datetime) else case.analysis_date
    year, month = anchor.year, anchor.month
    result = []
    for offset in range(5, -1, -1):
        absolute = year * 12 + (month - 1) - offset
        y, m0 = divmod(absolute, 12)
        m = m0 + 1
        result.append((date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])))
    return result


def _document_is_trusted(doc: models.Document | None, db: Session) -> bool:
    if doc is None or doc.deleted_at is not None or doc.processing_status != "COMPLETED" or doc.malware_scan_status != "CLEAN":
        return False
    if not doc.sha256 or len(doc.sha256) != 64:
        return False
    from pathlib import Path
    stored = Path(doc.stored_path)
    if stored.is_symlink() or not stored.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with stored.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    if digest.hexdigest() != doc.sha256:
        return False
    scan = (db.query(models.DocumentSecurityEvent).filter_by(
        document_id=doc.id, event_type="SCAN_COMPLETED", scan_status="CLEAN",
        scanned_sha256=doc.sha256, attestation_version="V1_CLAMAV", engine_name="ClamAV")
        .filter(models.DocumentSecurityEvent.engine_version.isnot(None)).first())
    manifest = db.query(models.EvidenceManifestEntry).filter_by(case_id=doc.case_id, document_id=doc.id, sha256=doc.sha256).first()
    return scan is not None and manifest is not None


def evaluate_data_readiness(db: Session, case: models.Case) -> dict:
    """Return a deterministic DATA-AI input-readiness view, not credit eligibility."""
    blockers: list[dict] = []
    warnings: list[dict] = []
    attestation = latest_attestation(db, case.id)
    if attestation is None:
        blockers.append({"code": "SCOPE_CONSENT_ATTESTATION_MISSING"})
    else:
        if attestation.scope_status != "IN_SCOPE":
            blockers.append({"code": "CASE_OUT_OF_SCOPE", "scope_status": attestation.scope_status})
        if attestation.consent_status != "GRANTED":
            blockers.append({"code": "CONSENT_NOT_GRANTED", "consent_status": attestation.consent_status})
        if attestation.scope_code != "VN_UNSECURED_SALARIED_VND":
            blockers.append({"code": "PRODUCT_SCOPE_MISMATCH"})

    application = db.query(models.LoanApplication).filter_by(case_id=case.id).first()
    if application is None:
        blockers.append({"code": "LOAN_APPLICATION_MISSING"})
    elif application.requested_term_months < 6 or application.requested_term_months > 36:
        blockers.append({"code": "PRODUCT_TERM_OUT_OF_SCOPE"})
    elif not application.product_code:
        blockers.append({"code": "PRODUCT_CODE_MISSING"})

    declarations = latest_declarations(db, case.id)
    reviews = latest_review_map(db, case.id, target_type="DECLARATION_REVISION")
    required_sections = ("HOUSEHOLD", "EMPLOYMENT", "EXPENSES", "LIABILITIES", "SALARY_ACCOUNTS")
    for section in required_sections:
        revision = declarations.get(section)
        if revision is None:
            blockers.append({"code": "DECLARATION_SECTION_MISSING", "section": section})
            continue
        decision = reviews.get(str(revision.id))
        if decision is None or decision.decision_code != "CONFIRMED":
            blockers.append({"code": "DECLARATION_SECTION_NOT_MAKER_CONFIRMED", "section": section,
                             "revision_id": str(revision.id),
                             "latest_decision": decision.decision_code if decision else None})

    employment = declarations.get("EMPLOYMENT")
    if employment:
        payload = employment.payload
        if payload.get("employment_type") != "SALARIED" or payload.get("currency", "VND") != "VND":
            blockers.append({"code": "EMPLOYMENT_SCOPE_NOT_SALARIED_VND"})
        if payload.get("income_basis") not in {"NET", "GROSS"}:
            blockers.append({"code": "EMPLOYMENT_INCOME_BASIS_MISSING"})

    expense = declarations.get("EXPENSES")
    if expense and expense.payload.get("answer") not in {"HAS_ITEMS", "NONE"}:
        blockers.append({"code": "EXPENSE_DECLARATION_NOT_EXPLICIT"})
    liability = declarations.get("LIABILITIES")
    if liability and liability.payload.get("answer") not in {"HAS_ITEMS", "NONE"}:
        blockers.append({"code": "LIABILITY_DECLARATION_NOT_EXPLICIT"})

    window = _six_month_window(case)
    if not window:
        blockers.append({"code": "ANALYSIS_DATE_MISSING"})
    salary_revision = declarations.get("SALARY_ACCOUNTS")
    accounts = (salary_revision.payload.get("accounts", []) if salary_revision else [])
    if salary_revision:
        salary_review = reviews.get(str(salary_revision.id))
        required_account_evidence = {str(item.get("evidence_document_id")) for item in accounts if item.get("evidence_document_id")}
        confirmed_refs = {str(item.get("document_id")) for item in (salary_review.evidence_refs if salary_review else [])}
        if salary_review is None or salary_review.decision_code != "CONFIRMED" or not required_account_evidence.issubset(confirmed_refs):
            blockers.append({"code": "SALARY_ACCOUNT_OWNERSHIP_AND_PERIOD_NOT_MAKER_VERIFIED",
                             "required_statement_document_ids": sorted(required_account_evidence)})
    if len(accounts) > 3:
        blockers.append({"code": "SALARY_ACCOUNT_LIMIT_EXCEEDED", "maximum": 3})

    documents = {d.id: d for d in db.query(models.Document).filter_by(case_id=case.id).all()}
    pdf_statements = [d for d in documents.values() if d.document_type == "BANK_STATEMENT"
                      and __import__("pathlib").Path(d.original_filename).suffix.lower() == ".pdf"]
    csv_statements = [d for d in documents.values() if d.document_type == "BANK_STATEMENT"
                      and __import__("pathlib").Path(d.original_filename).suffix.lower() == ".csv"]
    reconciliation_runs_for_docs = db.query(models.EvidenceReconciliationRun).filter_by(case_id=case.id).all()
    reconciled_document_ids = {row.pdf_document_id for row in reconciliation_runs_for_docs} | {row.csv_document_id for row in reconciliation_runs_for_docs}
    if pdf_statements and csv_statements:
        unreconciled_sources = [str(doc.id) for doc in (pdf_statements + csv_statements)
                                if doc.id not in reconciled_document_ids]
        if unreconciled_sources:
            blockers.append({"code": "PDF_CSV_RECONCILIATION_PAIR_MISSING",
                             "unreconciled_statement_document_ids": sorted(unreconciled_sources)})
    elif pdf_statements or csv_statements:
        warnings.append({"code": "PDF_CSV_COUNTERPART_NOT_PROVIDED",
                         "pdf_statement_count": len(pdf_statements), "csv_statement_count": len(csv_statements),
                         "note": "DATA-AI will not fabricate or infer a missing statement counterpart."})
    covered_months: list[str] = []
    uncovered_months: list[str] = []
    for month_start, month_end in window:
        month_key = month_start.strftime("%Y-%m")
        covered = False
        for account in accounts:
            try:
                start = date.fromisoformat(str(account.get("statement_start")))
                end = date.fromisoformat(str(account.get("statement_end")))
                evidence_id = UUID(str(account.get("evidence_document_id")))
            except (TypeError, ValueError):
                continue
            doc = documents.get(evidence_id)
            if start <= month_start and end >= month_end and _document_is_trusted(doc, db):
                covered = True
                break
        (covered_months if covered else uncovered_months).append(month_key)
    if window and uncovered_months:
        blockers.append({"code": "SIX_MONTH_STATEMENT_COVERAGE_INCOMPLETE", "missing_months": uncovered_months})

    # Each target month needs a payslip evidence candidate and a Maker-confirmed
    # payroll-to-bank match. Absence is evidence absence, never a zero amount.
    payrolls = db.query(models.PayrollEvidence).filter_by(case_id=case.id).all()
    match_candidates = db.query(models.EarningMatchCandidate).filter_by(case_id=case.id).all()
    match_reviews = latest_review_map(db, case.id, target_type="EARNING_MATCH")
    payroll_reviews = latest_review_map(db, case.id, target_type="PAYROLL_EVIDENCE")
    payroll_by_month: dict[str, list[models.PayrollEvidence]] = {}
    for payroll in payrolls:
        pay_date = payroll.payment_date or payroll.pay_period_end
        if pay_date:
            payroll_by_month.setdefault(pay_date.strftime("%Y-%m"), []).append(payroll)
    missing_payroll, payroll_pending = [], []
    missing_match, match_pending = [], []
    for month_start, _month_end in window:
        key = month_start.strftime("%Y-%m")
        month_payrolls = payroll_by_month.get(key, [])
        if not month_payrolls:
            missing_payroll.append(key)
            missing_match.append(key)
            continue
        confirmed_payrolls = [p for p in month_payrolls
                              if payroll_reviews.get(str(p.id)) and payroll_reviews[str(p.id)].decision_code == "CONFIRMED"]
        if not confirmed_payrolls:
            payroll_pending.append(key)
        confirmed_payroll_ids = {p.id for p in confirmed_payrolls}
        matched = False
        pending_candidate = False
        for candidate in match_candidates:
            if candidate.payroll_evidence_id not in confirmed_payroll_ids:
                continue
            decision = match_reviews.get(str(candidate.id))
            if decision and decision.decision_code == "CONFIRMED":
                matched = True
                break
            if decision is None or decision.decision_code in {"RETURNED", "UNABLE_TO_VERIFY"}:
                pending_candidate = True
        if not matched:
            missing_match.append(key)
            if pending_candidate or confirmed_payrolls:
                match_pending.append(key)
    if missing_payroll:
        blockers.append({"code": "PAYSLIP_EVIDENCE_MISSING", "months": missing_payroll})
    if payroll_pending:
        blockers.append({"code": "PAYSLIP_EVIDENCE_REQUIRES_MAKER_REVIEW", "months": payroll_pending})
    if missing_match:
        blockers.append({"code": "PAYROLL_BANK_MATCH_NOT_CONFIRMED", "months": missing_match})

    # The six-month observed-income ledger is a separate Maker-controlled
    # reconciliation surface. A payslip/match alone must not silently imply
    # that the monthly bank-credit ledger was reviewed.
    ledger_rows = db.query(models.IncomeLedgerMonth).filter_by(case_id=case.id).all()
    ledger_by_month = {row.period_month.strftime("%Y-%m"): row for row in ledger_rows}
    ledger_reviews = latest_review_map(db, case.id, target_type="INCOME_LEDGER")
    missing_ledger_months, ledger_review_pending = [], []
    for month_start, _month_end in window:
        key = month_start.strftime("%Y-%m")
        ledger = ledger_by_month.get(key)
        if ledger is None or ledger.observed_amount is None:
            missing_ledger_months.append(key)
            continue
        decision = ledger_reviews.get(str(ledger.id))
        if decision is None or decision.decision_code != "CONFIRMED":
            ledger_review_pending.append(key)
    if missing_ledger_months:
        blockers.append({"code": "OBSERVED_INCOME_LEDGER_MISSING", "months": missing_ledger_months})
    if ledger_review_pending:
        blockers.append({"code": "INCOME_LEDGER_REQUIRES_MAKER_REVIEW", "months": ledger_review_pending})

    reconciliation_runs = db.query(models.EvidenceReconciliationRun).filter_by(case_id=case.id).all()
    reconciliation_ids = [row.id for row in reconciliation_runs]
    reconciliation_reviews = {}
    if reconciliation_ids:
        review_rows = (db.query(models.EvidenceReviewDecision)
                       .filter(models.EvidenceReviewDecision.case_id == case.id,
                               models.EvidenceReviewDecision.target_type == "RECONCILIATION_RUN",
                               models.EvidenceReviewDecision.target_id.in_(reconciliation_ids))
                       .order_by(models.EvidenceReviewDecision.created_at.desc(), models.EvidenceReviewDecision.id.desc()).all())
        for review in review_rows:
            reconciliation_reviews.setdefault(str(review.target_id), review)
    unreviewed_reconciliations = []
    variance_reconciliations = []
    changed_reconciliation_sources = []
    for run in reconciliation_runs:
        review = reconciliation_reviews.get(str(run.id))
        pdf_source = documents.get(run.pdf_document_id)
        csv_source = documents.get(run.csv_document_id)
        if (pdf_source is None or csv_source is None or pdf_source.sha256 != run.pdf_sha256
                or csv_source.sha256 != run.csv_sha256 or not _document_is_trusted(pdf_source, db)
                or not _document_is_trusted(csv_source, db)):
            changed_reconciliation_sources.append(str(run.id))
        if run.result_status in {"INCOMPLETE", "ABSTAINED"} or review is None or review.decision_code not in {"CONFIRMED_MATCH", "CONFIRMED_VARIANCE"}:
            unreviewed_reconciliations.append(str(run.id))
        elif run.result_status != "BALANCE_MATCH_CANDIDATE" or review.decision_code != "CONFIRMED_MATCH":
            variance_reconciliations.append(str(run.id))
    if changed_reconciliation_sources:
        blockers.append({"code": "PDF_CSV_RECONCILIATION_SOURCE_HASH_OR_TRUST_FAILED",
                         "reconciliation_run_ids": sorted(changed_reconciliation_sources)})
    if unreviewed_reconciliations:
        blockers.append({"code": "PDF_CSV_RECONCILIATION_REQUIRES_MAKER_REVIEW",
                         "reconciliation_run_ids": sorted(unreviewed_reconciliations)})
    if variance_reconciliations:
        blockers.append({"code": "PDF_CSV_RECONCILIATION_VARIANCE_UNRESOLVED",
                         "reconciliation_run_ids": sorted(variance_reconciliations)})

    duplicate_candidates = db.query(models.TransactionDuplicateCandidate).filter_by(case_id=case.id).all()
    duplicate_ids = [row.id for row in duplicate_candidates]
    duplicate_reviews = {}
    if duplicate_ids:
        review_rows = (db.query(models.EvidenceReviewDecision)
                       .filter(models.EvidenceReviewDecision.case_id == case.id,
                               models.EvidenceReviewDecision.target_type == "TRANSACTION_DUPLICATE",
                               models.EvidenceReviewDecision.target_id.in_(duplicate_ids))
                       .order_by(models.EvidenceReviewDecision.created_at.desc(), models.EvidenceReviewDecision.id.desc()).all())
        for review in review_rows:
            duplicate_reviews.setdefault(str(review.target_id), review)
    unresolved_duplicates = [str(candidate.id) for candidate in duplicate_candidates
                             if (duplicate_reviews.get(str(candidate.id)) is None or
                                 duplicate_reviews[str(candidate.id)].decision_code == "NEEDS_MORE_EVIDENCE")]
    if unresolved_duplicates:
        blockers.append({"code": "TRANSACTION_DUPLICATE_CANDIDATES_REQUIRE_MAKER_REVIEW",
                         "candidate_ids": sorted(unresolved_duplicates)})

    snapshot, technical = build_case_snapshot(db, case)
    if not technical.get("review_ready"):
        blockers.append({"code": "TECHNICAL_EVIDENCE_GOVERNANCE_BLOCKED",
                         "technical_blockers": technical.get("blockers", [])})

    # Categorize blockers without weakening them. Insufficient evidence takes
    # precedence over review state; all missing values remain explicit.
    blocker_codes = {item["code"] for item in blockers}
    insufficient_codes = {"SIX_MONTH_STATEMENT_COVERAGE_INCOMPLETE", "PAYSLIP_EVIDENCE_MISSING",
                          "OBSERVED_INCOME_LEDGER_MISSING", "LOAN_APPLICATION_MISSING", "ANALYSIS_DATE_MISSING"}
    recoverable_evidence_codes = {"DECLARATION_SECTION_MISSING", "SIX_MONTH_STATEMENT_COVERAGE_INCOMPLETE",
                                  "PAYSLIP_EVIDENCE_MISSING", "OBSERVED_INCOME_LEDGER_MISSING",
                                  "PDF_CSV_RECONCILIATION_PAIR_MISSING"}
    review_codes = {"DECLARATION_SECTION_NOT_MAKER_CONFIRMED", "SALARY_ACCOUNT_OWNERSHIP_AND_PERIOD_NOT_MAKER_VERIFIED",
                    "PAYSLIP_EVIDENCE_REQUIRES_MAKER_REVIEW", "PAYROLL_BANK_MATCH_NOT_CONFIRMED",
                    "INCOME_LEDGER_REQUIRES_MAKER_REVIEW",
                    "PDF_CSV_RECONCILIATION_PAIR_MISSING", "PDF_CSV_RECONCILIATION_REQUIRES_MAKER_REVIEW",
                    "PDF_CSV_RECONCILIATION_VARIANCE_UNRESOLVED",
                    "TRANSACTION_DUPLICATE_CANDIDATES_REQUIRE_MAKER_REVIEW"}
    if not blockers:
        status = "READY_FOR_BUSINESS_ENGINE"
    elif blocker_codes & insufficient_codes:
        status = "INSUFFICIENT_EVIDENCE"
    elif blocker_codes & review_codes:
        status = "NEEDS_MAKER_REVIEW"
    else:
        status = "BLOCKED"

    if status == "READY_FOR_BUSINESS_ENGINE":
        route_hint = "BUSINESS_ENGINE_HANDOFF"
    elif status == "NEEDS_MAKER_REVIEW":
        route_hint = "MAKER_REVIEW"
    elif status == "INSUFFICIENT_EVIDENCE" and blocker_codes & recoverable_evidence_codes:
        # Advisory only: Camunda/Bank DMN decides whether to request more evidence,
        # start a timer, or close as terminal insufficient evidence.
        route_hint = "AWAITING_EVIDENCE"
    elif status == "INSUFFICIENT_EVIDENCE":
        route_hint = "INSUFFICIENT_EVIDENCE"
    else:
        route_hint = "HOLD"

    if duplicate_candidates:
        warnings.append({"code": "MAKER_DUPLICATE_DECISIONS_RECORDED",
                         "candidate_count": len(duplicate_candidates),
                         "confirmed_duplicate_count": sum(1 for r in duplicate_reviews.values() if r.decision_code == "CONFIRMED_DUPLICATE"),
                         "note": "DATA-AI never deletes or nets duplicate transactions; downstream engine must consume Maker decisions."})
    return {
        "contract_version": "DATA_AI_READINESS_V1",
        "case_id": str(case.id),
        "status": status,
        "workflow_route_hint": route_hint,
        "workflow_route_authority": "CAMUNDA_BANK_DMN_NOT_DATA_AI",
        "ready_for_business_engine": status == "READY_FOR_BUSINESS_ENGINE",
        "scope_status": attestation.scope_status if attestation else None,
        "consent_status": attestation.consent_status if attestation else None,
        "window_months": [start.strftime("%Y-%m") for start, _ in window],
        "covered_statement_months": covered_months,
        "missing_statement_months": uncovered_months,
        "missing_observed_income_ledger_months": missing_ledger_months,
        "income_ledger_maker_review_pending_months": ledger_review_pending,
        "blockers": blockers,
        "warnings": warnings + [{"code": "DATA_AI_BOUNDARY", "message": "DATA-AI does not calculate eligible income, expense floor, debt consolidation, proposed installments, residual, DSR, stress results, policy labels or credit decisions."}],
        "technical_readiness": technical,
        "declaration_revision_ids": {k: str(v.id) for k, v in declarations.items()},
    }


def build_financial_input_payload(db: Session, case: models.Case, readiness: dict) -> dict:
    if readiness["status"] != "READY_FOR_BUSINESS_ENGINE":
        raise HTTPException(409, detail={"message": "Case is not ready for Financial Engine handoff", "readiness": readiness})
    declarations = latest_declarations(db, case.id)
    application = db.query(models.LoanApplication).filter_by(case_id=case.id).first()
    documents = db.query(models.Document).filter_by(case_id=case.id).order_by(models.Document.created_at, models.Document.id).all()
    payrolls = db.query(models.PayrollEvidence).filter_by(case_id=case.id).all()
    ledgers = db.query(models.IncomeLedgerMonth).filter_by(case_id=case.id).order_by(models.IncomeLedgerMonth.period_month).all()
    transactions = db.query(models.Transaction).filter_by(case_id=case.id).order_by(models.Transaction.transaction_date, models.Transaction.source_row).all()
    reviews = db.query(models.CaseInputReviewDecision).filter_by(case_id=case.id).order_by(models.CaseInputReviewDecision.created_at).all()
    reconciliation_runs = db.query(models.EvidenceReconciliationRun).filter_by(case_id=case.id).order_by(models.EvidenceReconciliationRun.created_at).all()
    evidence_reviews = db.query(models.EvidenceReviewDecision).filter_by(case_id=case.id).order_by(models.EvidenceReviewDecision.created_at).all()
    duplicate_candidates = db.query(models.TransactionDuplicateCandidate).filter_by(case_id=case.id).order_by(models.TransactionDuplicateCandidate.created_at).all()

    evidence_rows = [{"document_id": str(d.id), "sha256": d.sha256, "mime_type": d.mime_type,
                      "document_type": d.document_type, "processing_status": d.processing_status,
                      "page_count": d.page_count}
                     for d in documents if d.deleted_at is None]
    payroll_rows = []
    for p in payrolls:
        payroll_rows.append({"payroll_evidence_id": str(p.id), "document_id": str(p.document_id) if p.document_id else None,
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
            "pay_period_start": p.pay_period_start.isoformat() if p.pay_period_start else None,
            "pay_period_end": p.pay_period_end.isoformat() if p.pay_period_end else None,
            "gross_amount_vnd_observed": format(p.gross_amount, "f") if p.gross_amount is not None else None,
            "net_amount_vnd_observed": format(p.net_amount, "f") if p.net_amount is not None else None,
            "currency": p.currency, "evidence_status": p.evidence_status,
            "source_anchor": _json_value(p.source_anchor)})
    tx_rows = [{"transaction_id": str(t.id), "document_id": str(t.document_id) if t.document_id else None,
        "source_row": t.source_row, "transaction_date": t.transaction_date,
        "amount_vnd_observed": format(t.amount_vnd, "f") if t.amount_vnd is not None else None,
        "direction": t.direction, "suggested_category": t.category,
        "classification_confidence": float(t.classification_confidence or 0),
        "review_status": t.review_status} for t in transactions]
    ledger_rows = [{"period_month": l.period_month.isoformat(),
        "observed_amount_vnd": format(l.observed_amount, "f") if l.observed_amount is not None else None,
        "accepted_amount_vnd": format(l.accepted_amount, "f") if l.accepted_amount is not None else None,
        "month_status": l.month_status, "exclusion_reasons": l.exclusion_reasons} for l in ledgers]
    # Minimize direct identifiers in the Financial Engine contract. Source names,
    # employer tax identifiers, account-holder names and free-text notes remain in
    # DATA-AI evidence storage and are retrievable only through authorized case views.
    declaration_rows = {}
    for section, rev in declarations.items():
        raw = _json_value(rev.payload)
        if section == "HOUSEHOLD":
            filtered = {k: raw.get(k) for k in ("household_size", "dependents_count", "housing_status", "residence_since")}
        elif section == "EMPLOYMENT":
            filtered = {k: raw.get(k) for k in ("employment_type", "start_date", "end_date", "is_current", "monthly_income_declared", "income_basis", "currency")}
        elif section in {"EXPENSES", "LIABILITIES"}:
            filtered = raw
            if section == "EXPENSES":
                filtered = {"answer": raw.get("answer"), "items": [
                    {k: item.get(k) for k in ("category", "amount_vnd", "frequency")} for item in raw.get("items", [])]}
            else:
                filtered = {"answer": raw.get("answer"), "items": [
                    {k: item.get(k) for k in ("liability_type", "creditor_ref_last4", "outstanding_balance_vnd", "monthly_payment_vnd", "due_day", "start_date", "expected_end_date", "is_overdue", "overdue_amount_vnd")} for item in raw.get("items", [])]}
        elif section == "SALARY_ACCOUNTS":
            filtered = {"accounts": [{k: item.get(k) for k in ("account_ref_id", "bank_code", "account_number_last4", "currency", "statement_start", "statement_end", "evidence_document_id")} for item in raw.get("accounts", [])]}
        else:
            filtered = {}
        declaration_rows[section] = {"revision_id": str(rev.id), "revision_no": rev.revision_no,
                                     "payload_sha256": rev.payload_sha256, "payload": filtered}
    # Share decision outcomes and evidence pointers with the Financial Engine,
    # but keep free-text reviewer comments and staff identity inside DATA-AI.
    review_rows = [{"review_id": str(r.id), "target_type": r.target_type,
                    "target_id": str(r.target_id), "decision_code": r.decision_code,
                    "created_at": r.created_at.isoformat()} for r in reviews]

    reconciliation_rows = [{"reconciliation_run_id": str(row.id),
        "pdf_document_id": str(row.pdf_document_id), "csv_document_id": str(row.csv_document_id),
        "pdf_sha256": row.pdf_sha256, "csv_sha256": row.csv_sha256,
        "reconciliation_version": row.reconciliation_version, "result_status": row.result_status,
        "summary": _json_value(row.summary)} for row in reconciliation_runs]
    duplicate_rows = [{"candidate_id": str(row.id), "left_transaction_id": str(row.left_transaction_id),
        "right_transaction_id": str(row.right_transaction_id), "fingerprint_sha256": row.fingerprint_sha256,
        "match_reasons": row.match_reasons,
        "maker_decision": next((r.decision_code for r in reversed(evidence_reviews)
                                  if r.target_type == "TRANSACTION_DUPLICATE" and r.target_id == row.id), None)}
        for row in duplicate_candidates]
    evidence_review_rows = [{"id": str(r.id), "target_type": r.target_type, "target_id": str(r.target_id),
        "decision_code": r.decision_code, "reviewer_role": r.reviewer_role,
        "evidence_refs": _json_value(r.evidence_refs),
        "created_at": r.created_at.isoformat()} for r in evidence_reviews]

    return {
        "contract_version": "DATA_AI_FINANCIAL_INPUT_V1",
        "case_id": str(case.id),
        "external_case_id": case.external_case_id,
        "analysis_date": ((case.analysis_date.date() if isinstance(case.analysis_date, datetime)
                           else case.analysis_date).isoformat() if case.analysis_date else None),
        "product_request": {"product_code": application.product_code,
            "requested_amount_vnd": format(application.requested_amount, "f"),
            "requested_term_months": application.requested_term_months,
            "loan_purpose": application.loan_purpose, "currency": "VND"},
        "readiness": readiness,
        "evidence_documents": evidence_rows,
        "declarations": declaration_rows,
        "payroll_evidence_candidates": payroll_rows,
        "observed_income_ledger": ledger_rows,
        "bank_transactions": tx_rows,
        "maker_input_reviews": review_rows,
        "statement_reconciliation_reviews": reconciliation_rows,
        "transaction_duplicate_candidates": duplicate_rows,
        "evidence_review_decisions": evidence_review_rows,
        "non_imputation_policy": {"missing_values_remain_null": True,
                                   "missing_months_are_not_zero": True,
                                   "averages_are_not_imputed": True},
        "decision_boundary": {"authoritative_calculation_owner": "BUSINESS_ENGINE",
                               "data_ai_does_not_calculate": ["eligible_income", "expense_floor", "debt_consolidation",
                                   "repayment_schedule", "residual", "DSR", "stress_scenarios", "policy_outcome", "credit_decision"]},
    }
