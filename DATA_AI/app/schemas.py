from datetime import datetime, timedelta
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class CaseCreate(BaseModel):
    external_case_id: str
    bank_id: str
    analysis_date: datetime | None = None

class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    external_case_id: str
    bank_id: str
    status: str
    created_at: datetime

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    case_id: UUID
    original_filename: str
    sha256: str
    document_type: str
    layout_code: str
    evidence_status: str
    processing_status: str
    page_count: int

from typing import Any
from pydantic import Field

class ApplicantSubmissionIn(BaseModel):
    applicant_ref: str = Field(min_length=1, max_length=120)
    form_version: str = Field(default="1.1", min_length=1, max_length=40)
    form_data: dict[str, Any]
    consent_reference: str = Field(min_length=1, max_length=160)

class ApplicantSubmissionOut(BaseModel):
    id: UUID
    case_id: UUID
    applicant_ref: str
    form_version: str
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)

from datetime import date
from decimal import Decimal
from typing import Any
from pydantic import field_validator

class AddressIn(BaseModel):
    address_type: str = "RESIDENTIAL"
    country_code: str = "VN"
    province_code: str | None = None
    province_name: str | None = None
    district_name: str | None = None
    ward_name: str | None = None
    street_address: str | None = None
    is_primary: bool = True

class EmploymentIn(BaseModel):
    employment_type: str = Field(min_length=1, max_length=40)
    employer_name: str | None = Field(default=None, max_length=200)
    employer_tax_code: str | None = None
    job_title: str | None = None
    industry: str | None = None
    work_phone: str | None = None
    work_address: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    monthly_income_declared: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    income_basis: str | None = Field(default=None, pattern="^(NET|GROSS)$")
    income_currency: str = "VND"
    is_current: bool = True

class CustomerCreate(BaseModel):
    customer_code: str = Field(min_length=3, max_length=100)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=8, max_length=30)
    email: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    nationality: str = "Vietnamese"
    identity_type: str | None = None
    identity_last4: str | None = None
    marital_status: str | None = None
    dependents_count: int | None = None
    preferred_contact_method: str | None = None
    bank_id: UUID | None = None
    address: AddressIn | None = None
    employment: EmploymentIn | None = None

    @field_validator("identity_last4")
    @classmethod
    def valid_identity_last4(cls, value):
        if value is not None and (len(value) != 4 or not value.isdigit()):
            raise ValueError("identity_last4 must contain exactly four digits")
        return value

    @field_validator("dependents_count")
    @classmethod
    def nonnegative_dependents(cls, value):
        if value is not None and (value < 0 or value > 30):
            raise ValueError("dependents_count must be between 0 and 30")
        return value

class CustomerUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    nationality: str | None = None
    marital_status: str | None = None
    dependents_count: int | None = None
    preferred_contact_method: str | None = None
    customer_status: str | None = None
    address: AddressIn | None = None
    employment: EmploymentIn | None = None

class LoanApplicationCreate(BaseModel):
    external_case_id: str
    bank_id: str
    requested_amount: Decimal
    requested_term_months: int
    loan_purpose: str
    product_code: str | None = None
    preferred_disbursement_account_last4: str | None = None
    form_version: str = "1.1"
    form_data: dict[str, Any] = Field(default_factory=dict)
    consent_reference: str = Field(min_length=1, max_length=160)

    @field_validator("requested_amount")
    @classmethod
    def positive_amount(cls, value):
        if value <= 0:
            raise ValueError("requested_amount must be positive")
        return value

    @field_validator("requested_term_months")
    @classmethod
    def valid_term(cls, value):
        if not 6 <= value <= 36:
            raise ValueError("requested_term_months must be between 6 and 36 for the MVP")
        return value

class StaffSyncIn(BaseModel):
    employee_code: str
    full_name: str
    email: str
    bank_id: UUID | None = None
    branch_id: UUID | None = None
    phone: str | None = None
    staff_type: str = "BANK_STAFF"
    external_identity_id: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["BANK_STAFF"])

class FormDefinitionUpdate(BaseModel):
    form_name: str
    version: str
    audience: str = "CUSTOMER"
    definition_json: dict[str, Any]
    fields: list[dict[str, Any]] = Field(default_factory=list)

class BankOrganizationIn(BaseModel):
    bank_code: str
    bank_name: str
    status: str = "ACTIVE"

class BankBranchIn(BaseModel):
    branch_code: str
    branch_name: str
    address: str | None = None
    status: str = "ACTIVE"

class OCRLayoutProfileOut(BaseModel):
    profile_id: str
    document_family: str
    format: str
    approval_status: str
    profile_status: str


class OCRFieldCatalogEntryOut(BaseModel):
    field_name: str
    data_type: str
    required: bool | None = None
    approval_status: str
    extraction_rule_count: int


class OCRCatalogOut(BaseModel):
    layout_catalog_version: str
    field_catalog_version: str
    authority: str
    bank_approval_status: str
    layout_profiles: list[OCRLayoutProfileOut]
    field_catalog: list[OCRFieldCatalogEntryOut]
    field_count: int
    layout_profile_count: int


class EvidenceReconciliationIn(BaseModel):
    pdf_document_id: UUID
    csv_document_id: UUID
    tolerance_vnd: Decimal = Field(default=Decimal("0"), ge=0, le=1_000_000, max_digits=12, decimal_places=2)


class EvidenceReviewIn(BaseModel):
    decision_code: str = Field(min_length=3, max_length=40)
    reason: str = Field(min_length=8, max_length=1000)
    evidence_refs: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("reason")
    @classmethod
    def reason_must_contain_meaningful_text(cls, value):
        normalized = value.strip()
        if len(normalized) < 8:
            raise ValueError("reason must contain at least eight non-whitespace characters")
        return normalized


class GovernanceFreezeIn(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def freeze_reason_must_be_meaningful(cls, value):
        value = value.strip()
        if len(value) < 8:
            raise ValueError("reason must contain at least eight non-whitespace characters")
        return value


class GovernanceCheckerReviewIn(BaseModel):
    decision: str = Field(pattern="^(CONFIRM|RETURN)$")
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def checker_reason_must_be_meaningful(cls, value):
        value = value.strip()
        if len(value) < 8:
            raise ValueError("reason must contain at least eight non-whitespace characters")
        return value

# V9.4.2: Maker proposals and Named Authority decisions are separate from
# Checker technical review and never mutate policy or execute business rules.
import json as _json
from datetime import timezone as _timezone
from pydantic import model_validator


class OverrideRequestIn(BaseModel):
    request_kind: str = Field(pattern="^(OVERRIDE|POLICY_EXCEPTION)$")
    exception_code: str = Field(min_length=2, max_length=80, pattern="^[A-Z][A-Z0-9_]{1,79}$")
    policy_reference: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=12, max_length=2000)
    requested_change: dict[str, Any]
    impact_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[UUID] = Field(min_length=1, max_length=25)

    @field_validator("reason", "policy_reference", "policy_version")
    @classmethod
    def trim_nonblank_override_text(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("evidence_refs")
    @classmethod
    def unique_evidence_refs(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must be unique")
        return value

    @model_validator(mode="after")
    def validate_override_json_payloads(self):
        if not self.requested_change:
            raise ValueError("requested_change must be a non-empty JSON object")
        for name, value in (("requested_change", self.requested_change), ("impact_summary", self.impact_summary)):
            try:
                encoded = _json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must contain finite JSON values only") from exc
            if len(encoded.encode("utf-8")) > 8192:
                raise ValueError(f"{name} exceeds the 8 KiB limit")
        return self


class NamedAuthorityReviewIn(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    reason: str = Field(min_length=12, max_length=2000)
    authority_grant_ref: str = Field(min_length=3, max_length=160)
    authority_scope_ref: str = Field(min_length=3, max_length=160)
    valid_until: datetime | None = None

    @field_validator("reason", "authority_grant_ref", "authority_scope_ref")
    @classmethod
    def trim_nonblank_authority_text(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @model_validator(mode="after")
    def require_expiry_only_for_approval(self):
        if self.decision == "APPROVE":
            if self.valid_until is None or self.valid_until.tzinfo is None:
                raise ValueError("APPROVE requires a timezone-aware valid_until")
            if self.valid_until <= datetime.now(_timezone.utc):
                raise ValueError("valid_until must be in the future")
        elif self.valid_until is not None:
            raise ValueError("REJECT must not include valid_until")
        return self


class OverrideWithdrawIn(BaseModel):
    reason: str = Field(min_length=12, max_length=2000)

    @field_validator("reason")
    @classmethod
    def trim_nonblank_withdraw_reason(cls, value):
        normalized = value.strip()
        if len(normalized) < 12:
            raise ValueError("reason must contain at least twelve non-whitespace characters")
        return normalized

# V9.5.1: Camunda correlation and governed evidence lifecycle contracts.
from datetime import timezone as _workflow_timezone
import json as _workflow_json


class WorkflowBindingIn(BaseModel):
    process_definition_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    process_instance_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    business_key: str = Field(min_length=1, max_length=160)

    @field_validator("business_key")
    @classmethod
    def trim_business_key(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("business_key must not be blank")
        return value


class WorkflowEvidenceRequestIn(BaseModel):
    required_item_codes: list[str] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=12, max_length=2000)
    due_at: datetime
    based_on_version_id: UUID | None = None

    @field_validator("required_item_codes")
    @classmethod
    def normalize_required_items(cls, values):
        cleaned = [v.strip().upper() for v in values if isinstance(v, str) and v.strip()]
        if len(cleaned) != len(values) or len(cleaned) != len(set(cleaned)):
            raise ValueError("required_item_codes must be unique nonblank codes")
        if any(len(v) > 80 or not __import__("re").fullmatch(r"[A-Z][A-Z0-9_]{1,79}", v) for v in cleaned):
            raise ValueError("required_item_codes contains an invalid code")
        return cleaned

    @field_validator("reason")
    @classmethod
    def meaningful_evidence_reason(cls, value):
        value = value.strip()
        if len(value) < 12:
            raise ValueError("reason must contain at least twelve non-whitespace characters")
        return value

    @field_validator("due_at")
    @classmethod
    def require_future_aware_due_at(cls, value):
        if value.tzinfo is None or value <= datetime.now(_workflow_timezone.utc):
            raise ValueError("due_at must be timezone-aware and in the future")
        return value


class WorkflowResubmissionIn(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=12, max_length=2000)

    @field_validator("document_ids")
    @classmethod
    def unique_resubmission_documents(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("document_ids must be unique")
        return value

    @field_validator("reason")
    @classmethod
    def trim_resubmission_reason(cls, value):
        value = value.strip()
        if len(value) < 12:
            raise ValueError("reason must contain at least twelve non-whitespace characters")
        return value


class WorkflowReopenIn(BaseModel):
    reason_code: str = Field(pattern="^(EVIDENCE_UPDATED|POLICY_VERSION_CHANGED|PRODUCT_VERSION_CHANGED|EXTERNAL_REVIEW_REOPEN)$")
    reason: str = Field(min_length=12, max_length=2000)
    policy_reference: str | None = Field(default=None, max_length=160)
    policy_version: str | None = Field(default=None, max_length=80)
    product_code: str | None = Field(default=None, max_length=100)
    product_version: str | None = Field(default=None, max_length=80)

    @field_validator("reason")
    @classmethod
    def trim_workflow_reopen_reason(cls, value):
        value = value.strip()
        if len(value) < 12:
            raise ValueError("reason must contain at least twelve non-whitespace characters")
        return value

    @model_validator(mode="after")
    def require_changed_version_reference(self):
        if self.reason_code == "POLICY_VERSION_CHANGED" and not (self.policy_reference and self.policy_version):
            raise ValueError("policy reference and version are required")
        if self.reason_code == "PRODUCT_VERSION_CHANGED" and not (self.product_code and self.product_version):
            raise ValueError("product code and version are required")
        return self


class WorkflowInboxEventIn(BaseModel):
    external_event_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    process_instance_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    process_sequence: int = Field(ge=1, le=9_223_372_036_854_775_807)
    event_type: str = Field(pattern="^(PROCESS_STARTED|TASK_ASSIGNED|TASK_COMPLETED|EVIDENCE_EXPIRED|CASE_EXPIRED|PROCESS_COMPLETED|CAMUNDA_INCIDENT|G3_SHADOW_GATE_PASSED|G4_OPERATIONAL_GATE_PASSED)$")
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bound_event_payload(self):
        try:
            raw = _workflow_json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be finite JSON") from exc
        if len(raw.encode("utf-8")) > 8192:
            raise ValueError("payload exceeds 8 KiB")
        if self.event_type == "EVIDENCE_EXPIRED" and not self.payload.get("evidence_request_id"):
            raise ValueError("EVIDENCE_EXPIRED requires evidence_request_id")
        if self.event_type in {"G3_SHADOW_GATE_PASSED", "G4_OPERATIONAL_GATE_PASSED"} and not self.payload.get("external_gate_reference"):
            raise ValueError("release gate callback requires external_gate_reference")
        return self


class WorkflowOutboxClaimIn(BaseModel):
    worker_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    limit: int = Field(default=20, ge=1, le=100)
    lease_seconds: int = Field(default=300, ge=30, le=900)


class WorkflowOutboxAckIn(BaseModel):
    worker_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    decision: str = Field(pattern="^(DELIVERED|RETRY|DEAD_LETTER)$")
    error_code: str | None = Field(default=None, max_length=80, pattern=r"^[A-Z0-9_:-]+$")
    retry_after_seconds: int = Field(default=30, ge=1, le=3600)

    @model_validator(mode="after")
    def require_error_on_failure(self):
        if self.decision in {"RETRY", "DEAD_LETTER"} and not self.error_code:
            raise ValueError("error_code is required for RETRY or DEAD_LETTER")
        if self.decision == "DELIVERED" and self.error_code:
            raise ValueError("error_code must be omitted for DELIVERED")
        return self


class OverrideApplicationReceiptIn(BaseModel):
    external_application_reference: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9_.:/-]+$")
    applied_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    applied_version_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_reference: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=80)
    applied_at: datetime

    @field_validator("policy_reference", "policy_version", "external_application_reference")
    @classmethod
    def trim_application_receipt_values(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("application receipt references must not be blank")
        return value

    @field_validator("applied_at")
    @classmethod
    def require_aware_non_future_application_time(cls, value):
        if value.tzinfo is None or value > datetime.now(_workflow_timezone.utc) + timedelta(minutes=5):
            raise ValueError("applied_at must be timezone-aware and cannot be materially in the future")
        return value


class WorkflowReleaseGateIn(BaseModel):
    version_id: UUID
    gate_code: str = Field(pattern="^(G3_SHADOW|G4_OPERATIONAL)$")
    external_gate_reference: str = Field(min_length=3, max_length=160)
    product_code: str = Field(min_length=1, max_length=100)
    product_version: str = Field(min_length=1, max_length=80)
    policy_reference: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=80)

    @field_validator("external_gate_reference", "product_code", "product_version", "policy_reference", "policy_version")
    @classmethod
    def trim_release_gate_values(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("release gate fields must not be blank")
        return value


class WorkflowExportPackageIn(BaseModel):
    version_id: UUID
    product_code: str = Field(min_length=1, max_length=100)
    product_version: str = Field(min_length=1, max_length=80)
    product_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    policy_reference: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=80)
    policy_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    calculation_reference: str = Field(min_length=1, max_length=160)
    calculation_version: str = Field(min_length=1, max_length=80)
    calculation_sha256: str = Field(pattern="^[0-9a-f]{64}$")

    @field_validator("product_code", "product_version", "policy_reference", "policy_version",
                     "calculation_reference", "calculation_version")
    @classmethod
    def trim_export_refs(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("export reference fields must not be blank")
        return value

# V10.0 DATA-AI/Backend/Financial Engine contracts. These inputs are records or
# references only; DATA-AI never performs eligibility, DSR, stress or policy math.
from typing import Literal
from datetime import timezone
from uuid import UUID as _UUID


class ScopeConsentAttestationIn(BaseModel):
    scope_code: Literal["VN_UNSECURED_SALARIED_VND"]
    scope_status: Literal["IN_SCOPE", "OUT_OF_SCOPE"]
    consent_status: Literal["GRANTED", "REVOKED", "NOT_GRANTED"]
    consent_reference: str = Field(min_length=1, max_length=160)
    purpose_code: str = Field(min_length=1, max_length=80)
    notice_version: str = Field(min_length=1, max_length=60)
    backend_decision_reference: str = Field(min_length=1, max_length=160)
    attested_at: datetime

    @field_validator("attested_at")
    @classmethod
    def attested_at_must_be_timezone_aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attested_at must include a timezone")
        return value


class InputDeclarationRevisionIn(BaseModel):
    payload: dict[str, Any]
    evidence_document_ids: list[_UUID] = Field(default_factory=list, max_length=20)
    client_request_id: _UUID | None = None


class CaseInputReviewIn(BaseModel):
    target_type: Literal["DECLARATION_REVISION", "EXTRACTED_FIELD", "PAYROLL_EVIDENCE", "EARNING_MATCH", "TRANSACTION", "INCOME_LEDGER"]
    target_id: _UUID
    decision_code: Literal["CONFIRMED", "RETURNED", "UNABLE_TO_VERIFY", "REJECTED"]
    reason: str = Field(min_length=8, max_length=1000)
    evidence_document_ids: list[_UUID] = Field(default_factory=list, max_length=20)

    @field_validator("reason")
    @classmethod
    def review_reason_must_be_meaningful(cls, value):
        normalized = value.strip()
        if len(normalized) < 8:
            raise ValueError("reason must contain at least eight non-whitespace characters")
        return normalized


class ProposedScheduleReferenceIn(BaseModel):
    bundle_id: _UUID
    schedule_reference: str = Field(min_length=1, max_length=160)
    schedule_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    product_code: str = Field(min_length=1, max_length=80)
    product_version: str = Field(min_length=1, max_length=80)
    term_months: int = Field(ge=6, le=36)
    currency: Literal["VND"] = "VND"


class BusinessEngineReceiptIn(BaseModel):
    bundle_id: _UUID
    schedule_reference_id: _UUID | None = None
    input_bundle_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    calculation_reference: str = Field(min_length=1, max_length=160)
    calculation_version: str = Field(min_length=1, max_length=80)
    policy_reference: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=80)
    product_code: str = Field(min_length=1, max_length=80)
    product_version: str = Field(min_length=1, max_length=80)
    product_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    policy_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    result_status: Literal["COMPLETED", "HOLD", "FAILED"]
    scenario_references: dict[str, str] = Field(default_factory=dict)
    output_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def receipt_datetime_must_be_aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return value

    @model_validator(mode="after")
    def completed_receipt_requires_three_scenarios(self):
        if self.result_status == "COMPLETED":
            if self.schedule_reference_id is None:
                raise ValueError("COMPLETED receipt must identify the exact proposed schedule reference")
            required = {"BASELINE", "STRESS_1", "STRESS_2"}
            if set(self.scenario_references) != required:
                raise ValueError("COMPLETED receipt must contain exactly BASELINE, STRESS_1 and STRESS_2 references")
            if any(not str(self.scenario_references[key]).strip() for key in required):
                raise ValueError("scenario references must be non-empty")
        return self
