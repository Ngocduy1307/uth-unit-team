"""Create reviewable duplicate-pair candidates for already-imported transactions.

Dry run by default. Execute only after V13 migration and after reviewing counts:
  python scripts/backfill_duplicate_candidates.py
  python scripts/backfill_duplicate_candidates.py --apply
  python scripts/backfill_duplicate_candidates.py --apply --case-id <UUID>

No transaction is removed, hidden, or marked ineligible by this script.
"""
from __future__ import annotations

import argparse
import uuid
from app.database import get_session_factory
from app import models
from app.evidence_reconciliation import build_duplicate_pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist duplicate candidates")
    parser.add_argument("--case-id", help="limit to one case UUID")
    args = parser.parse_args()

    factory = get_session_factory()
    with factory() as db:
        case_query = db.query(models.Case).order_by(models.Case.created_at.asc())
        if args.case_id:
            case_query = case_query.filter(models.Case.id == uuid.UUID(args.case_id))
        cases = case_query.all()
        created_total = 0
        truncated_total = 0
        for case in cases:
            transactions = (db.query(models.Transaction).filter_by(case_id=case.id)
                            .order_by(models.Transaction.transaction_date.asc(), models.Transaction.source_row.asc(),
                                      models.Transaction.id.asc()).all())
            candidates, truncated = build_duplicate_pairs(case.id, transactions)
            existing_keys = {x.candidate_key for x in db.query(models.TransactionDuplicateCandidate)
                             .filter_by(case_id=case.id).all()}
            pending = [x for x in candidates if x["candidate_key"] not in existing_keys]
            truncated_total += truncated
            print(f"case={case.id} transactions={len(transactions)} candidates={len(pending)} fanout_truncated={truncated}")
            if args.apply and pending:
                try:
                    for item in pending:
                        db.add(models.TransactionDuplicateCandidate(
                            case_id=case.id,
                            left_transaction_id=uuid.UUID(item["left_transaction_id"]),
                            right_transaction_id=uuid.UUID(item["right_transaction_id"]),
                            fingerprint_sha256=item["fingerprint_sha256"],
                            candidate_key=item["candidate_key"],
                            match_reasons=item["match_reasons"],
                            review_status="PENDING_REVIEW",
                        ))
                    db.commit()
                    created_total += len(pending)
                except Exception:
                    db.rollback()
                    raise
        print(f"cases_scanned={len(cases)} created_candidates={created_total} fanout_truncated={truncated_total} apply={args.apply}")
        if not args.apply:
            print("DRY RUN ONLY: run with --apply after V13, backup and review of candidate volumes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
