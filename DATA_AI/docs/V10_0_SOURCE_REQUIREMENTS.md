# V10.0 Source Requirements and Authority Boundaries

## Source basis

This V10.0 DATA-AI completion was derived from:

1. User-supplied `Workflow(4).drawio` (preserved byte-for-byte as `docs/Workflow.drawio`).
2. User-supplied `Bao_cao_He_thong_UNIT_Camunda8_va_Cong_nghe_OCR.docx` (preserved as supplied under `docs/`).
3. User-supplied V9.5.2 production-hardening source ZIP and matching SHA-256 file.

## Requirements taken from the report

- Scope is one VND unsecured consumer-loan product, monthly installments, 6–36 months, for Vietnam-resident individuals receiving salaried bank transfers. Self-employed income, cash salary, FX, co-borrowers, mortgage and revolving credit-card debt are outside this scope.
- Collect evidence for income, living expenses and debt obligations; reconcile payslips to bank statements over six months; preserve an observed evidence trail.
- The product report expects one base and two stress scenarios, but the calculation service is separate from DATA-AI.
- DATA-AI must not automatically approve/reject, certify document legality, price interest or impute missing months as zero/average.
- Original files are immutable and SHA-bound; OCR fields retain page/row and bounding-box provenance; uncertain fields remain for Maker review.
- Camunda process variables contain only opaque IDs and routing state, never statements, customer names or monetary amounts.
- The report's OCR thresholds, 400-case independent validation, 1,000 exact-VND math validation and Camunda concurrency/performance tests are acceptance criteria, not results proven by source-level tests.

## Design refinements in V10.0

- The API returns `workflow_route_hint` for Camunda convenience, but the route owner remains Camunda/Bank DMN. The hint never executes a Timer or terminal case decision.
- Monthly observed-income ledger requires its own Maker review; the stored `accepted_amount` remains null. This ensures data extraction and evidence review are not confused with eligible-income approval.
- The Financial Engine receipt must identify the exact proposed schedule reference and match the same case/bundle/product/term. The output snapshot must contain that exact receipt before export.
- Idempotent retries are content-bound for Backend decision reference, declaration client request ID, proposed schedule reference and calculation reference. Reusing the same key/reference with different content produces HTTP 409.
- The monthly Maker ledger review must cite the relevant payslip and statement documents; a payslip payment date or the documented pay-period end is used only to map source evidence to a month.
- Financial Engine receives review outcomes and opaque evidence references, not Maker free-text comments or staff identifiers. Missing analysis dates remain an empty month window with an explicit blocker; DATA-AI does not synthesize six dates.

## What this source does not prove

The source package does not prove that a real bank SSO, BPMN/DMN deployment, Business Engine, OCR model training, KMS, ClamAV service, PostgreSQL migration or supervised shadow pilot is deployed. These remain integration/staging/pilot gates and are itemized in the V10.0 handoff.
