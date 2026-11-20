import uuid
from decimal import Decimal
from datetime import datetime, date
from sqlalchemy import String, Text, DateTime, Date, ForeignKey, Integer, Numeric, Boolean, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

class Case(Base):
    __tablename__ = "cases"
    id: Mapped[uuid.UUID] = uuid_pk()
    external_case_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    bank_id: Mapped[str] = mapped_column(String(100), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_profiles.id", ondelete="RESTRICT"), nullable=True, index=True)
    analysis_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    documents: Mapped[list["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="case", cascade="all, delete-orphan")

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    document_type: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    layout_code: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    evidence_status: Mapped[str] = mapped_column(String(30), default="RECEIVED")
    processing_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    case: Mapped["Case"] = relationship(back_populates="documents")
    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("case_id", "sha256", name="uq_document_case_hash"),)

class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(100), index=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    document: Mapped["Document"] = relationship(back_populates="fields")

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    source_row: Mapped[int] = mapped_column(Integer)
    transaction_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    amount_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    direction: Mapped[str] = mapped_column(String(10), default="UNKNOWN")
    category: Mapped[str] = mapped_column(String(40), default="unknown")
    classification_confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    is_income_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    case: Mapped["Case"] = relationship(back_populates="transactions")
    __table_args__ = (UniqueConstraint("case_id", "document_id", "source_row", name="uq_transaction_source_row"),)

class ProcessingResult(Base):
    __tablename__ = "processing_results"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(40), default="0.1.0")
    result_status: Mapped[str] = mapped_column(String(30))
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="data-ai-service")
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

Index("ix_transactions_case_date", Transaction.case_id, Transaction.transaction_date)

class ApplicantSubmission(Base):
    """Immutable snapshot of customer-entered form data; schema is versioned by Backend."""
    __tablename__ = "applicant_submissions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    applicant_ref: Mapped[str] = mapped_column(String(120), index=True)
    form_version: Mapped[str] = mapped_column(String(40), default="1")
    form_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    consent_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    submitted_by: Mapped[str] = mapped_column(String(120), default="backend")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("case_id", "applicant_ref", "form_version", name="uq_applicant_submission_version"),)

class ExportJob(Base):
    __tablename__ = "export_jobs"
    id: Mapped[uuid.UUID] = uuid_pk()
    bank_id: Mapped[str] = mapped_column(String(100), index=True)
    requested_by: Mapped[str] = mapped_column(String(120))
    export_scope: Mapped[str] = mapped_column(String(40), default="BOTH")
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    row_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    issue_code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    source_anchor: Mapped[dict] = mapped_column(JSONB, default=dict)
    issue_status: Mapped[str] = mapped_column(String(30), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class PayrollEvidence(Base):
    __tablename__ = "payroll_evidence"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    pay_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    evidence_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    source_anchor: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class IncomeLedgerMonth(Base):
    __tablename__ = "income_ledger_months"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    period_month: Mapped[date] = mapped_column(Date)
    observed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    accepted_amount: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    excluded_amount: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    month_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    exclusion_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class EarningMatchCandidate(Base):
    __tablename__ = "earning_match_candidates"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    payroll_evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_evidence.id", ondelete="CASCADE"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    similarity_score: Mapped[float] = mapped_column(Numeric(6,5))
    match_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    review_status: Mapped[str] = mapped_column(String(30), default="SUGGESTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


# Customer, staff, access-control and configurable-form domain. Authentication is owned by Backend/SSO.
class BankOrganization(Base):
    __tablename__ = "bank_organizations"
    id: Mapped[uuid.UUID] = uuid_pk()
    bank_code: Mapped[str] = mapped_column(String(80), unique=True)
    bank_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class BankBranch(Base):
    __tablename__ = "bank_branches"
    id: Mapped[uuid.UUID] = uuid_pk()
    bank_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_organizations.id", ondelete="RESTRICT"), index=True)
    branch_code: Mapped[str] = mapped_column(String(80))
    branch_name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("bank_id", "branch_code", name="uq_bank_branch_code"),)

class StaffUser(Base):
    __tablename__ = "staff_users"
    id: Mapped[uuid.UUID] = uuid_pk()
    bank_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_branches.id", ondelete="SET NULL"), nullable=True)
    employee_code: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    staff_type: Mapped[str] = mapped_column(String(30), default="BANK_STAFF")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    external_identity_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class AccessRole(Base):
    __tablename__ = "access_roles"
    id: Mapped[uuid.UUID] = uuid_pk()
    role_code: Mapped[str] = mapped_column(String(60), unique=True)
    role_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class StaffUserRole(Base):
    __tablename__ = "staff_user_roles"
    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("access_roles.id", ondelete="RESTRICT"), primary_key=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    id: Mapped[uuid.UUID] = uuid_pk()
    bank_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    customer_code: Mapped[str] = mapped_column(String(100), unique=True)
    external_identity_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nationality: Mapped[str] = mapped_column(String(80), default="Vietnamese")
    phone: Mapped[str] = mapped_column(String(30), index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    identity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    identity_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dependents_count: Mapped[int] = mapped_column(Integer, default=0)
    preferred_contact_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    customer_status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_profiles.id", ondelete="CASCADE"), index=True)
    address_type: Mapped[str] = mapped_column(String(30))
    country_code: Mapped[str] = mapped_column(String(2), default="VN")
    province_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    province_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ward_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    street_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerEmployment(Base):
    __tablename__ = "customer_employments"
    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_profiles.id", ondelete="CASCADE"), index=True)
    employment_type: Mapped[str] = mapped_column(String(40))
    employer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    employer_tax_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    work_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    work_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_income_declared: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    income_currency: Mapped[str] = mapped_column(String(3), default="VND")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class LoanApplication(Base):
    __tablename__ = "loan_applications"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_profiles.id", ondelete="RESTRICT"), index=True)
    product_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(18,2))
    requested_term_months: Mapped[int] = mapped_column(Integer)
    loan_purpose: Mapped[str] = mapped_column(String(500))
    preferred_disbursement_account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    application_status: Mapped[str] = mapped_column(String(40), default="SUBMITTED")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class FormDefinition(Base):
    __tablename__ = "form_definitions"
    id: Mapped[uuid.UUID] = uuid_pk()
    form_code: Mapped[str] = mapped_column(String(80), index=True)
    form_name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(40))
    audience: Mapped[str] = mapped_column(String(30), default="CUSTOMER")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    definition_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("form_code", "version", name="uq_form_definition_version"),)

class FormFieldDefinition(Base):
    __tablename__ = "form_field_definitions"
    id: Mapped[uuid.UUID] = uuid_pk()
    form_definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("form_definitions.id", ondelete="CASCADE"), index=True)
    field_key: Mapped[str] = mapped_column(String(100))
    field_label: Mapped[str] = mapped_column(String(200))
    data_type: Mapped[str] = mapped_column(String(30))
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    validation_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    options_json: Mapped[list] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("form_definition_id", "field_key", name="uq_form_field_key"),)

class ManagementAuditLog(Base):
    __tablename__ = "management_audit_logs"
    id: Mapped[uuid.UUID] = uuid_pk()
    bank_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    before_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class SourceInventory(Base):
    __tablename__ = "source_inventory"
    id: Mapped[uuid.UUID] = uuid_pk()
    source_code: Mapped[str] = mapped_column(String(80), unique=True)
    source_name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(40))
    approval_status: Mapped[str] = mapped_column(String(30), default="PENDING_APPROVAL")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class FieldMappingRegistry(Base):
    __tablename__ = "field_mapping_registry"
    id: Mapped[uuid.UUID] = uuid_pk()
    source_code: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(40))
    source_field: Mapped[str] = mapped_column(String(150))
    target_field: Mapped[str] = mapped_column(String(100))
    transform_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_status: Mapped[str] = mapped_column(String(30), default="PENDING_APPROVAL")
    __table_args__ = (UniqueConstraint("source_code", "schema_version", "source_field", "target_field", name="uq_source_mapping"),)

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(150), unique=True)
    pipeline_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)

class CustomerHouseholdProfile(Base):
    __tablename__ = "customer_household_profiles"
    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_profiles.id", ondelete="RESTRICT"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    household_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dependents_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    housing_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    residence_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    household_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    declaration_status: Mapped[str] = mapped_column(String(24), default="DECLARED")
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerExpenseDeclaration(Base):
    __tablename__ = "customer_expense_declarations"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    expense_category: Mapped[str] = mapped_column(String(40))
    amount_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), default="MONTHLY")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), default="CUSTOMER_DECLARED")
    review_status: Mapped[str] = mapped_column(String(24), default="PENDING_REVIEW")
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerLiabilityDeclaration(Base):
    __tablename__ = "customer_liability_declarations"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    liability_type: Mapped[str] = mapped_column(String(40))
    creditor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_ref_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    outstanding_balance_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    monthly_payment_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_overdue: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    overdue_amount_vnd: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), default="CUSTOMER_DECLARED")
    review_status: Mapped[str] = mapped_column(String(24), default="PENDING_REVIEW")
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerSalaryAccount(Base):
    __tablename__ = "customer_salary_accounts"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    bank_name: Mapped[str] = mapped_column(String(160))
    bank_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_number_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    statement_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    ownership_verification_status: Mapped[str] = mapped_column(String(24), default="UNVERIFIED")
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class CustomerDeclarationRevision(Base):
    __tablename__ = "customer_declaration_revisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    section_code: Mapped[str] = mapped_column(String(40))
    revision_no: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    submitted_by: Mapped[str] = mapped_column(String(120))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_declaration_revisions.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (UniqueConstraint("case_id", "section_code", "revision_no", name="uq_customer_declaration_revision"),)
