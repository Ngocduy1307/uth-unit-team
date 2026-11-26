#!/usr/bin/env python3
"""Backfill legacy case AuditEvent rows into the V15 hash-chained audit ledger.

Safe by default: prints the number of eligible source rows. Pass --apply only
against a V15-migrated disposable/staging database after a restorable backup.
The original audit_events table is never modified.
"""
from __future__ import annotations

import argparse
import re
import hashlib
import json
import sys
from pathlib import Path
from collections import defaultdict
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_session_factory
from app import models
from app.audit_governance import append_case_audit_entry


def _action_code(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", (value or "LEGACY_AUDIT_EVENT").upper()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = "LEGACY_" + normalized
    return normalized[:64]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write entries; without this flag the script is read-only")
    parser.add_argument("--case-id", type=UUID, help="limit backfill to one case")
    args = parser.parse_args()

    factory = get_session_factory()
    inserted = 0
    skipped = 0
    with factory() as db:
        query = db.query(models.AuditEvent).order_by(
            models.AuditEvent.case_id, models.AuditEvent.created_at, models.AuditEvent.id)
        if args.case_id:
            query = query.filter(models.AuditEvent.case_id == args.case_id)
        legacy_rows = query.all()
        by_case = defaultdict(list)
        for row in legacy_rows:
            by_case[row.case_id].append(row)

        for case_id, rows in by_case.items():
            case = db.query(models.Case).filter_by(id=case_id).first()
            if not case:
                skipped += len(rows)
                continue
            existing = (db.query(models.CaseAuditEntry).filter_by(case_id=case_id).all())
            existing_ids = {
                str((entry.details or {}).get("legacy_audit_event_id"))
                for entry in existing if (entry.details or {}).get("legacy_audit_event_id")
            }
            for row in rows:
                if str(row.id) in existing_ids:
                    skipped += 1
                    continue
                version_id = None
                if row.entity_type == "case_analysis_version":
                    try:
                        candidate_id = UUID(str(row.entity_id))
                    except (ValueError, TypeError, AttributeError):
                        candidate_id = None
                    if candidate_id and db.query(models.CaseAnalysisVersion.id).filter_by(
                        id=candidate_id, case_id=case_id).first():
                        version_id = candidate_id
                if not args.apply:
                    inserted += 1
                    continue
                append_case_audit_entry(
                    db, case=case, actor_id=(row.actor or "legacy-unknown")[:160],
                    actor_role="LEGACY", action_code=_action_code(row.action),
                    entity_type=(row.entity_type or "legacy_event")[:64],
                    entity_id=(row.entity_id or str(row.id))[:160], version_id=version_id,
                    reason=None, details={
                        "legacy_source_table": "audit_events",
                        "legacy_audit_event_id": str(row.id),
                        "legacy_action": row.action,
                        "legacy_details_sha256": hashlib.sha256(json.dumps(
                            row.details or {}, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
                    }, created_at=row.created_at,
                )
                inserted += 1
            if args.apply:
                db.commit()

    mode = "APPLIED" if args.apply else "DRY_RUN"
    print(f"{mode}: eligible={inserted}, skipped={skipped}, cases={len(by_case)}")
    if not args.apply:
        print("No rows were written. Re-run with --apply only after V15 migration and backup/restore rehearsal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
