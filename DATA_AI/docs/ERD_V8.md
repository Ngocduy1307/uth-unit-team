# ERD database DATA-AI V8

> Phạm vi: schema PostgreSQL `data_ai`, kế thừa V1–V7 và các thay đổi additive của V8. Đây là ERD logic/vật lý ở mức bảng và khóa. Authentication, quyết định tín dụng và workflow điều phối vẫn thuộc Backend/SSO/Camunda theo phân công dự án.

## 1. Quy ước

- `PK`: khóa chính; `FK`: khóa ngoại; `UQ`: unique; `NN`: not null.
- `1 — 0..N`: một bản ghi cha có thể có không hoặc nhiều bản ghi con.
- `1 — 0..1`: quan hệ một-một tùy chọn.
- Bảng liên kết N-N: `staff_user_roles`, `role_permissions`.
- `cases` là aggregate root cho một lần xử lý hồ sơ. Chứng từ, giao dịch, OCR, khai báo và evidence phải gắn với `case_id`, không chỉ gắn customer.
- `cases.bank_id` là mã ngân hàng dạng text từ V1, giữ để tương thích. V8 thêm `cases.bank_organization_id` (UUID FK) nhưng KHÔNG tự suy diễn/migrate dữ liệu cũ. Backfill sau khi đối chiếu `bank_organizations.bank_code`.
- `bank_id` trong `customer_profiles` là UUID FK tới `bank_organizations`. Khách hàng có thể dùng chung nền tảng nhưng dữ liệu theo ngân hàng phải được phân vùng bằng quyền truy cập ở Backend và/hoặc tenant context.
- V8 dùng các FK `NOT VALID` có chủ đích để migration không thất bại do dữ liệu lịch sử chưa được đối soát. Các FK này vẫn áp dụng cho thao tác ghi mới. Chỉ `VALIDATE CONSTRAINT` sau khi preflight không còn orphan/mismatch.

## 2. Sơ đồ tổng thể

Mở file `ERD_V8.svg` để xem toàn bộ sơ đồ có thể phóng to; `ERD_V8.png` để chèn vào báo cáo; `ERD_V8.mmd` là Mermaid source có thể chỉnh sửa.

## 3. Phân miền và bảng

### A. Organization, staff và RBAC

| Bảng | PK | FK chính | Vai trò |
|---|---|---|---|
| `bank_organizations` | `id` | — | Danh mục ngân hàng/tenant |
| `bank_branches` | `id` | `bank_id → bank_organizations.id` | Chi nhánh thuộc ngân hàng |
| `staff_users` | `id` | `bank_id → bank_organizations.id`; `branch_id → bank_branches.id` | Hồ sơ nhân viên mirror từ Backend/SSO |
| `access_roles` | `id` | — | Danh mục vai trò |
| `staff_user_roles` | (`staff_user_id`,`role_id`) | staff, role, `assigned_by → staff_users.id` | Liên kết N-N nhân viên-vai trò |
| `permissions` | `id` | — | Danh mục permission |
| `role_permissions` | (`role_id`,`permission_id`) | role, permission | Liên kết N-N role-permission |
| `staff_role_assignment_history` | `id` | staff, role | Lịch sử ASSIGNED/REVOKED, append-only |
| `management_audit_logs` | `id` | bank, actor staff | Nhật ký quản trị |

### B. Customer và loan application

| Bảng | PK | FK chính | Vai trò |
|---|---|---|---|
| `customer_profiles` | `id` | `bank_id → bank_organizations.id` | Thông tin định danh tối thiểu của khách hàng |
| `customer_addresses` | `id` | `customer_id → customer_profiles.id` | Một khách hàng có nhiều địa chỉ |
| `customer_employments` | `id` | `customer_id → customer_profiles.id` | Lịch sử/khai báo việc làm |
| `cases` | `id` | V8: `customer_id → customer_profiles.id`; `bank_organization_id → bank_organizations.id` | Hồ sơ xử lý trung tâm; `bank_id` text legacy |
| `loan_applications` | `id` | `case_id → cases.id` (unique); `customer_id → customer_profiles.id` | Thông tin khoản vay đề nghị; V8 thêm composite FK case/customer |
| `applicant_submissions` | `id` | `case_id → cases.id` | Snapshot form/version đã gửi |
| `form_definitions` | `id` | `created_by → staff_users.id` | Định nghĩa phiên bản biểu mẫu |
| `form_field_definitions` | `id` | `form_definition_id → form_definitions.id` | Cấu hình trường của form |
| `consent_events` (V8) | `id` | composite `(case_id,customer_id) → cases` | Sự kiện đồng ý/rút lại theo mục đích và phiên bản thông báo |

### C. Customer financial declarations

| Bảng | PK | FK chính | Vai trò |
|---|---|---|---|
| `customer_household_profiles` | `id` | `customer_id → customer_profiles`; `case_id → cases`; V8 composite case/customer | Khai báo hộ gia đình theo hồ sơ |
| `customer_expense_declarations` | `id` | `case_id → cases` | Chi phí khách hàng khai báo |
| `customer_liability_declarations` | `id` | `case_id → cases` | Nghĩa vụ nợ khách hàng khai báo |
| `customer_salary_accounts` | `id` | `case_id → cases`; `evidence_document_id → documents` | Tài khoản nhận lương, chỉ lưu last4; tối đa 3/case bằng trigger V8 |
| `customer_declaration_revisions` | `id` | `case_id → cases`; self-FK `supersedes_id`; V8 composite case/customer | Snapshot lịch sử khai báo, append-only |

V8 thêm `client_request_id` để idempotency cho các API khai báo. API cần gửi UUID này; DB có unique partial index theo `(case_id, client_request_id)`. Không thay thế việc kiểm tra quyền hay validation ở API.

### D. Documents, OCR, transaction, evidence và ledger

| Bảng | PK | FK chính | Vai trò |
|---|---|---|---|
| `documents` | `id` | `case_id → cases` | Metadata file chứng từ, hash, trạng thái xử lý |
| `document_security_events` (V8) | `id` | `document_id → documents` | Lịch sử quét mã độc/bảo mật, append-only |
| `extracted_fields` | `id` | `document_id → documents` | Giá trị OCR, confidence, page, bbox, review status |
| `transactions` | `id` | `case_id → cases`; `document_id → documents` | Dòng giao dịch đã parse |
| `processing_results` | `id` | `case_id → cases`; `document_id → documents` | Kết quả xử lý pipeline |
| `pipeline_runs` | `id` | `case_id → cases`; `document_id → documents` | Lần chạy pipeline, idempotency key |
| `payroll_evidence` | `id` | `case_id → cases`; `document_id → documents`; V8 source-field FK tới `extracted_fields` | Bằng chứng bảng lương đã trích xuất |
| `earning_match_candidates` | `id` | `case_id → cases`; `payroll_evidence_id`; `transaction_id` | Gợi ý đối chiếu lương với giao dịch |
| `income_ledger_months` | `id` | `case_id → cases` | Tổng hợp thu nhập quan sát/được chấp nhận theo tháng |
| `data_quality_issues` | `id` | `case_id → cases`; `document_id → documents` | Vấn đề chất lượng dữ liệu |

### E. Data governance, mapping, audit và export

| Bảng | PK | FK chính | Vai trò |
|---|---|---|---|
| `source_inventory` | `id` | — | Danh mục nguồn chứng từ/dữ liệu |
| `field_mapping_registry` | `id` | logical reference `source_code/schema_version` tới source inventory | Mapping trường nguồn → trường chuẩn; hiện chưa có FK vật lý |
| `audit_events` | `id` | `case_id → cases` | Nhật ký sự kiện theo hồ sơ; V8 append-only |
| `export_jobs` | `id` | `bank_id` là mã text, chưa có FK vật lý | Metadata job xuất dữ liệu, không lưu nội dung workbook |

## 4. Cardinality quan trọng

- `bank_organizations 1:N bank_branches`, `staff_users`, `customer_profiles`.
- `customer_profiles 1:N customer_addresses`, `customer_employments`, `cases`.
- `cases 1:0..1 loan_applications` (một case tối đa một loan application do unique `case_id`).
- `cases 1:N applicant_submissions`, `documents`, `transactions`, `payroll_evidence`, `pipeline_runs`, `processing_results`, `data_quality_issues`, `income_ledger_months`, declarations và audit events.
- `documents 1:N extracted_fields`; `documents 1:N document_security_events`.
- `payroll_evidence N:N transactions` thông qua `earning_match_candidates`.
- `form_definitions 1:N form_field_definitions`.
- `staff_users N:N access_roles` qua `staff_user_roles`; `access_roles N:N permissions` qua `role_permissions`.

## 5. Các ranh giới không được nhầm

1. `customer_profiles` là hồ sơ khách hàng; `cases` là từng hồ sơ vay/xử lý. Một khách hàng có thể có nhiều case.
2. `monthly_income_declared` và dữ liệu khách hàng khai báo không phải thu nhập đã xác minh.
3. `extracted_fields` là kết quả OCR; `payroll_evidence` là evidence đã cấu trúc; `earning_match_candidates` chỉ là gợi ý đối chiếu; `income_ledger_months.accepted_amount` chỉ được cập nhật sau review/approval đúng workflow.
4. `role_permissions` trong DATA-AI là catalog/mirror. Backend/SSO vẫn là nơi xác thực và thực thi authorization theo actor, bank, branch, case và segregation of duties.
5. Không bật RLS chỉ bằng migration V8 nếu Backend chưa thiết lập transaction-local tenant/actor context cho mọi connection. Bật RLS mà quên context có thể chặn hợp lệ hoặc tạo false sense of security.

## 6. Hạn chế hiện tại cần ghi nhận khi bàn giao

- Các FK V8 dùng `NOT VALID` cần preflight và validate sau khi reconcile dữ liệu cũ.
- `cases.bank_id` legacy là text; backfill `bank_organization_id` phải có mapping được duyệt, không tự cast.
- `field_mapping_registry.source_code/schema_version` chưa được FK tới `source_inventory`; cần migration riêng sau khi kiểm tra orphan và quyết định khóa nghiệp vụ.
- V8 thêm schema và trigger; cần đồng bộ ORM, Pydantic, API, OpenAPI, export và test integration trước production rollout.
- V8 không tự tạo workflow Maker-Checker, không cấp quyền cho Admin, không thực thi quyết định tín dụng, không tự quét file. Các service tương ứng phải gọi và ghi kết quả vào các bảng này.
