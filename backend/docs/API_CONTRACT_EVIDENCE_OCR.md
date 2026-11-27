# API Contract: Tiếp nhận Chứng từ & Kết quả OCR (KAN-118)

Tài liệu đặc tả các API phục vụ tiếp nhận chứng từ, quản lý phiên bản tài liệu, lưu trữ kết quả OCR và ghi vết kiểm toán (Audit + Outbox) để phối hợp tích hợp với **Data/AI Service** và **Camunda 8 Workflow**.

---

## 1. Schema & Cơ chế Versioning

- **Migration:** `V3__evidence_ocr_schema.sql`
- **Bảng `evidence_records`:**
  - Mỗi loại chứng từ (`fileType`: `BANK_STATEMENT`, `SALARY_CONFIRMATION`, `LABOR_CONTRACT`, `ID_CARD`, `CIC_REPORT`, `OTHER`) trong cùng `dossierId` được đánh số `version` tăng dần (`1, 2, 3...`).
  - Bản ghi mới nhất được đánh dấu `isLatest = true`, các bản ghi cũ tự động chuyển `isLatest = false`.
  - Chặn trùng lặp file giống hệt nhau trong cùng hồ sơ thông qua `fileHash` (SHA-256 64 ký tự hex).
- **Bảng `evidence_ocr_results`:**
  - Lưu kết quả bóc tách OCR theo từng `ocrVersion` (`1, 2, 3...`) gắn với `evidenceId`.
  - Lưu `rawPayload` (JSONB) và `extractedSummary` (JSONB).
- **Audit & Workflow Outbox:**
  - Mọi thao tác tạo mới chứng từ hoặc nhận kết quả OCR đều ghi `audit_logs` và phát sự kiện `outbox_events` (`EVIDENCE_RECEIVED`, `OCR_COMPLETED`, `OCR_FAILED`).

---

## 2. Danh sách Endpoints

### 2.1. Đăng ký tiếp nhận chứng từ
- **URL:** `POST /api/v1/dossiers/{dossierId}/evidences`
- **Request Body:**
```json
{
  "fileName": "sao_ke_vcb_6m.pdf",
  "fileHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "fileType": "BANK_STATEMENT",
  "storagePath": "/storage/dossiers/dossier-1/sao_ke_vcb_6m.pdf",
  "uploadedBy": "maker_01",
  "fileSizeBytes": 204800,
  "mimeType": "application/pdf",
  "reason": "Bo sung sao ke 6 thang"
}
```
- **Response (`201 Created`):**
```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "Evidence registered successfully",
  "data": {
    "id": "uuid",
    "dossierId": "dossier-1",
    "fileName": "sao_ke_vcb_6m.pdf",
    "fileHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "fileType": "BANK_STATEMENT",
    "status": "RECEIVED",
    "ocrStatus": "PENDING",
    "version": 1,
    "isLatest": true
  }
}
```

### 2.2. Lấy danh sách chứng từ theo hồ sơ
- **URL:** `GET /api/v1/dossiers/{dossierId}/evidences?latestOnly=false`
- **Query Param:** `latestOnly` (`true` để chỉ lấy bản mới nhất của từng loại chứng từ).

### 2.3. Lấy chi tiết chứng từ
- **URL:** `GET /api/v1/evidences/{evidenceId}`

### 2.4. Tiếp nhận và lưu trữ kết quả OCR
- **URL:** `POST /api/v1/evidences/{evidenceId}/ocr-results`
- **Request Body:**
```json
{
  "engineName": "pdfplumber",
  "engineVersion": "0.11.0",
  "confidenceScore": 97.50,
  "rawPayload": "{\"pages\": 6, \"rows\": 120}",
  "extractedSummary": "{\"accountNumber\": \"0071000123456\"}",
  "status": "COMPLETED",
  "processedBy": "ai-service-worker"
}
```
- **Response (`201 Created`):** Trả về bản ghi `EvidenceOcrResultResponse` kèm `ocrVersion`.

### 2.5. Truy xuất lịch sử kết quả OCR
- **URL:** `GET /api/v1/evidences/{evidenceId}/ocr-results`

### 2.6. Truy xuất kết quả OCR mới nhất
- **URL:** `GET /api/v1/evidences/{evidenceId}/ocr-results/latest`
