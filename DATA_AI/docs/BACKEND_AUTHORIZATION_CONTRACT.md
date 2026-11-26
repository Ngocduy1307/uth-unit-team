# Backend authentication and authorization contract

## Ownership boundary

Spring Boot is the only public entry point for browser clients. It owns customer login, staff/admin login, password hashing or identity-provider integration, MFA, session/refresh-token lifecycle, logout, account recovery, rate limiting and authoritative authorization. DATA-AI is a private internal service and must never be called directly by a browser.

Never add password, password_hash, OTP, refresh-token or session columns to `customer_profiles` or `staff_users`. `external_identity_id` is a reference to the identity managed by Backend/SSO, not a credential.

## Suggested role model

| Principal | Role | Allowed scope |
|---|---|---|
| Customer | CUSTOMER | Own profile, own application, own uploads and own application status only |
| Bank staff | MAKER | Assigned cases in own bank; prepare evidence and analysis; cannot Checker-review own work |
| Bank staff | CHECKER | Assigned cases in own bank; independently review Maker output; cannot review own work |
| Bank admin | BANK_ADMIN | Manage staff and configuration within own bank; no cross-bank access |
| Platform admin | SYSTEM_ADMIN | Platform-level configuration; sensitive customer data access remains explicitly audited |
| Named bank authority | NAMED_AUTHORITY | Approve/reject only the bank-scoped Override/Policy Exception requests covered by an active Backend/SSO-validated authority grant |
| Service identity | DATA_AI_SERVICE | Call only approved internal DATA-AI endpoints; no interactive login |

A person may have more than one staff role only if the bank's segregation-of-duties policy allows it. A Maker and Checker must be different authenticated identities for the same case and review cycle.

## Permission matrix

| Action | CUSTOMER | MAKER | CHECKER | BANK_ADMIN | SYSTEM_ADMIN |
|---|---:|---:|---:|---:|---:|
| View own profile/application | Yes | No | No | No | Audited support only |
| Create own application | Yes | No | No | No | No |
| Upload evidence to own application | Yes | No | No | No | No |
| View assigned case evidence | No | Yes | Yes | Scoped support | Audited |
| Edit extraction review / prepare analysis | No | Yes | No | No | No |
| Submit to Checker | No | Yes | No | No | No |
| Complete independent review | No | No | Yes | No | No |
| Manage bank staff and bank form config | No | No | No | Own bank | All banks |
| View audit history | Own activity only | Assigned-case scope | Assigned-case scope | Own bank | Platform scope |
| Export customer financial data | No | Explicit case scope only | Explicit case scope only | Explicit bank scope | Explicit audited scope |

## Mandatory Backend checks

1. Authenticate every request. Do not trust customer ID, staff ID, role, bank ID, case ID or tenant ID supplied by the browser.
2. Derive actor ID, roles and bank scope from the authenticated server-side principal.
3. For customers, enforce `application.customer_id == authenticated_customer_id` on every read, update, upload and download.
4. For staff, enforce `case.bank_id == authenticated_bank_id` and assignment/role scope on every case operation. Never rely on UI hiding.
5. Enforce Maker/Checker separation server-side, including direct API calls and retries.
6. Use least privilege, MFA for administrators, short-lived access tokens, secure refresh-token rotation, CSRF protection for cookie sessions, rate limits and audit logs.
7. Keep `X-Internal-Service-Token`, database credentials and service secrets only in server-side secret storage. Never expose them to frontend bundles or API responses.
8. DATA-AI internal headers (`X-Actor-Id`, `X-Actor-Roles`, `X-Bank-Id`) may only be populated by the trusted Backend after authentication. Production calls must include both `X-Internal-Service-Token` and `X-Service-Assertion` (HMAC request signature binding method/path/query/body/issuer/audience/timestamp/nonce/actor/roles/bank). Block direct public access to DATA-AI and use TLS/private networking plus secret rotation.
9. Scope every customer/case/document/export query by bank and authorized subject. A guessed UUID must not reveal another customer's record.
10. Audit privileged reads, exports, staff-role changes, form publication, evidence replacement and every Maker/Checker transition.

## Required Backend routes (illustrative contract)

- `POST /api/auth/customer/register` or bank-approved customer onboarding.
- `POST /api/auth/customer/login`, `POST /api/auth/customer/logout`, `POST /api/auth/customer/refresh`.
- `POST /api/auth/staff/login` or SSO callback; admin login uses MFA.
- `GET /api/customer/me`, `GET /api/customer/applications`, `POST /api/customer/applications`.
- `GET /api/staff/cases`, `GET /api/staff/cases/{caseId}` with bank/assignment scope.
- `POST /api/staff/cases/{caseId}/maker-submit`.
- `POST /api/staff/cases/{caseId}/checker-review`.
- `GET/POST/PATCH /api/admin/staff...` with BANK_ADMIN/SYSTEM_ADMIN scope.
- `GET /api/admin/audit-logs` and export routes with explicit scope and audit.

These are Backend-owned routes, not new public DATA-AI endpoints. Final route names should follow the team's existing Spring Boot API contract.

## Current ZIP findings that must be fixed before a real multi-bank pilot

- The DATA-AI service uses a shared internal token plus V9.2.2 signed service assertions in production. These are service-to-service gates, not end-user authentication.
- Customer list/detail endpoints are not independently tenant-scoped inside DATA-AI. Backend must enforce scope, and the internal service should also apply bank/case scope as defense in depth before multi-bank pilot.
- `GET /api/v1/customers` accepts an optional `bank_id`; never let the browser choose this value or treat it as authorization.
- Staff/admin APIs trust `X-Actor-*` headers only under the internal-token/private-network assumption. Ensure only Spring Boot can reach the service and can set those headers.
- V7 adds `permissions`, `role_permissions`, `BANK_POLICY_OWNER` and append-only staff role assignment history. This is a reference catalogue only. Backend must implement authoritative permission checks, object/assignment scope and Maker/Checker separation; a role name alone is not sufficient.


## DATA-AI read-only access-control reference endpoints

- `GET /api/v1/admin/access-control/catalog`: returns roles and permission-code mapping; Backend remains authoritative.
- `GET /api/v1/admin/staff/{staff_id}/role-history`: returns mirrored role assignment/revocation history to a scoped BANK_ADMIN or SYSTEM_ADMIN.

Customer detail/list responses are minimized and customer reads are written to `management_audit_logs`. New customer application creation checks trusted actor roles and the caller bank code. These checks do not replace Backend's own authorization.


## V9.4.2 Named Authority and Override contract

- `NAMED_AUTHORITY` is a DATA-AI role-catalogue reference, not a self-granting permission. Backend/SSO must verify the actor's active named-authority grant, bank/product/policy scope, authority limits, effective dates, task assignment and any required MFA before signing the request to DATA-AI.
- A Maker submits an immutable `OVERRIDE` or `POLICY_EXCEPTION` proposal against a specific V14 version. The proposal includes an exception code, bank policy reference/version, reason, proposed-change JSON, impact summary and at least one same-case evidence reference. The proposal is SHA-256-bound to the version snapshot and evidence references.
- Only a distinct `NAMED_AUTHORITY` actor may approve/reject, and that actor must differ from both the proposing Maker and the technical Checker for the linked version. The signed request body must carry `authority_grant_ref` and `authority_scope_ref`; DATA-AI records these references but does not independently validate delegation, amount limits or policy eligibility.
- An approval requires a timezone-aware `valid_until`. Expiry is reported as a derived `EXPIRED` status; the scheduled expiry notification/timer and escalation remain Backend/Camunda responsibilities.
- `APPROVED` means the named authority approved the exact proposal hash within the referenced grant. It does not apply the override, change the bank policy, update calculations, imply a lending decision or complete a Camunda task. Backend/Business Engine must separately validate and execute the authorized change under the bank's policy implementation.
- DATA-AI audit entries are case-scoped and hash chained. Hash verification detects sequence/payload/previous-hash alteration, but is not a digital signature or an externally anchored WORM guarantee. DB-owner access, independent log export/retention and SIEM/WORM anchoring remain production controls.
