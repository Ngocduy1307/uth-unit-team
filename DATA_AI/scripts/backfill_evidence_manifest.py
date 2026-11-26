"""Backfill V13 manifest entries for legacy documents without mutating files.

Run from DATA_AI with:
  python scripts/backfill_evidence_manifest.py             # dry run
  python scripts/backfill_evidence_manifest.py --apply     # persist append-only entries

The script locks each case while assigning its sequence and chain. Backfilled
records are explicitly attributed to LEGACY_BACKFILL, not to the original
uploader, because historical actor attribution may not exist.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from app.database import get_session_factory
from app import models, service


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist backfilled manifest entries")
    parser.add_argument("--case-id", help="limit to one case UUID")
    args = parser.parse_args()

    factory = get_session_factory()
    with factory() as db:
        query = db.query(models.Case).order_by(models.Case.created_at.asc())
        if args.case_id:
            query = query.filter(models.Case.id == args.case_id)
        cases = query.all()
        total_missing = 0
        for case in cases:
            documents = (db.query(models.Document).filter_by(case_id=case.id)
                         .order_by(models.Document.created_at.asc(), models.Document.id.asc()).all())
            manifested = {x.document_id for x in db.query(models.EvidenceManifestEntry).filter_by(case_id=case.id).all()}
            missing = [doc for doc in documents if doc.id not in manifested]
            if not missing:
                continue
            total_missing += len(missing)
            eligible = []
            blocked = []
            for doc in missing:
                path = Path(doc.stored_path)
                if not path.is_file():
                    blocked.append((doc.id, "STORAGE_OBJECT_MISSING"))
                elif service.sha256_file(path).lower() != doc.sha256.lower():
                    blocked.append((doc.id, "STORAGE_HASH_MISMATCH"))
                else:
                    eligible.append(doc)
            print(f"case={case.id} existing={len(manifested)} missing={len(missing)} eligible={len(eligible)} blocked={len(blocked)}")
            for doc_id, reason in blocked:
                print(f"  BLOCKED document={doc_id} reason={reason}")
            if args.apply and eligible:
                try:
                    for doc in eligible:
                        service.append_evidence_manifest_entry(db, case, doc, "LEGACY_BACKFILL")
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
        print(f"cases_scanned={len(cases)} legacy_documents_missing_manifest={total_missing} apply={args.apply}")
        if not args.apply:
            print("DRY RUN ONLY: pass --apply after backup, review and V13 migration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
