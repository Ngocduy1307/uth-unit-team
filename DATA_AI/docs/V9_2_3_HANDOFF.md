# V9.2.3 – Handoff

**Ngày cập nhật:** 2026-11-26  
**Baseline:** `DATA_AI_V9_2_3_API_RELIABILITY_FOUNDATION.zip` + `Workflow.drawio` do người dùng cung cấp.

## Kết quả source-level

- Đã kiểm tra checksum SHA-256 của ZIP gốc và xác nhận khớp file `.sha256` người dùng gửi.
- Baseline test: 80 passed.
- Source update: bổ sung persistent idempotency V11, Signed Assertion V2 binding, Spring retry/circuit-breaker example, sửa CSV transaction boundary, per-attempt upload storage cleanup chống duplicate-upload race; cập nhật OpenAPI, Docker Compose, README và tài liệu traceability/transaction audit.
- Test sau cập nhật: **96 passed**.
- `python -m compileall -q app tests`: passed.
- `javac` cho `DataAiAssertionSigner.java`: passed.

## Việc cần làm trước khi dùng ở staging/production

1. Backup database và kiểm tra Flyway history đang ở V10; chỉ sau đó chạy Flyway V11 qua một migration owner.
2. Đặt `APP_ENV=production`, secret `INTERNAL_SERVICE_TOKEN` và `SERVICE_ASSERTION_KEYS` riêng biệt qua secret manager; không dùng giá trị local trong `.env.example`.
3. Xác nhận PostgreSQL V11, response cache retention, database/storage encryption, least-privilege và chạy `db/maintenance/cleanup_api_idempotency_records.sql` định kỳ.
4. Merge các adapter Java vào Backend thật, build với đúng Spring Boot version/dependencies, kiểm tra multipart bytes, timeouts, retries và circuit breaker đa replica.
5. Chạy concurrency test với nhiều worker, load/pool saturation, migration rehearsal, backup/restore và chaos/recovery test.
6. Không retry `GET /api/v1/admin/exports/excel`; endpoint này hiện có side effect. Đưa POST export command + download route vào một increment API/export tiếp theo.
7. Giữ `OUTCOME_UNKNOWN` ở trạng thái cần đối soát; không xóa row hoặc cấp key mới để chạy lại trước khi xác định business outcome.

## Mức xác nhận

Đây là **source update + local automated verification**. Không có Docker hoặc `psql` trong môi trường cập nhật, nên V11 chưa chạy trên PostgreSQL thật; không có dependency Spring Boot của Backend đích, nên chỉ signer Java độc lập được compile. Không được ghi nhận production-ready/production-certified ở thời điểm handoff.

## Roadmap

Theo lộ trình 9 vòng nhỏ đã chốt, V9.2.2 nằm trong baseline và V9.2.3 là gói cập nhật này. Như vậy đã xử lý source-level 2/9 vòng; còn **7 vòng nhỏ**: V9.3.1, V9.3.2, V9.4.1, V9.4.2, V9.5.1, V9.5.2 và V10.0. Tương ứng còn **4/5 đợt lớn**. Việc nghiệm thu PostgreSQL/Spring và các deployment gate của V9.2.3 là điều kiện đóng release, không phải một đợt tính năng mới trong bảng 9 vòng.
