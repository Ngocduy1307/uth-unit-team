"""Audit stored evidence objects against the document SHA-256 ledger.

Prints counts and document IDs only; it never prints file contents or applicant
metadata. Run with the same protected volume mount and a read-only DB account.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.database import get_session_factory
from app.models import Document
from app.service import sha256_file
from app.config import settings


def main() -> int:
    root = Path(settings.storage_dir).resolve()
    missing: list[str] = []
    mismatch: list[str] = []
    outside_root: list[str] = []
    checked = 0
    with get_session_factory()() as db:
        rows = db.query(Document).filter(Document.deleted_at.is_(None)).all()
        for row in rows:
            checked += 1
            candidate = Path(row.stored_path)
            try:
                if candidate.is_symlink():
                    outside_root.append(str(row.id))
                    continue
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except FileNotFoundError:
                missing.append(str(row.id))
                continue
            except (OSError, ValueError, RuntimeError):
                outside_root.append(str(row.id))
                continue
            if not resolved.is_file():
                missing.append(str(row.id))
                continue
            try:
                if sha256_file(resolved).lower() != str(row.sha256).lower():
                    mismatch.append(str(row.id))
            except OSError:
                missing.append(str(row.id))
    report = {
        "status": "PASS" if not (missing or mismatch or outside_root) else "FAIL",
        "checked_documents": checked,
        "missing_document_ids": missing,
        "hash_mismatch_document_ids": mismatch,
        "unsafe_path_document_ids": outside_root,
        "storage_root": str(root),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
