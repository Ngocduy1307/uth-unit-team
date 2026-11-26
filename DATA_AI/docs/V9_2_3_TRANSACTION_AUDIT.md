# V9.2.3 – Transaction Boundary Audit

## Mục tiêu

Rà các điểm commit có side effect trong API và pipeline để giảm trạng thái ghi dở, ghi trùng hoặc audit/domain record không đồng bộ. Đây là static/source review cộng regression test, chưa thay thế PostgreSQL integration/load testing.

## Các đường ghi chính

| API / luồng | Domain writes | Audit / phụ trợ | Boundary hiện tại | Nhận xét |
|---|---|---|---|---|
| `POST /api/v1/cases` | `Case` | Chưa có audit event trong `repository.create_case` | Một commit trong repository; bắt unique race và trả 409 | Dùng idempotency key cho retry; audit event tạo hồ sơ là phần cần thống nhất policy |
| `POST /api/v1/cases/{case_id}/documents` | `Document` | `AuditEvent` | DB commit sau file write; mỗi attempt có storage path riêng; rollback + cleanup file của attempt đó nếu commit lỗi | Filesystem/DB không atomic; unique storage path tránh xóa nhầm file khi hai upload giống nhau chạy đua; vẫn cần đối soát orphan nếu cleanup thất bại |
| `POST .../documents/{document_id}/process` – CSV | `Transaction`, `DataQualityIssue`, `SourceInventory`, ledger, payroll match, `ProcessingResult`, `PipelineRun` | Quality findings và lineage | Một commit trong parent `process_document()`; `process_csv()` không commit | Đã sửa split commit cũ |
| `POST .../documents/{document_id}/process` – PDF/OCR | `ExtractedField`, `SourceInventory`, `ProcessingResult`, `PipelineRun`, document status | OCR quality findings | Một commit trong `process_document()` | Nếu xử lý lỗi, rollback domain writes rồi đánh dấu PipelineRun FAILED trong transaction kế tiếp |
| `POST /api/v1/cases/{case_id}/applicant-submissions` | `ApplicantSubmission` | `AuditEvent` | Một commit | Backend phải kiểm tra consent/purpose/field allow-list trước khi gọi |
| `POST /api/v1/customers` | Customer + address + employment | `ManagementAuditLog` | Một commit | Có check trùng trước insert; unique constraint vẫn cần xử lý race đồng bộ |
| `PATCH /api/v1/customers/{customer_id}` | Customer/address/employment | `ManagementAuditLog` | Một commit | Gộp domain update và audit |
| `POST /api/v1/customers/{customer_id}/applications` | Case + LoanApplication + ApplicantSubmission; có thể gắn bank cho customer | `ManagementAuditLog` | Một commit | Thực hiện nhiều kiểm tra trước commit; cần PostgreSQL concurrency test với external_case_id |
| `POST /api/v1/internal/staff-sync` | Staff + StaffUserRole + role history | `ManagementAuditLog` | Một commit | Role sync và audit đi cùng nhau |
| `PUT /api/v1/admin/forms/{form_code}` | Deactivate form cũ + form mới + field definitions | `ManagementAuditLog` | Một commit | Versioning snapshot đang ở mức form-definition; không phải full workflow freeze |
| `POST /api/v1/admin/banks`, `POST .../branches` | Bank / Branch | `ManagementAuditLog` | Một commit mỗi route | Cần DB unique-race test trên PostgreSQL |
| `GET /api/v1/admin/exports/excel` | `ExportJob` | ManagementAuditLog; có thể `AuditEvent` theo case | Commit trước khi stream workbook | **GET có side effect**; không được tự động retry. Cần POST command + download route |
| `GET /api/v1/customers`, `GET /api/v1/customers/{customer_id}` | Không sửa customer | `ManagementAuditLog` access event | Commit audit khi đọc | GET có audit-write side effect; caller không nên tự retry nếu cần tránh log duplicate |

## Reliability ledger không thay thế domain transaction

`api_idempotency_records` là bảng điều phối request/response. Reservation được commit trước khi gọi handler; response được commit sau business handler. Nếu server chết tại khoảng giữa, record có thể ở `IN_PROGRESS` và sau timeout được đánh dấu `OUTCOME_UNKNOWN`. Không tự động chạy lặp. V9.2.3 chưa triển khai transactional outbox hoặc atomic commit chung cho mọi handler.

## Test evidence

`tests/test_v9_2_3_transaction_boundaries.py` xác nhận CSV processor không tự commit, upload cleanup được gọi khi DB commit thất bại và upload attempt thua unique race không xóa file của attempt thắng. `tests/test_v9_2_3_idempotency.py` xác nhận handler exception tạo `OUTCOME_UNKNOWN` và retry không chạy business lần hai. Những test này chưa chứng minh transaction isolation, deadlock/retry, locking, hay race condition đa process trên PostgreSQL.

## Retention và dữ liệu trong response cache

`response_body` được lưu ở dạng `BYTEA` trong PostgreSQL để hỗ trợ replay; payload có thể mang thông tin khách hàng. V9.2.3 chưa cung cấp application-level encryption. Trước production phải xác nhận database/storage encryption, DB least-privilege và vận hành job TTL cleanup `db/maintenance/cleanup_api_idempotency_records.sql`. Cleanup chạy theo batch 10.000 rows và lặp tới khi hết row hết hạn; không quét/xóa toàn bảng trên mỗi API request.
