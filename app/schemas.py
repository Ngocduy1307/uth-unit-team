from datetime import datetime
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
    form_version: str = Field(default="1", min_length=1, max_length=40)
    form_data: dict[str, Any]
    consent_reference: str | None = Field(default=None, max_length=160)

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
    employment_type: str
    employer_name: str | None = None
    employer_tax_code: str | None = None
    job_title: str | None = None
    industry: str | None = None
    work_phone: str | None = None
    work_address: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    monthly_income_declared: Decimal | None = None
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
    dependents_count: int = 0
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
        if value < 0 or value > 30:
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
    form_version: str = "1.0"
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
        if not 1 <= value <= 360:
            raise ValueError("requested_term_months must be between 1 and 360")
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
