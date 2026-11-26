# V9.2.3 – API Reliability Foundation (bản cập nhật 2026-11-26)

## 1. Phạm vi đã cập nhật trong source

Bản cập nhật này mở rộng nền V9.2.3 ban đầu thành lớp API reliability có thể kiểm thử ở mức ứng dụng:

1. **Request correlation**: response mang `X-Request-ID`; chỉ chấp nhận UUID hợp lệ từ caller, nếu không server tự sinh UUID.
2. **Bounded PostgreSQL pool**: cấu hình pool size, overflow, timeout, recycle và connect timeout qua environment.
3. **Durable idempotency cho mutation request**: middleware áp dụng cho `POST`, `PUT`, `PATCH`, `DELETE` dưới `/api/v1/` khi caller gửi `Idempotency-Key`; reservation và response record lưu trong PostgreSQL.
4. **Signed Assertion V2**: `Idempotency-Key` được đưa vào canonical HMAC payload. Request có key phải dùng assertion V2; request không có key vẫn dùng V1 để tương thích ngược.
5. **Backend retry/circuit-breaker example**: Spring adapter dùng cùng idempotency key và cùng serialized request bytes cho mọi lần retry; có connect/read timeout, backoff có jitter và circuit breaker process-local.
6. **Transaction boundary fixes**: CSV import, quality findings, observed income ledger, payroll-match candidates, ProcessingResult và PipelineRun completion nằm trong cùng transaction của `process_document`; upload dùng storage path riêng cho từng attempt và dọn file của attempt thất bại khi DB commit lỗi, tránh request thua unique race xóa nhầm file của request thắng (nếu cleanup filesystem cũng thất bại, lỗi nêu rõ cần reconciliation); duplicate `external_case_id` race trả về HTTP 409.
7. **OpenAPI**: công bố header `Idempotency-Key` là optional trên mọi mutation API V1 và response 409 cho conflict/in-progress/reconciliation.

## 2. Idempotency contract

### Header và phạm vi

- Header: `Idempotency-Key`.
- Định dạng: 8–128 ký tự ASCII, bắt đầu bằng chữ/số; phần còn lại chỉ gồm chữ/số, `.`, `_`, `:`, `-`.
- Mặc định lưu 72 giờ (`IDEMPOTENCY_TTL_HOURS`); sau thời hạn này, key có thể được dùng lại và không còn bảo đảm chống trùng cho logical command cũ.
- Giới hạn body mặc định 24 MiB; response replay tối đa 1 MiB.
- Response body có thể chứa dữ liệu nghiệp vụ/PII; bảng V11 hiện chưa mã hóa payload ở tầng ứng dụng. Production phải bật mã hóa storage/database, giới hạn quyền DB, và chạy job dọn dữ liệu hết hạn theo `db/maintenance/cleanup_api_idempotency_records.sql`.
- Key được hash trước khi lưu. Database không lưu raw key hoặc raw actor/bank trong bảng idempotency.
- Scope: trusted actor + bank. Request fingerprint gồm method, raw path/query, content type/encoding, Accept, actor, roles chuẩn hóa, bank và SHA-256 của body.
- Key chỉ có ý nghĩa cho **một logical command**. Backend phải cấp key khi tạo command và lưu bền vững; khi retry phải dùng đúng key và đúng request bytes. Không tạo key mới cho từng lần retry.

### State machine

| State / kết quả | Ý nghĩa | Hành vi |
|---|---|---|
| `IN_PROGRESS` | Reservation đã commit trước khi gọi business handler | Request trùng nhận HTTP 409 `IDEMPOTENCY_IN_PROGRESS` và `Retry-After: 2`; không chạy business lần hai |
| `COMPLETED` | Response đã được ghi bền vững trước khi gửi cho caller | Cùng key + cùng fingerprint nhận lại status/body/header đã lưu; `X-Request-ID` không lấy từ response cũ (dùng UUID hợp lệ của caller nếu có, nếu không server tự sinh) và có `Idempotency-Replayed: true` |
| `OUTCOME_UNKNOWN` | Handler bị ngắt/throw hoặc không thể persist response sau khi business handler đã chạy | HTTP 409 `IDEMPOTENCY_OUTCOME_UNKNOWN`; không tự chạy lại, phải đối soát business record |
| Key mismatch | Cùng actor/bank dùng lại key cho fingerprint khác | HTTP 409 `IDEMPOTENCY_KEY_REUSED` |
| Response vượt giới hạn | Business handler hoàn tất nhưng response quá lớn để replay | Lưu trạng thái không replayable; request tiếp theo nhận HTTP 409 `IDEMPOTENCY_RESPONSE_NOT_REPLAYABLE` |

Các response 4xx từ business handler giải phóng reservation để caller có thể sửa dữ liệu và thử lại. Các response không phải 4xx được ghi lại để tránh chạy lại side effect không chắc chắn.

### Ràng buộc bảo mật

- Middleware xác minh service token, Signed Assertion và nonce chống replay mới **trước khi** replay response đã lưu.
- Signed Assertion V2 ký cả `Idempotency-Key`; không thể thay key mà vẫn dùng chữ ký cũ.
- Mỗi lần retry phải tạo assertion mới với nonce mới, nhưng giữ nguyên idempotency key và body.
- Response replay bỏ các header per-attempt/hop-by-hop và `Set-Cookie`; `X-Request-ID` luôn mới.
- Caller không gửi `Idempotency-Key` vẫn theo luồng cũ. Vì vậy Backend cần chủ động chuyển các command có retry sang key bắt buộc ở tầng integration.

## 3. Backend retry policy mẫu

`examples/backend-spring/DataAiClient.java`, `DataAiAssertionSigner.java`, `DataAiSignedAssertionInterceptor.java` và `DataAiResilience.java` là ví dụ tích hợp, không phải bằng chứng đã được merge vào repository Spring Boot thực tế.

- Tối đa 3 lần gọi cho một logical command.
- Retry network `ResourceAccessException`, HTTP 429/502/504, 503 chỉ khi mã lỗi là `IDEMPOTENCY_STORE_UNAVAILABLE`, và 409 chỉ khi mã lỗi là `IDEMPOTENCY_IN_PROGRESS`.
- Tôn trọng `Retry-After` có giới hạn; nếu không có thì exponential backoff + jitter.
- Circuit breaker mở sau 5 lần logical command liên tiếp thất bại; cooldown 30 giây, sau đó cho một half-open probe. Bộ đếm hiện là process-local, không chia sẻ giữa nhiều Backend replica.
- Connect timeout mặc định 3 giây; read timeout 90 giây.
- JSON được serialize một lần trước retry. Multipart upload dùng boundary xác định từ key + file hash, nhờ đó body bytes ổn định giữa các lần retry.
- Không retry `GET /api/v1/admin/exports/excel`: endpoint GET này hiện tạo `ExportJob` và audit log trước khi stream file. Đây là side effect không phù hợp với GET; cần chuyển thành command POST + endpoint download riêng ở một đợt API/export tiếp theo.

## 4. Transaction boundary đã chỉnh

- `process_document()` là transaction owner cho nhánh CSV. `process_csv()` không commit riêng; các transaction rows, quality findings, ledger aggregation, payroll-match candidates, ProcessingResult và trạng thái PipelineRun được commit cùng nhau.
- `save_upload()` ghi file trước DB. Nếu DB commit lỗi, code rollback và xóa file đã lưu; DB và filesystem không phải một distributed transaction, nên vẫn cần storage orphan reconciliation khi thao tác xóa file thất bại.
- `POST /api/v1/cases` ánh xạ race condition của unique `external_case_id` thành HTTP 409.
- Các write handler khác đã có commit boundary theo endpoint, thường gộp domain rows và audit rows trong một commit. Bản này chưa triển khai một transaction coordinator xuyên nhiều service hoặc Camunda.

## 5. Giới hạn quan trọng – không tuyên bố exactly-once tuyệt đối

Idempotency reservation, business transaction và response completion hiện được commit qua các transaction/session riêng. Nếu process chết sau khi business transaction commit nhưng trước khi response record commit, bản ghi giữ ở `IN_PROGRESS` rồi chuyển `OUTCOME_UNKNOWN`; hệ thống cố ý chặn re-execution. Đây là lựa chọn an toàn hơn chạy lặp side effect, nhưng cần quy trình đối soát thủ công.

Muốn loại bỏ hoàn toàn khoảng hở này cần thiết kế transactional outbox/command result hoặc gộp idempotency ledger với business transaction cho từng write path. Việc đó chưa được tuyên bố hoàn tất trong V9.2.3 này.

## 6. Migration và cấu hình

- Migration mới: `db/migration/V11__api_idempotency_records.sql`.
- Môi trường mới: chạy Flyway tuần tự V1–V11.
- Môi trường đang ở V10: backup/restore point, kiểm tra Flyway history, sau đó chạy V11 qua đúng một migration owner.
- Flyway là migration owner duy nhất; không dùng `Base.metadata.create_all()` hoặc Alembic trên schema này. Cleanup TTL là công việc maintenance riêng, không chạy table-wide delete trên mỗi request.
- Các biến mới: `IDEMPOTENCY_TTL_HOURS`, `IDEMPOTENCY_MAX_REQUEST_MB`, `IDEMPOTENCY_MAX_RESPONSE_KB`, `IDEMPOTENCY_IN_PROGRESS_TIMEOUT_SECONDS`.

## 7. Kiểm thử và gate còn mở

- Baseline trước chỉnh sửa: 80 tests passed.
- Sau cập nhật V9.2.3: xem kết quả `pytest -q` trong release handoff; suite gồm idempotency replay/mismatch/in-progress/unknown/oversized response, V1/V2 assertion, contract sync và transaction regression.
- Đã kiểm tra compile độc lập cho `DataAiAssertionSigner.java` trong môi trường làm việc. Các class Spring cần dependency của dự án Backend nên chưa thể xác nhận compile/integration end-to-end tại đây.
- Chưa chạy migration V11 trên PostgreSQL thật, concurrency/load test, pool saturation test, backup/restore drill, Docker Compose/Flyway, hoặc test trong repository Spring Boot đích.
- Do đó: đây là **source-level implementation + automated local tests**, chưa phải Production Acceptance/Production Sign-off.
