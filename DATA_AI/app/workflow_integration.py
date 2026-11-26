"""V9.5.1 workflow integration primitives.

This module deliberately implements a durable integration boundary, not a
Camunda client or a business decision engine. Camunda owns BPMN tasks/timers;
Backend/SSO owns identity, assignments and authority; DATA-AI persists
correlation, idempotent inbox/outbox events and evidence-package hashes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

SAFE_EVENT_KEYS = {
    "evidence_request_id", "task_id", "task_type", "timer_id", "reason_code",
    "incident_code", "incident_reference", "external_gate_reference",
    "policy_reference", "policy_version", "product_code", "product_version",
    "authority_reference", "completed_at", "assigned_group", "document_id",
    "document_sha256", "due_at", "resubmission_id", "impact_sha256",
    "analysis_version_id", "declaration_revision_id", "section_code", "revision_no",
    "financial_input_bundle_id", "readiness_status", "business_engine_receipt_id",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=_json_default, allow_nan=False).encode("utf-8")


def _json_default(value: Any):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "hex"):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sanitize_workflow_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Allow only routing metadata; never persist arbitrary Camunda variables."""
    if not isinstance(payload, dict):
        raise ValueError("workflow payload must be an object")
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in SAFE_EVENT_KEYS:
            continue
        if not isinstance(value, (str, int, bool)) and value is not None:
            raise ValueError(f"workflow metadata field {key} has an unsupported type")
        if isinstance(value, str):
            value = value.strip()
            if len(value) > 200:
                raise ValueError(f"workflow metadata field {key} is too long")
        safe[key] = value
    return safe


def build_resubmission_impact(*, case_id: str, request_id: str, document_ids: list[str],
                              base_version_id: str | None, next_version_no: int,
                              field_count: int, transaction_count: int,
                              manifest_sequence_numbers: list[int]) -> dict:
    return {
        "impact_schema_version": "1.0",
        "case_id": str(case_id),
        "evidence_request_id": str(request_id),
        "received_document_ids": sorted(str(v) for v in document_ids),
        "based_on_version_id": str(base_version_id) if base_version_id else None,
        "requested_new_version_no": int(next_version_no),
        "affected_domains": [
            "DOCUMENT_MANIFEST", "OCR_FIELDS", "TRANSACTION_LEDGER",
            "EVIDENCE_RECONCILIATION", "READINESS_SNAPSHOT", "EXPORT_PACKAGE",
        ],
        "affected_existing_field_count": int(field_count),
        "affected_existing_transaction_count": int(transaction_count),
        "manifest_sequence_numbers": sorted(int(v) for v in manifest_sequence_numbers),
        "recalculation_required": True,
        "credit_decision_made": False,
    }


def _register_vietnamese_font() -> str:
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                if "DataAIVietnamese" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("DataAIVietnamese", str(path)))
                return "DataAIVietnamese"
            except Exception:
                continue
    return "Helvetica"


def build_summary_pdf(manifest: dict) -> bytes:
    """Create a compact Vietnamese-capable audit summary, not a credit report."""
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=36, leftMargin=36,
                            topMargin=36, bottomMargin=36, title="DATA-AI Evidence Package")
    font = _register_vietnamese_font()
    styles = getSampleStyleSheet()
    styles["Title"].fontName = font
    styles["BodyText"].fontName = font
    styles["Heading2"].fontName = font
    story = [
        Paragraph("DATA-AI – GÓI BẰNG CHỨNG TÍCH HỢP", styles["Title"]),
        Spacer(1, 8),
        Paragraph("Gói kỹ thuật về nguồn dữ liệu và phiên bản. Không phải quyết định tín dụng, không tính DSR và không phê duyệt khoản vay.", styles["BodyText"]),
        Spacer(1, 14),
        Paragraph("Thông tin phiên bản", styles["Heading2"]),
    ]
    rows = [
        ["Trường", "Giá trị"],
        ["Case ID", str(manifest.get("case_id", ""))],
        ["Analysis version", str(manifest.get("analysis_version_no", ""))],
        ["Snapshot SHA-256", str(manifest.get("snapshot_sha256", ""))],
        ["Applicant snapshot SHA-256", str(manifest.get("applicant_snapshot_sha256", ""))],
        ["Product", f"{manifest.get('product_code', '')} / {manifest.get('product_version', '')}"],
        ["Policy", f"{manifest.get('policy_reference', '')} / {manifest.get('policy_version', '')}"],
        ["Calculation reference", f"{manifest.get('calculation_reference', '')} / {manifest.get('calculation_version', '')}"],
        ["Calculation SHA-256", str(manifest.get("calculation_sha256", ""))],
        ["Evidence documents", str(manifest.get("evidence_document_count", 0))],
        ["Audit head SHA-256", str(manifest.get("audit_head_sha256", ""))],
    ]
    table = Table(rows, colWidths=[150, 360], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7EDF4")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9AA6B2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Spacer(1, 12), Paragraph(
        "Các hash product/policy/calculation là tham chiếu do Backend hoặc Business Engine cung cấp qua request đã ký; DATA-AI đóng gói và ràng buộc chúng với evidence snapshot, không tự xác minh hoặc tái tính các nghiệp vụ này.",
        styles["BodyText"])])
    doc.build(story)
    return output.getvalue()


def build_export_zip(*, manifest: dict, analysis_snapshot: dict,
                     evidence_rows: list[dict]) -> tuple[bytes, dict]:
    """Return ZIP bytes and per-entry SHA-256 map; manifest is self-describing."""
    csv_buffer = io.StringIO(newline="")
    columns = ["document_id", "filename", "mime_type", "file_size", "sha256", "document_type", "evidence_status", "processing_status"]
    writer = csv.DictWriter(csv_buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in evidence_rows:
        writer.writerow(row)
    files: dict[str, bytes] = {
        "analysis.json": canonical_json_bytes(analysis_snapshot),
        "evidence.csv": csv_buffer.getvalue().encode("utf-8-sig"),
    }
    file_hashes = {name: sha256_bytes(content) for name, content in files.items()}
    final_manifest = dict(manifest)
    final_manifest["package_files"] = file_hashes
    files["summary.pdf"] = build_summary_pdf(final_manifest)
    file_hashes["summary.pdf"] = sha256_bytes(files["summary.pdf"])
    final_manifest["package_files"] = file_hashes
    files["manifest.json"] = canonical_json_bytes(final_manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name)
            info.date_time = (2020, 1, 1, 0, 0, 0)  # deterministic archive metadata
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue(), final_manifest


def validate_outbox_transition(current: str, decision: str, *, attempts: int = 0) -> str:
    transitions = {
        "PENDING": {"IN_FLIGHT"},
        "IN_FLIGHT": {"DELIVERED", "PENDING", "DEAD_LETTER"},
        "DELIVERED": set(),
        "DEAD_LETTER": set(),
    }
    allowed = decision in transitions.get(current, set())
    if current == "PENDING" and decision == "DEAD_LETTER" and attempts >= 8:
        allowed = True  # A never-claimed pending event can be retired only at the hard attempt ceiling.
    if not allowed:
        raise ValueError(f"invalid outbox transition {current}->{decision}")
    return decision
