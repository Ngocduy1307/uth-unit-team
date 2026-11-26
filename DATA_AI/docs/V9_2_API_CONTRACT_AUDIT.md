# V9.2.0 - API contract alignment audit

## Scope of this increment

This is a deliberately narrow, non-breaking contract-governance increment. It does not add
business logic, change endpoint behavior, or claim that Camunda orchestration is complete.

## Baseline observed

- FastAPI exposes 26 paths and 28 HTTP operations in the `/api/v1` namespace, plus `/health`
  and `/ready` operational endpoints.
- The checked-in OpenAPI artifact contains the same 26 paths and 16 component schemas as the
  runtime-generated specification at the time of this audit.
- Every `/api/v1/**` operation publishes the `X-Internal-Service-Token` header. V9.2.2 additionally publishes `X-Service-Assertion` on every protected API operation.
- The token is conditionally enforced by runtime configuration: required when configured;
  tokenless mode is allowed only when `APP_ENV` is `development` or `test`.
- Actor and bank context headers vary by operation. Their presence in OpenAPI is not proof of
  authorization correctness; endpoint-level role and tenant-scope behavior still needs targeted
  integration tests.

## Changes in this increment

1. Regenerated `contracts/data-ai-openapi.json` from the live FastAPI application.
2. Replaced the abbreviated API notes with the full implemented endpoint inventory and trust
   boundary rules.
3. Added regression tests to detect OpenAPI drift, missing internal-token header declarations,
   and unversioned API paths.
4. Recorded workflow capabilities that are not established by the current API inventory, so
   tables/endpoints are not mistaken for completed workflow behavior.

## Workflow traceability

| Workflow stage | Current API evidence | Audit conclusion |
|---|---|---|
| Intake case | Create/read case | Partially supported |
| Receive evidence | Upload/list documents | Supported at API level; malware scanning and immutable object storage remain release gates |
| OCR/extraction | Process document/read fields/transactions | Supported as extraction pipeline; maker verification remains external/manual |
| Quality/lineage | Quality issues and pipeline runs | Read surfaces exist; full workflow transition not proven |
| Applicant intake | Applicant submission and customer/application endpoints | Snapshot/intake support exists; consent authorization remains Backend-owned |
| Maker verification | No dedicated task/decision API established | Not proven complete |
| Debt schedule and affordability | No corresponding calculation API established | Out of DATA-AI business-logic scope; must be owned by approved calculation service |
| Stress/policy routing | No corresponding API established | Not proven complete |
| Freeze/checker/override | Staff/audit metadata exists, but no complete decision lifecycle proven | Not proven complete |
| Shadow/operational gates | No release-gate API established | Not proven complete |
| Expiry/reopen | No corresponding lifecycle API established | Not proven complete |

## Verification

Run:

```bash
pytest -q
```

The new checks compare the checked-in OpenAPI JSON with `app.main:app`, assert internal token
header publication for every internal API operation, and enforce `/api/v1` path versioning.

## Explicit limitations

This pass does not connect to a live PostgreSQL instance, Spring Boot deployment, or Camunda 8
cluster. It does not prove authentication headers are injected correctly in production, that
bank-level authorization is correct for every route, or that all Workflow nodes are executable.
Those require integration tests with the owning services and representative tenant fixtures.
