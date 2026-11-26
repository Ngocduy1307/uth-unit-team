"""Evidence-ledger helpers. This module never decides eligible/accepted income."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal


def payroll_transaction_match_score(payroll_amount: Decimal | None,
                                    payroll_date: date | None,
                                    transaction_amount: Decimal | None,
                                    transaction_date: date | None) -> tuple[float, list[str]]:
    if payroll_amount is None or transaction_amount is None or payroll_date is None or transaction_date is None:
        return 0.0, ["MISSING_AMOUNT_OR_DATE"]
    if payroll_amount != transaction_amount:
        return 0.0, ["AMOUNT_MISMATCH"]
    day_delta = abs((payroll_date - transaction_date).days)
    if day_delta > 5:
        return 0.0, ["PAYMENT_DATE_OUTSIDE_5_DAY_WINDOW"]
    return max(0.80, 1.0 - day_delta * 0.04), ["EXACT_AMOUNT", f"DATE_DELTA_DAYS:{day_delta}"]


def rebuild_observed_income_ledger(db, case_id) -> int:
    """Upsert monthly observed salary-candidate totals; accepted_amount remains NULL."""
    from app import models
    from sqlalchemy import func

    rows = (db.query(models.Transaction).filter(
        models.Transaction.case_id == case_id,
        models.Transaction.direction == "CREDIT",
        models.Transaction.category == "salary_candidate",
        models.Transaction.review_status != "DUPLICATE",
        models.Transaction.transaction_date.isnot(None),
        models.Transaction.amount_vnd.isnot(None),
    ).all())
    totals: dict[date, Decimal] = defaultdict(Decimal)
    for tx in rows:
        try:
            parsed = date.fromisoformat(tx.transaction_date[:10])
        except (TypeError, ValueError):
            continue
        month = date(parsed.year, parsed.month, 1)
        totals[month] += Decimal(tx.amount_vnd)

    count = 0
    for month, amount in totals.items():
        ledger = db.query(models.IncomeLedgerMonth).filter_by(
            case_id=case_id, period_month=month).first()
        if ledger is None:
            ledger = models.IncomeLedgerMonth(case_id=case_id, period_month=month,
                observed_amount=amount, accepted_amount=None, excluded_amount=None,
                month_status="NEEDS_REVIEW", exclusion_reasons=[])
            db.add(ledger)
        else:
            ledger.observed_amount = amount
            # Never overwrite a reviewer decision or manufacture an accepted amount.
            if ledger.accepted_amount is None:
                ledger.month_status = "NEEDS_REVIEW"
        count += 1
    return count


def generate_payroll_match_candidates(db, case_id) -> int:
    """Suggest exact-amount payroll-to-credit matches; no match is auto-accepted."""
    from app import models
    from datetime import date as date_type

    payroll_items = db.query(models.PayrollEvidence).filter_by(case_id=case_id).all()
    transactions = db.query(models.Transaction).filter_by(case_id=case_id, direction="CREDIT").all()
    created = 0
    for payroll in payroll_items:
        payroll_date = payroll.payment_date or payroll.pay_period_end
        payroll_amount = payroll.net_amount or payroll.gross_amount
        if payroll_date is None or payroll_amount is None:
            continue
        for tx in transactions:
            if tx.amount_vnd is None or not tx.transaction_date:
                continue
            try:
                tx_date = date_type.fromisoformat(tx.transaction_date[:10])
            except ValueError:
                continue
            score, reasons = payroll_transaction_match_score(
                Decimal(payroll_amount), payroll_date, Decimal(tx.amount_vnd), tx_date)
            if score <= 0:
                continue
            exists = db.query(models.EarningMatchCandidate).filter_by(
                payroll_evidence_id=payroll.id, transaction_id=tx.id).first()
            if exists:
                continue
            db.add(models.EarningMatchCandidate(case_id=case_id,
                payroll_evidence_id=payroll.id, transaction_id=tx.id,
                similarity_score=score, match_reasons=reasons, review_status="SUGGESTED"))
            created += 1
    return created
