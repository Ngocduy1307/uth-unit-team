# RBAC catalogue and ownership contract

## Important boundary

Spring Boot / SSO is the authoritative source for identity, authentication, role assignment and permission enforcement. DATA-AI's `staff_users`, `access_roles`, `staff_user_roles`, `permissions`, and `role_permissions` are a mirror/reference catalogue used for integration, display and audit. A permission row in this database alone never grants access.

## Roles

| Role | Scope | Responsibility |
|---|---|---|
| CUSTOMER | Own customer/application | Own profile, application and evidence submission |
| MAKER | Assigned cases in own bank | Prepare evidence and analysis; cannot Checker-review own work |
| CHECKER | Assigned cases in own bank | Independent review; cannot review own work |
| BANK_ADMIN | Own bank | Manage staff and bank-scoped configuration; no credit approval |
| BANK_POLICY_OWNER | Own bank/product | Own policy versions/effective dates; does not approve a customer loan |
| NAMED_AUTHORITY | Explicit bank-defined delegation scope | Approve/reject a specific Override/Policy Exception proposal only when Backend/SSO proves a current authority grant |
| DATA_AI_STAFF | Explicitly assigned internal scope | Data quality, source mapping and authorized export |
| SYSTEM_ADMIN | Platform | Platform configuration; sensitive customer access remains separately authorized and audited |
| DATA_AI_SERVICE | Service identity | Non-interactive service-to-service access only; no human login |
| WORKFLOW_ORCHESTRATOR | Dedicated Camunda integration service | Process correlation, signed callbacks, transactional outbox delivery; no human task completion |
| RELEASE_AUTHORITY | Explicit release gate authority | Records externally authorized G4 Operational reference; actual authority grant remains Backend/SSO-owned |
| BUSINESS_ENGINE | Dedicated Business Engine service identity | Writes external override-application receipts only; assertion must contain this role alone |

Do not use a generic `ADMIN` alias. It is ambiguous between bank and platform authority and is not accepted by the current administrative permission gates.

## Permission codes

`CUSTOMER_VIEW`, `CUSTOMER_UPDATE`, `APPLICATION_VIEW`, `DOCUMENT_UPLOAD`, `DOCUMENT_REVIEW`, `MAKER_SUBMIT`, `CHECKER_REVIEW`, `STAFF_MANAGE`, `ROLE_ASSIGN`, `FORM_MANAGE`, `AUDIT_VIEW`, `DATA_EXPORT`, `POLICY_MANAGE`, `SOURCE_MAPPING_MANAGE`, `OVERRIDE_APPROVE`, `POLICY_EXCEPTION_APPROVE`, `CASE_GOVERNANCE_AUDIT_VIEW`, `WORKFLOW_BINDING_MANAGE`, `WORKFLOW_EVENT_RECEIVE`, `WORKFLOW_OUTBOX_DELIVER`, `CASE_EVIDENCE_REQUEST`, `CASE_WORKFLOW_REOPEN`, `CASE_RELEASE_GATE_RECORD`, `CASE_EXPORT_PACKAGE_CREATE`, `OVERRIDE_APPLICATION_RECEIPT_WRITE`.

`role_permissions` is a starter/reference matrix. Backend must enforce object scope, assignment scope, purpose, segregation of duties and explicit permissions at every API path. Never infer a Maker/Checker permission solely from a frontend menu or task assignment.

## Assignment history

Every role mirror change received by `/api/v1/internal/staff-sync` writes `ASSIGNED` or `REVOKED` to `staff_role_assignment_history` and a management audit event. Backend remains responsible for approving the grant, validating the grantor, recording business reason and delivering the authoritative event.

## Maker / Checker invariants

- Maker and Checker must be different authenticated identities for the same case and review cycle.
- Maker cannot invoke Checker completion by calling an API directly.
- Bank Admin and System Admin cannot turn administrative access into business review completion.
- Reassignment, process administration or service identity cannot grant business approval.
- Every review/override/export/admin action must include actor, case, version, timestamp and reason where applicable.

## Known implementation boundary

The current DATA-AI service does not implement the full external workflow state machine or policy approval engine. V9.5.1 provides correlation, inbox/outbox and evidence-lifecycle adapters only. BPMN/DMN/task routing and actual policy execution belong to Camunda/Backend and the Bank Business Engine; do not infer a business decision from DATA-AI metadata. The catalogue endpoint `/api/v1/admin/access-control/catalog` is read-only. Role history is available at `/api/v1/admin/staff/{staff_id}/role-history` for scoped administrators.


## V15 Named Authority and case governance permissions

V15 adds the reference role `NAMED_AUTHORITY` and permission codes `OVERRIDE_APPROVE`, `POLICY_EXCEPTION_APPROVE` and `CASE_GOVERNANCE_AUDIT_VIEW`. The role/permission rows are integration metadata only: they do not validate a delegation, authority limit, product scope, approval ceiling or effective date. Backend/SSO must validate those attributes and include the grant/scope references in the signed request. `NAMED_AUTHORITY` cannot be combined with `MAKER`, `CHECKER`, `BANK_ADMIN`, `SYSTEM_ADMIN`, `DATA_AI_STAFF` or `DATA_AI_SERVICE` for a decision. The Named Authority must also be a different actor from both the Maker and the Checker on the linked version.

`case_audit_entries`, `case_override_requests` and `case_override_events` are append-only. Approval is a record attached to one immutable V14 version and proposal hash; DATA-AI does not apply it.


## V16 / V9.5.1 workflow integration roles

- `WORKFLOW_ORCHESTRATOR` is a dedicated signed service identity for process binding, event callbacks and outbox claim/ACK. It must not be assigned to human staff and is not allowed to complete Maker/Checker/Authority work.
- `BUSINESS_ENGINE` is a dedicated single-role assertion for `OVERRIDE_APPLICATION_RECEIPT_WRITE`. The application-receipt route rejects combined role sets; the receipt proves that an external engine applied a previously approved proposal.
- `RELEASE_AUTHORITY` records a G4 external gate reference after Backend/SSO validates the actual grant. It does not run G4 operational tests.
- MAKER/CHECKER and BANK_POLICY_OWNER receive case workflow permissions as defined by V16, but role codes in DATA-AI remain a mirror. Backend/SSO must check the human's active assignment, task, bank/product scope, authority limit, purpose and effective dates for every call.
