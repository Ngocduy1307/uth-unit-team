# Báo cáo kỹ thuật DATA–AI Engineer

## 1. Mục tiêu
Xây dựng dịch vụ hỗ trợ tiếp nhận bằng chứng, OCR, chuẩn hóa và cung cấp dữ liệu có thể truy vết cho hệ thống Trợ lý phân tích thu nhập và khả năng trả nợ. Dịch vụ không thay thế nhân viên ngân hàng và không quyết định tín dụng.

## 2. Công nghệ
Python 3.11+, FastAPI, SQLAlchemy 2, PostgreSQL 16, Flyway 10, PyMuPDF, Pillow, Tesseract OCR, Pydantic Settings, Docker Compose, Pytest.

## 3. Pipeline
1. Nhận file và kiểm tra phần mở rộng/kích thước.
2. Sinh tên lưu trữ nội bộ, tính SHA-256 và chống trùng trong cùng hồ sơ.
3. Ghi manifest vào PostgreSQL.
4. PDF/ảnh: OCR theo trang, lưu token, confidence, page và bounding box.
5. CSV: đọc UTF-8, nhận diện header alias demo, chuẩn hóa ngày/số tiền, phân loại gợi ý giao dịch.
6. Lưu processing result và audit event.
7. Trả dữ liệu qua API cho Backend để Maker rà soát.

## 4. Mô hình dữ liệu
`cases`, `documents`, `extracted_fields`, `transactions`, `processing_results`, `audit_events`, `source_inventory`, `field_mapping_registry`, `payroll_evidence`, `earning_match_candidates`, `income_ledger_months`, `data_quality_issues`, `pipeline_runs`.

## 5. Flyway
`V1__create_data_ai_core.sql` tạo schema và bảng lõi; `V2__add_data_lineage_and_income_evidence.sql` bổ sung registry, payroll evidence, matching candidates, ledger tháng, quality issues và pipeline runs.

## 6. API
Xem `contracts/data-ai-openapi-notes.md`. Swagger được FastAPI sinh tại `/docs` khi service chạy.

## 7. Giới hạn và công việc còn cần phê duyệt
Bộ 6 layout, 20 field definitions, hai bank CSV schemas, rule mapping chính thức, threshold confidence, dữ liệu gán nhãn, malware scanner, sandbox, immutable storage, tenant isolation, TLS, encryption-at-rest, retention, SSO/RBAC và kiểm thử nghiệm thu chưa được cung cấp/triển khai đầy đủ. Không tuyên bố đạt các tiêu chí nghiệm thu khi chưa có dữ liệu và kết quả đo.

## 8. Tiêu chí kiểm thử cần chạy ở dự án
- Intake: 100 kịch bản file lỗi, file trùng, vượt giới hạn, encoding lỗi.
- Classification: Macro F1 >= 0.90 trên bộ 400 hồ sơ có nhãn độc lập.
- Extraction: accuracy >= 95% trên coverage >= 80% theo field trọng yếu.
- Matching: accuracy >= 98% trên coverage >= 80%.
- Data quality: 0 hồ sơ có bằng chứng lỗi được chuyển trạng thái sẵn sàng duyệt.
Các con số trên là tiêu chí SRS, không phải kết quả đã đạt của source baseline.
