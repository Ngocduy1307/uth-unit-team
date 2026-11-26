"""Evidence provenance and statement reconciliation primitives.

This module produces reviewable evidence candidates only. It does not verify
account ownership, accept income, decide policy, or authorize credit.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

MANIFEST_HASH_VERSION = "1"
RECONCILIATION_VERSION = "V9.3.2.1"
# Intentionally empty until PO/bank supplies and approves an independent,
# versioned calibration corpus and its acceptance thresholds.
APPROVED_RECONCILIATION_CALIBRATION_BASES: frozenset[str] = frozenset()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def manifest_payload(*, case_id: Any, sequence_no: int, document_id: Any,
                     original_filename: str, sha256: str, mime_type: str,
                     file_size: int, previous_entry_hash: str | None,
                     received_at: datetime, received_by: str) -> dict[str, Any]:
    return {
        "hash_version": MANIFEST_HASH_VERSION,
        "case_id": str(case_id),
        "sequence_no": int(sequence_no),
        "document_id": str(document_id),
        "original_filename": original_filename,
        "sha256": sha256.lower(),
        "mime_type": mime_type,
        "file_size": int(file_size),
        "previous_entry_hash": previous_entry_hash,
        "received_at": _utc_iso(received_at),
        "received_by": received_by,
    }


def calculate_manifest_entry_hash(**kwargs) -> str:
    payload = manifest_payload(**kwargs)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def verify_manifest_chain(entries: Iterable[Any]) -> dict[str, Any]:
    """Validate ordered append-only manifest entries; return a diagnostic summary."""
    ordered = sorted(entries, key=lambda x: x.sequence_no)
    expected_previous = None
    errors: list[dict[str, Any]] = []
    expected_sequence = 1
    expected_case_id = str(ordered[0].case_id) if ordered else None
    for entry in ordered:
        if str(entry.case_id) != expected_case_id:
            errors.append({"sequence_no": entry.sequence_no, "code": "CASE_ID_MISMATCH"})
        if entry.sequence_no != expected_sequence:
            errors.append({"sequence_no": entry.sequence_no, "code": "SEQUENCE_GAP"})
        if entry.previous_entry_hash != expected_previous:
            errors.append({"sequence_no": entry.sequence_no, "code": "PREVIOUS_HASH_MISMATCH"})
        try:
            expected_hash = calculate_manifest_entry_hash(
                case_id=entry.case_id,
                sequence_no=entry.sequence_no,
                document_id=entry.document_id,
                original_filename=entry.original_filename,
                sha256=entry.sha256,
                mime_type=entry.mime_type,
                file_size=entry.file_size,
                previous_entry_hash=entry.previous_entry_hash,
                received_at=entry.received_at,
                received_by=entry.received_by,
            )
        except Exception:
            expected_hash = None
        if expected_hash != entry.entry_hash:
            errors.append({"sequence_no": entry.sequence_no, "code": "ENTRY_HASH_MISMATCH"})
        expected_previous = entry.entry_hash
        expected_sequence += 1
    return {
        "valid": not errors,
        "entry_count": len(ordered),
        "latest_entry_hash": expected_previous,
        "errors": errors,
    }


def manifest_matches_document_metadata(entry: Any, document: Any) -> bool:
    """Compare every duplicated receipt field, not only the file digest."""
    return bool(
        entry is not None
        and str(entry.document_id) == str(document.id)
        and str(entry.case_id) == str(document.case_id)
        and (entry.original_filename or "") == (document.original_filename or "")
        and (entry.sha256 or "").lower() == (document.sha256 or "").lower()
        and (entry.mime_type or "") == (document.mime_type or "")
        and int(entry.file_size) == int(document.file_size)
    )


def summarize_document_integrity(document_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize integrity and completeness as distinct dimensions."""
    return {
        "document_count": len(document_rows),
        "all_manifest_metadata_match": all(row["manifest_metadata_integrity"] == "MATCH" for row in document_rows),
        "all_documents_manifested": all(bool(row["manifested"]) for row in document_rows),
        "unmanifested_document_count": sum(1 for row in document_rows if not row["manifested"]),
        "all_stored_bytes_match": all(row["stored_bytes_integrity"] == "MATCH" for row in document_rows),
        "stored_byte_mismatch_count": sum(1 for row in document_rows if row["stored_bytes_integrity"] != "MATCH"),
    }


def normalize_description(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def transaction_fingerprint(transaction_date: str | None, amount: Decimal | int | float | str | None,
                            direction: str | None, description: str | None) -> str | None:
    """Stable exact-match candidate fingerprint; never a deduplication decision."""
    if not transaction_date or amount is None or direction not in {"CREDIT", "DEBIT"}:
        return None
    try:
        parsed_amount = Decimal(str(amount))
        if not parsed_amount.is_finite():
            return None
        normalized_amount = format(abs(parsed_amount).quantize(Decimal("0.01")), "f")
    except (InvalidOperation, ValueError, TypeError):
        return None
    normalized_date = str(transaction_date)[:10]
    try:
        date.fromisoformat(normalized_date)
    except ValueError:
        return None
    payload = "|".join((normalized_date, normalized_amount, direction, normalize_description(description)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def duplicate_pair_key(case_id: Any, transaction_a_id: Any, transaction_b_id: Any) -> tuple[str, str, str]:
    left, right = sorted((str(transaction_a_id), str(transaction_b_id)))
    key = hashlib.sha256(f"{case_id}|{left}|{right}".encode("utf-8")).hexdigest()
    return left, right, key


def _normalized_decimal(field: Any) -> Decimal | None:
    normalized = getattr(field, "normalized_value", None)
    if not isinstance(normalized, dict):
        return None
    value = normalized.get("amount_vnd")
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if amount.is_finite() else None


def _normalized_date(field: Any) -> date | None:
    normalized = getattr(field, "normalized_value", None)
    if not isinstance(normalized, dict) or not normalized.get("date"):
        return None
    try:
        return date.fromisoformat(str(normalized["date"])[:10])
    except ValueError:
        return None


def _valid_source_bbox(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        coordinates = {name: Decimal(str(value[name])) for name in ("x", "y", "width", "height")}
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return False
    if not all(number.is_finite() for number in coordinates.values()):
        return False
    return (coordinates["x"] >= 0 and coordinates["y"] >= 0
            and coordinates["width"] > 0 and coordinates["height"] > 0)


def _field_candidate(fields: list[Any], field_name: str, kind: str) -> tuple[Any | None, str | None]:
    candidates = [x for x in fields if getattr(x, "field_name", None) == field_name]
    if not candidates:
        return None, f"MISSING_{field_name.upper()}"
    if len(candidates) != 1:
        return None, f"AMBIGUOUS_{field_name.upper()}"
    item = candidates[0]
    if getattr(item, "validation_status", None) != "VALID":
        return None, f"INVALID_{field_name.upper()}"
    if kind == "amount" and _normalized_decimal(item) is None:
        return None, f"INVALID_{field_name.upper()}"
    if kind == "date" and _normalized_date(item) is None:
        return None, f"INVALID_{field_name.upper()}"
    page_number = getattr(item, "page_number", None)
    if not isinstance(page_number, int) or page_number < 1 or not _valid_source_bbox(getattr(item, "bbox", None)):
        return None, f"MISSING_OR_INVALID_SOURCE_ANCHOR_{field_name.upper()}"
    return item, None


def reconcile_pdf_csv_candidates(*, pdf_fields: list[Any], csv_transactions: list[Any],
                                  tolerance_vnd: Decimal | int | str = Decimal("0")) -> dict[str, Any]:
    """Compare PDF balance fields with CSV movement totals, with abstention gates.

    The output is a machine-generated candidate. Even a zero variance is not a
    Maker confirmation, bank statement authenticity check, or financial decision.
    """
    tolerance = Decimal(str(tolerance_vnd))
    if not tolerance.is_finite() or tolerance < 0 or tolerance > Decimal("1000000"):
        raise ValueError("tolerance_vnd must be between 0 and 1,000,000")

    required = {
        "opening_balance": "amount",
        "closing_balance": "amount",
        "statement_start_date": "date",
        "statement_end_date": "date",
    }
    chosen: dict[str, Any] = {}
    errors: list[str] = []
    for field_name, kind in required.items():
        candidate, error = _field_candidate(pdf_fields, field_name, kind)
        if error:
            errors.append(error)
        else:
            chosen[field_name] = candidate

    if errors:
        return {
            "status": "INCOMPLETE",
            "reconciliation_version": RECONCILIATION_VERSION,
            "errors": sorted(set(errors)),
            "maker_review_required": True,
            "maker_review_status": "PENDING",
            "authority": "DATA_AI_CANDIDATE_ONLY",
        }

    opening = _normalized_decimal(chosen["opening_balance"])
    closing = _normalized_decimal(chosen["closing_balance"])
    period_start = _normalized_date(chosen["statement_start_date"])
    period_end = _normalized_date(chosen["statement_end_date"])
    if period_start > period_end:
        return {"status": "INCOMPLETE", "reconciliation_version": RECONCILIATION_VERSION,
                "errors": ["STATEMENT_PERIOD_START_AFTER_END"], "maker_review_required": True,
                "maker_review_status": "PENDING", "authority": "DATA_AI_CANDIDATE_ONLY"}

    if not csv_transactions:
        return {"status": "INCOMPLETE", "reconciliation_version": RECONCILIATION_VERSION,
                "errors": ["CSV_HAS_NO_TRANSACTION_ROWS"], "maker_review_required": True,
                "maker_review_status": "PENDING", "authority": "DATA_AI_CANDIDATE_ONLY"}

    credits = Decimal("0")
    debits = Decimal("0")
    included = 0
    outside_period = 0
    invalid_rows: list[dict[str, Any]] = []
    for tx in csv_transactions:
        raw_date = getattr(tx, "transaction_date", None)
        try:
            tx_date = date.fromisoformat(str(raw_date)[:10]) if raw_date else None
        except ValueError:
            tx_date = None
        amount = getattr(tx, "amount_vnd", None)
        direction = getattr(tx, "direction", None)
        try:
            amount_value = Decimal(str(amount)) if amount is not None else None
            if amount_value is not None and not amount_value.is_finite():
                amount_value = None
        except (InvalidOperation, ValueError, TypeError):
            amount_value = None
        if tx_date is None or amount_value is None or direction not in {"CREDIT", "DEBIT"}:
            invalid_rows.append({"source_row": getattr(tx, "source_row", None),
                                 "reason": "MISSING_OR_INVALID_DATE_AMOUNT_DIRECTION"})
            continue
        if tx_date < period_start or tx_date > period_end:
            outside_period += 1
            continue
        if direction == "CREDIT":
            credits += abs(amount_value)
        else:
            debits += abs(amount_value)
        included += 1

    if invalid_rows or included == 0:
        return {
            "status": "INCOMPLETE",
            "reconciliation_version": RECONCILIATION_VERSION,
            "errors": (["CSV_HAS_INVALID_TRANSACTION_ROWS"] if invalid_rows else ["NO_TRANSACTIONS_WITHIN_STATEMENT_PERIOD"]),
            "invalid_row_count": len(invalid_rows),
            "rows_outside_statement_period": outside_period,
            "maker_review_required": True,
            "maker_review_status": "PENDING",
            "authority": "DATA_AI_CANDIDATE_ONLY",
        }

    computed_closing = opening + credits - debits
    variance = closing - computed_closing
    arithmetic_status = "BALANCE_MATCH_CANDIDATE" if abs(variance) <= tolerance else "BALANCE_VARIANCE_CANDIDATE"
    # The approved allowlist is intentionally empty until the bank/PO supplies
    # and signs off a versioned calibration corpus. Merely naming a basis
    # CALIBRATED_* is not sufficient evidence that it was approved.
    uncalibrated = [name for name, field in chosen.items()
                    if getattr(field, "extraction_decision", "ABSTAIN") != "SUGGEST"
                    or getattr(field, "confidence_basis", None) not in APPROVED_RECONCILIATION_CALIBRATION_BASES]
    source_review_notes = [f"UNCONFIRMED_PDF_FIELD:{name}" for name in uncalibrated]
    return {
        "status": "ABSTAINED" if uncalibrated else arithmetic_status,
        "arithmetic_candidate_status": arithmetic_status,
        "reconciliation_version": RECONCILIATION_VERSION,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "opening_balance_vnd": str(opening),
        "closing_balance_pdf_vnd": str(closing),
        "total_credit_csv_vnd": str(credits),
        "total_debit_csv_vnd": str(debits),
        "computed_closing_balance_vnd": str(computed_closing),
        "variance_vnd": str(variance),
        "tolerance_vnd": str(tolerance),
        "included_transaction_count": included,
        "rows_outside_statement_period": outside_period,
        "source_review_notes": source_review_notes,
        "maker_review_required": True,
        "maker_review_status": "PENDING",
        "account_ownership_verified": False,
        "statement_authenticity_verified": False,
        "bank_csv_schema_approval": "PENDING_BANK_SIGNOFF",
        "authority": "DATA_AI_CANDIDATE_ONLY",
    }


def build_duplicate_pairs(case_id: Any, transactions: Iterable[Any],
                          max_matches_per_transaction: int = 10) -> tuple[list[dict[str, Any]], int]:
    """Build bounded exact-match pairs from historic rows without suppressing data."""
    if max_matches_per_transaction < 1:
        raise ValueError("max_matches_per_transaction must be at least one")
    grouped: dict[str, list[Any]] = {}
    for transaction in transactions:
        fingerprint = transaction_fingerprint(
            getattr(transaction, "transaction_date", None),
            getattr(transaction, "amount_vnd", None),
            getattr(transaction, "direction", None),
            getattr(transaction, "description", None),
        )
        if fingerprint:
            grouped.setdefault(fingerprint, []).append(transaction)
    output: list[dict[str, Any]] = []
    truncated_count = 0
    for fingerprint, rows in grouped.items():
        for index, right in enumerate(rows):
            prior = rows[:index]
            chosen = prior[-max_matches_per_transaction:]
            truncated_count += max(0, len(prior) - len(chosen))
            for left in chosen:
                left_id, right_id, candidate_key = duplicate_pair_key(case_id, left.id, right.id)
                output.append({
                    "left_transaction_id": left_id,
                    "right_transaction_id": right_id,
                    "fingerprint_sha256": fingerprint,
                    "candidate_key": candidate_key,
                    "match_reasons": ["EXACT_DATE", "EXACT_ABSOLUTE_AMOUNT", "EXACT_DIRECTION", "NORMALIZED_DESCRIPTION"],
                })
    return output, truncated_count
