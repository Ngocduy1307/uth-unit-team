# Local demo: customer form -> PostgreSQL -> Excel

1. Start stack: `docker compose up --build -d`.
2. Seed sample records: `docker compose exec api python -m scripts.seed_demo`.
3. Open Swagger: `http://localhost:8001/docs`.
4. Inspect PostgreSQL schema `data_ai` in pgAdmin/DBeaver. Expected customer tables include `customer_profiles`, `customer_addresses`, `customer_employments`, `loan_applications`, `cases` and `applicant_submissions`.
5. Create a bank row through seed script or admin-managed bank reference data before submitting a new application.
6. Create a customer using `POST /api/v1/customers`. Include `customer_code`, `full_name`, `phone`, and optional address/employment objects.
7. Create the case/application using `POST /api/v1/customers/{customer_id}/applications`. `bank_id` must equal an active `bank_organizations.bank_code`.
8. For a staff export, call `GET /api/v1/admin/exports/excel` from Backend only. Backend must provide trusted headers `X-Actor-Id`, `X-Actor-Roles`, `X-Bank-Id` and internal token. `X-Bank-Id` must match the case `bank_id` (bank code).
9. Open the `.xlsx` file and verify customer/profile/application sheets alongside DATA-AI evidence sheets.

In local development with `INTERNAL_SERVICE_TOKEN` configured, Swagger's Authorize button is not automatically wired to custom headers. Use a REST client such as Postman, or temporarily set an isolated local token and configure headers. Never disable authentication or expose the token in a public browser deployment.
