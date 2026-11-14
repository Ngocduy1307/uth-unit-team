# Affordability Analysis Assistant - Backend Service

Dự án Trợ lý phân tích thu nhập và khả năng chi trả cho vay bán lẻ cá nhân tại Việt Nam (Đồ án Học kỳ Doanh nghiệp - Đơn vị đối tác: **UNIT**).

---

## 1. Yêu cầu môi trường
* **Java:** OpenJDK 21 (LTS)
* **Build Tool:** Maven 3.9+ (hoặc dùng sẵn Maven Wrapper `./mvnw` / `mvnw.cmd`)
* **Docker & Docker Compose:** Dùng để chạy nhanh PostgreSQL 16 và Camunda 8 Zeebe cục bộ

---

## 2. Cấu trúc thư mục Modular Monolith
Toàn bộ source code Backend được tổ chức theo chuẩn **Package-by-Feature (Modular Monolith)** nhằm giảm thiểu tối đa xung đột mã nguồn khi nhiều thành viên cùng phát triển:

```text
backend/src/main/java/vn/unit/affordability/
├── AffordabilityAssistantApplication.java  # Main Application Entrypoint
├── dossier/                                # Quản lý hồ sơ thẩm định & phân quyền Maker/Checker (INC 01)
├── statement/                              # Tiếp nhận sao kê (CSV/PDF), đối soát thu nhập & dòng tiền (INC 02 - INC 08)
├── financial/                              # Tính toán số học: DTI, chi phí sàn, 3 kịch bản stress-test (AFF 01 - AFF 09)
├── workflow/                               # Tích hợp Camunda 8 BPMN/DMN, Zeebe Job Workers (CAM 01 - CAM 08)
└── shared/                                 # Cấu hình dùng chung, WebClient, Outbox event, Exceptions
```

---

## 3. Hướng dẫn khởi chạy từ đầu (Step-by-Step)

### Bước 1: Khởi động cơ sở dữ liệu & Camunda 8 qua Docker Compose
Tại **thư mục gốc của dự án** (ngang hàng `backend/`, `frontend/`, `ai-service/`), file `docker-compose.yml` và file cấu hình mẫu `.env.example` đã được chuẩn hóa để toàn bộ nhóm dùng chung:
* **PostgreSQL 16** (port mặc định `5433` để tránh đụng độ port `5432` nếu máy đã cài Postgres)
* **Camunda 8 Zeebe Broker** (port mặc định `26500`)

```powershell
# Tại thư mục gốc của dự án:
# (Tùy chọn) Copy file .env.example thành .env nếu muốn tùy biến port cá nhân
Copy-Item .env.example .env

# Khởi chạy các service ngầm
docker compose up -d

# Kiểm tra trạng thái container
docker compose ps
```

### Bước 2: Chuẩn bị file cấu hình môi trường local
File cấu hình mật khẩu thật `application-local.yml` đã được đưa vào `.gitignore` để tránh rò rỉ secrets. Tạo file cấu hình từ file mẫu:

```powershell
# Trên PowerShell (tại thư mục backend)
Copy-Item src/main/resources/application.example.yml src/main/resources/application-local.yml
```
*(Nếu dùng Docker Compose ở Bước 1, thông số mặc định trong `application.example.yml` đã khớp sẵn với PostgreSQL port 5433 và Camunda Zeebe port 26500).*

### Bước 3: Kiểm thử và khởi chạy ứng dụng Spring Boot
```powershell
# 1. Chạy Unit Test kiểm tra build xanh
./mvnw clean test

# 2. Chạy ứng dụng
./mvnw spring-boot:run
```
Khi ứng dụng khởi động thành công:
* **Flyway Migration:** Tự động kết nối PostgreSQL 16 và tạo các bảng `dossiers`, `evidence_records`, `outbox_events`.
* **Zeebe Client:** Tự động kết nối đến Camunda Zeebe Gateway tại `localhost:26500`.
* **Tomcat Server:** Lắng nghe tại cổng `http://localhost:8080`.

### Bước 4: Kiểm tra Health Check API
Mở trình duyệt hoặc chạy lệnh PowerShell để kiểm tra trạng thái hệ thống:
```powershell
Invoke-RestMethod -Uri "http://localhost:8080/api/v1/health" -Method Get
```
Kết quả trả về:
```json
{
  "status": "UP"
}
```
