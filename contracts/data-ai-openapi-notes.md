# DATA-AI API contract
Base path: `/api/v1`; JSON uses UTF-8; identifiers are UUID strings; dates use ISO-8601.
All protected endpoints accept `X-Internal-Service-Token` when `INTERNAL_SERVICE_TOKEN` is configured.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | none | service status |
| GET | `/ready` | none | DB readiness |
| POST | `/cases` | `external_case_id`, `bank_id`, `analysis_date?` | case |
| GET | `/cases/{caseId}` | none | case |
| POST | `/cases/{caseId}/documents` | multipart `file` | document manifest |
| POST | `/cases/{caseId}/documents/{documentId}/process` | none | pipeline result |
| GET | `/cases/{caseId}/documents` | none | documents |
| GET | `/cases/{caseId}/fields` | none | extracted OCR tokens/fields |
| GET | `/cases/{caseId}/transactions` | none | normalized transaction rows |

Upload document response includes `id`, `case_id`, `original_filename`, `sha256`, `document_type`, `layout_code`, `evidence_status`, `processing_status`, `page_count`.

## Integration rules
- Frontend calls Spring Boot only. Never expose this service or PostgreSQL directly to a browser.
- Spring Boot owns public authentication, user authorization, tenant/bank context and API gateway policy. Internal token is service-to-service protection, not end-user RBAC.
- Backend supplies its stable `external_case_id` and `bank_id`; agree on their exact formats before integration.
- Do not pass customer names, account numbers, statement contents or amounts into Camunda variables. Pass opaque IDs and routing state only.
- DATA-AI output is evidence suggestion. Maker validates account ownership, currency, statement period, fields and eligibility.
- No DSR/residual calculation, policy decision, loan approval/rejection or disbursement is exposed by this service.
