import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
from sqlalchemy import String, Text, DateTime, Date, ForeignKey, ForeignKeyConstraint, Integer, BigInteger, Numeric, Boolean, UniqueConstraint, Index, LargeBinary, JSON, CheckConstraint, text as sql_text
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
    bank_organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_profiles.id", ondelete="RESTRICT"), nullable=True, index=True)
    analysis_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    documents: Mapped[list["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    __table_args__ = (ForeignKeyConstraint(["customer_id", "bank_organization_id"], ["customer_profiles.id", "customer_profiles.bank_id"], name="fk_cases_customer_bank_scope"),)

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
    detected_mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    malware_scan_status: Mapped[str] = mapped_column(String(24), default="NOT_SCANNED")
    malware_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    malware_scan_engine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    storage_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_key_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    case: Mapped["Case"] = relationship(back_populates="documents")
    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("case_id", "sha256", name="uq_document_case_hash"),
        UniqueConstraint("id", "case_id", name="uq_documents_id_case"),
    )

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
    coordinate_space: Mapped[str | None] = mapped_column(String(24), nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_basis: Mapped[str | None] = mapped_column(String(48), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(24), default="NOT_ASSESSED")
    extraction_decision: Mapped[str] = mapped_column(String(16), default="ABSTAIN")
    abstain_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_rule_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
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
    __table_args__ = (
        UniqueConstraint("case_id", "document_id", "source_row", name="uq_transaction_source_row"),
        UniqueConstraint("id", "case_id", name="uq_transactions_id_case"),
    )

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
Index("ix_extracted_fields_decision_review", ExtractedField.document_id,
      ExtractedField.extraction_decision, ExtractedField.review_status)

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
    gross_amount_field_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=True)
    net_amount_field_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=True)
    payment_date_field_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=True)
    pay_period_start_field_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=True)
    pay_period_end_field_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extracted_fields.id", ondelete="RESTRICT"), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = uuid_pk()
    permission_code: Mapped[str] = mapped_column(String(100), unique=True)
    resource: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("access_roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class StaffRoleAssignmentHistory(Base):
    __tablename__ = "staff_role_assignment_history"
    id: Mapped[uuid.UUID] = uuid_pk()
    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff_users.id", ondelete="RESTRICT"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("access_roles.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # ASSIGNED / REVOKED
    changed_by_external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

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
    dependents_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    income_basis: Mapped[str | None] = mapped_column(String(8), nullable=True)  # NET or GROSS, customer-declared
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
    __table_args__ = (ForeignKeyConstraint(["case_id", "customer_id"], ["cases.id", "cases.customer_id"], name="fk_loan_app_case_customer_consistency"),)

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
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (ForeignKeyConstraint(["case_id", "customer_id"], ["cases.id", "cases.customer_id"], name="fk_household_case_customer_consistency"),)

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
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
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
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
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
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
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
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_channel: Mapped[str] = mapped_column(String(40), default="BACKEND")
    __table_args__ = (
        UniqueConstraint("case_id", "section_code", "revision_no", name="uq_customer_declaration_revision"),
        ForeignKeyConstraint(["case_id", "customer_id"], ["cases.id", "cases.customer_id"], name="fk_declaration_revision_case_customer"),
    )


class ConsentEvent(Base):
    __tablename__ = "consent_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    consent_reference: Mapped[str] = mapped_column(String(160))
    purpose_code: Mapped[str] = mapped_column(String(80))
    notice_version: Mapped[str] = mapped_column(String(60))
    consent_status: Mapped[str] = mapped_column(String(20))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    captured_by: Mapped[str] = mapped_column(String(160))
    capture_channel: Mapped[str] = mapped_column(String(40))
    evidence_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language_code: Mapped[str] = mapped_column(String(10), default="vi")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (ForeignKeyConstraint(["case_id", "customer_id"], ["cases.id", "cases.customer_id"], name="fk_consent_case_customer"),)


class DocumentSecurityEvent(Base):
    __tablename__ = "document_security_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    scan_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    engine_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scanned_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attestation_version: Mapped[str] = mapped_column(String(32), default="LEGACY_UNVERIFIED", nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    recorded_by: Mapped[str] = mapped_column(String(160))

# Composite unique indexes required as referenced keys by V8 tenant-consistency FKs.
Index("uq_customer_profiles_id_bank", CustomerProfile.id, CustomerProfile.bank_id, unique=True)
Index("uq_cases_id_customer", Case.id, Case.customer_id, unique=True)


class ServiceAssertionNonce(Base):
    """Persistent one-time nonce store for signed Backend service assertions."""
    __tablename__ = "service_assertion_nonces"
    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    key_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ApiIdempotencyRecord(Base):
    """Durable request/response ledger for opt-in mutation idempotency."""
    __tablename__ = "api_idempotency_records"
    id: Mapped[uuid.UUID] = uuid_pk()
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="IN_PROGRESS")
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[list | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    response_replayable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("scope_hash", "idempotency_key_hash", name="uq_api_idempotency_scope_key"),
        Index("ix_api_idempotency_expires_at", "expires_at"),
        Index("ix_api_idempotency_state_created", "state", "created_at"),
    )


class EvidenceManifestEntry(Base):
    """Append-only hash-chained receipt record for every uploaded evidence object."""
    __tablename__ = "evidence_manifest_entries"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    previous_entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hash_version: Mapped[str] = mapped_column(String(8), default="1")
    received_by: Mapped[str] = mapped_column(String(160))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("sequence_no > 0", name="ck_evidence_manifest_sequence_positive"),
        CheckConstraint("file_size > 0", name="ck_evidence_manifest_file_size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_manifest_sha256"),
        CheckConstraint("previous_entry_hash IS NULL OR previous_entry_hash ~ '^[0-9a-f]{64}$'",
                        name="ck_evidence_manifest_previous_hash"),
        CheckConstraint("entry_hash ~ '^[0-9a-f]{64}$'", name="ck_evidence_manifest_entry_hash"),
        UniqueConstraint("case_id", "sequence_no", name="uq_evidence_manifest_case_sequence"),
        UniqueConstraint("document_id", name="uq_evidence_manifest_document"),
        ForeignKeyConstraint(["document_id", "case_id"], ["documents.id", "documents.case_id"],
                             name="fk_manifest_document_case", ondelete="RESTRICT"),
        Index("ix_evidence_manifest_case_received", "case_id", "received_at"),
    )


class TransactionDuplicateCandidate(Base):
    """Exact-fingerprint pair for Maker review; never silently drops a transaction."""
    __tablename__ = "transaction_duplicate_candidates"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"))
    left_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    right_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64))
    candidate_key: Mapped[str] = mapped_column(String(64), unique=True)
    match_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    review_status: Mapped[str] = mapped_column(String(24), default="PENDING_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("left_transaction_id < right_transaction_id", name="ck_duplicate_candidate_ordered_pair"),
        CheckConstraint("fingerprint_sha256 ~ '^[0-9a-f]{64}$'", name="ck_duplicate_candidate_fingerprint"),
        CheckConstraint("candidate_key ~ '^[0-9a-f]{64}$'", name="ck_duplicate_candidate_key"),
        CheckConstraint("review_status IN ('PENDING_REVIEW','REVIEWED')", name="ck_duplicate_candidate_review_status"),
        UniqueConstraint("left_transaction_id", "right_transaction_id", name="uq_duplicate_candidate_pair"),
        UniqueConstraint("id", "case_id", name="uq_duplicate_candidate_id_case"),
        Index("ix_duplicate_candidate_case", "case_id", "created_at"),
        Index("ix_duplicate_candidate_fingerprint", "fingerprint_sha256"),
        ForeignKeyConstraint(["left_transaction_id", "case_id"], ["transactions.id", "transactions.case_id"],
                             name="fk_duplicate_candidate_left_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["right_transaction_id", "case_id"], ["transactions.id", "transactions.case_id"],
                             name="fk_duplicate_candidate_right_case", ondelete="RESTRICT"),
    )


class EvidenceReconciliationRun(Base):
    """Immutable snapshot of a PDF statement vs CSV movement arithmetic check."""
    __tablename__ = "evidence_reconciliation_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"))
    pdf_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    csv_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    csv_sha256: Mapped[str] = mapped_column(String(64))
    reconciliation_version: Mapped[str] = mapped_column(String(40))
    result_status: Mapped[str] = mapped_column(String(32))
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("pdf_document_id <> csv_document_id", name="ck_reconciliation_distinct_documents"),
        CheckConstraint("pdf_sha256 ~ '^[0-9a-f]{64}$'", name="ck_reconciliation_pdf_sha256"),
        CheckConstraint("csv_sha256 ~ '^[0-9a-f]{64}$'", name="ck_reconciliation_csv_sha256"),
        CheckConstraint("result_status IN ('INCOMPLETE','ABSTAINED','BALANCE_MATCH_CANDIDATE','BALANCE_VARIANCE_CANDIDATE')",
                        name="ck_reconciliation_result_status"),
        ForeignKeyConstraint(["pdf_document_id", "case_id"], ["documents.id", "documents.case_id"],
                             name="fk_reconciliation_pdf_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["csv_document_id", "case_id"], ["documents.id", "documents.case_id"],
                             name="fk_reconciliation_csv_case", ondelete="RESTRICT"),
        Index("ix_reconciliation_case_created", "case_id", "created_at"),
        UniqueConstraint("id", "case_id", name="uq_reconciliation_run_id_case"),
    )


class EvidenceReviewDecision(Base):
    """Append-only human review record; workflow task completion remains Camunda-owned."""
    __tablename__ = "evidence_review_decisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reconciliation_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    duplicate_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_code: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSONB, default=list)
    reviewed_by: Mapped[str] = mapped_column(String(160))
    reviewer_role: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("target_type IN ('RECONCILIATION_RUN','TRANSACTION_DUPLICATE')",
                        name="ck_evidence_review_target_type"),
        CheckConstraint("length(trim(reason)) >= 8", name="ck_evidence_review_reason"),
        CheckConstraint("(target_type = 'RECONCILIATION_RUN' AND reconciliation_run_id IS NOT NULL AND duplicate_candidate_id IS NULL AND target_id = reconciliation_run_id) OR (target_type = 'TRANSACTION_DUPLICATE' AND duplicate_candidate_id IS NOT NULL AND reconciliation_run_id IS NULL AND target_id = duplicate_candidate_id)",
                        name="ck_evidence_review_target_link"),
        CheckConstraint("(target_type = 'RECONCILIATION_RUN' AND decision_code IN ('CONFIRMED_MATCH','CONFIRMED_VARIANCE','REJECTED','NEEDS_MORE_EVIDENCE')) OR (target_type = 'TRANSACTION_DUPLICATE' AND decision_code IN ('CONFIRMED_DUPLICATE','NOT_DUPLICATE','NEEDS_MORE_EVIDENCE'))",
                        name="ck_evidence_review_decision_code"),
        ForeignKeyConstraint(["reconciliation_run_id", "case_id"], ["evidence_reconciliation_runs.id", "evidence_reconciliation_runs.case_id"],
                             name="fk_evidence_review_reconciliation_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["duplicate_candidate_id", "case_id"], ["transaction_duplicate_candidates.id", "transaction_duplicate_candidates.case_id"],
                             name="fk_evidence_review_duplicate_case", ondelete="RESTRICT"),
        Index("ix_evidence_review_target_created", "target_type", "target_id", "created_at"),
        Index("ix_evidence_review_case_created", "case_id", "created_at"),
    )


class CaseAnalysisVersion(Base):
    """Immutable snapshot of DATA-AI evidence inputs for a Maker/Checker cycle.

    This is not a credit-decision version and does not contain calculated DSR,
    policy outcomes or an approval recommendation.
    """
    __tablename__ = "case_analysis_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    based_on_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    snapshot_schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="V9.4.1.1")
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    readiness: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(40), nullable=False, default="MAKER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("version_no > 0", name="ck_case_analysis_version_positive"),
        CheckConstraint("created_by_role = 'MAKER'", name="ck_case_analysis_version_creator_role"),
        CheckConstraint("length(trim(created_by)) > 0", name="ck_case_analysis_version_creator_nonblank"),
        CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_analysis_version_sha256"),
        UniqueConstraint("case_id", "version_no", name="uq_case_analysis_version_case_no"),
        UniqueConstraint("id", "case_id", name="uq_case_analysis_version_id_case"),
        ForeignKeyConstraint(["based_on_version_id", "case_id"],
                             ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_analysis_version_parent_case", ondelete="RESTRICT"),
        Index("ix_case_analysis_version_case_created", "case_id", sql_text("created_at DESC")),
    )


class CaseGovernanceEvent(Base):
    """Append-only technical governance events; Camunda remains workflow owner."""
    __tablename__ = "case_governance_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("event_type IN ('FROZEN','CHECKER_CONFIRMED','RETURNED_TO_MAKER','VERSION_SUPERSEDED')",
                        name="ck_case_governance_event_type"),
        CheckConstraint("actor_role IN ('MAKER','CHECKER')", name="ck_case_governance_actor_role"),
        CheckConstraint("length(trim(actor_id)) > 0", name="ck_case_governance_actor_nonblank"),
        CheckConstraint("length(trim(reason)) >= 8", name="ck_case_governance_reason"),
        CheckConstraint("(event_type IN ('FROZEN','VERSION_SUPERSEDED') AND actor_role = 'MAKER') OR "
                        "(event_type IN ('CHECKER_CONFIRMED','RETURNED_TO_MAKER') AND actor_role = 'CHECKER')",
                        name="ck_case_governance_event_role"),
        ForeignKeyConstraint(["version_id", "case_id"],
                             ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_governance_event_version_case", ondelete="RESTRICT"),
        Index("ix_case_governance_case_created", "case_id", sql_text("created_at DESC")),
        Index("ix_case_governance_version_created", "version_id", sql_text("created_at DESC")),
    )

# Partial uniqueness in PostgreSQL guarantees one freeze and one terminal
# Checker decision per immutable snapshot. Backend/Camunda task state remains external.
Index("uq_case_governance_frozen_per_version", CaseGovernanceEvent.version_id, unique=True,
      postgresql_where=(CaseGovernanceEvent.event_type == "FROZEN"))
Index("uq_case_governance_checker_decision_per_version", CaseGovernanceEvent.version_id, unique=True,
      postgresql_where=(CaseGovernanceEvent.event_type.in_(["CHECKER_CONFIRMED", "RETURNED_TO_MAKER"])))
Index("uq_case_governance_superseded_per_version", CaseGovernanceEvent.version_id, unique=True,
      postgresql_where=(CaseGovernanceEvent.event_type == "VERSION_SUPERSEDED"))


class CaseAuditEntry(Base):
    """Append-only, per-case hash-chained audit ledger for governance actions."""
    __tablename__ = "case_audit_entries"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    action_code: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    previous_entry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("sequence_no > 0", name="ck_case_audit_sequence_positive"),
        CheckConstraint("length(trim(actor_id)) > 0", name="ck_case_audit_actor_nonblank"),
        CheckConstraint("actor_role IN ('MAKER','CHECKER','NAMED_AUTHORITY','BANK_POLICY_OWNER','BUSINESS_ENGINE','LEGACY')",
                        name="ck_case_audit_actor_role"),
        CheckConstraint("action_code ~ '^[A-Z][A-Z0-9_]{2,63}$'", name="ck_case_audit_action_code"),
        CheckConstraint("length(trim(entity_type)) > 0 AND length(trim(entity_id)) > 0",
                        name="ck_case_audit_entity_reference"),
        CheckConstraint("previous_entry_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_audit_previous_hash"),
        CheckConstraint("entry_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_audit_entry_hash"),
        CheckConstraint("before_sha256 IS NULL OR before_sha256 ~ '^[0-9a-f]{64}$'",
                        name="ck_case_audit_before_hash"),
        CheckConstraint("after_sha256 IS NULL OR after_sha256 ~ '^[0-9a-f]{64}$'",
                        name="ck_case_audit_after_hash"),
        UniqueConstraint("case_id", "sequence_no", name="uq_case_audit_case_sequence"),
        ForeignKeyConstraint(["version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_audit_version_case", ondelete="RESTRICT"),
        Index("ix_case_audit_case_created", "case_id", "created_at"),
        Index("ix_case_audit_case_action", "case_id", "action_code", "sequence_no"),
    )


class CaseOverrideRequest(Base):
    """Immutable Maker proposal; approval never executes or mutates business policy."""
    __tablename__ = "case_override_requests"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    exception_code: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_change: Mapped[dict] = mapped_column(JSONB, nullable=False)
    impact_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    version_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("request_kind IN ('OVERRIDE','POLICY_EXCEPTION')", name="ck_case_override_request_kind"),
        CheckConstraint("exception_code ~ '^[A-Z][A-Z0-9_]{1,79}$'", name="ck_case_override_exception_code"),
        CheckConstraint("length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0",
                        name="ck_case_override_policy_reference"),
        CheckConstraint("length(trim(requested_by)) > 0 AND length(trim(reason)) >= 12",
                        name="ck_case_override_request_reason"),
        CheckConstraint("jsonb_typeof(requested_change) = 'object' AND requested_change <> '{}'::jsonb",
                        name="ck_case_override_change_object"),
        CheckConstraint("jsonb_typeof(impact_summary) = 'object'", name="ck_case_override_impact_object"),
        CheckConstraint("CASE WHEN jsonb_typeof(evidence_refs) = 'array' THEN jsonb_array_length(evidence_refs) > 0 ELSE FALSE END",
                        name="ck_case_override_evidence_refs"),
        CheckConstraint("version_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_override_version_hash"),
        CheckConstraint("proposal_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_override_proposal_hash"),
        UniqueConstraint("id", "case_id", name="uq_case_override_request_id_case"),
        UniqueConstraint("case_id", "version_id", "proposal_sha256", name="uq_case_override_version_proposal"),
        ForeignKeyConstraint(["version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_override_request_version_case", ondelete="RESTRICT"),
        Index("ix_case_override_case_created", "case_id", "created_at"),
        Index("ix_case_override_version_created", "version_id", "created_at"),
    )


class CaseOverrideEvent(Base):
    """Append-only request/authority decision events for one override proposal."""
    __tablename__ = "case_override_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authority_grant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    authority_scope_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("event_type IN ('REQUESTED','APPROVED','REJECTED','WITHDRAWN')",
                        name="ck_case_override_event_type"),
        CheckConstraint("(event_type IN ('REQUESTED','WITHDRAWN') AND actor_role = 'MAKER') OR "
                        "(event_type IN ('APPROVED','REJECTED') AND actor_role = 'NAMED_AUTHORITY')",
                        name="ck_case_override_event_role"),
        CheckConstraint("length(trim(actor_id)) > 0 AND length(trim(reason)) >= 12",
                        name="ck_case_override_event_reason"),
        CheckConstraint("proposal_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_override_event_hash"),
        CheckConstraint("event_type NOT IN ('APPROVED','REJECTED') OR "
                        "(authority_grant_ref IS NOT NULL AND length(trim(authority_grant_ref)) > 0 AND "
                        "authority_scope_ref IS NOT NULL AND length(trim(authority_scope_ref)) > 0)",
                        name="ck_case_override_authority_refs"),
        CheckConstraint("(event_type = 'APPROVED' AND valid_until IS NOT NULL) OR "
                        "(event_type <> 'APPROVED' AND valid_until IS NULL)",
                        name="ck_case_override_valid_until"),
        ForeignKeyConstraint(["request_id", "case_id"], ["case_override_requests.id", "case_override_requests.case_id"],
                             name="fk_case_override_event_request_case", ondelete="RESTRICT"),
        Index("ix_case_override_event_request_created", "request_id", "created_at"),
    )

Index("uq_case_override_requested_per_request", CaseOverrideEvent.request_id, unique=True,
      postgresql_where=(CaseOverrideEvent.event_type == "REQUESTED"))
Index("uq_case_override_terminal_per_request", CaseOverrideEvent.request_id, unique=True,
      postgresql_where=(CaseOverrideEvent.event_type.in_(["APPROVED", "REJECTED", "WITHDRAWN"])))

# V9.5.1: Camunda workflow correlation, outbox/inbox, evidence lifecycle,
# governed reopen, release-gate records and hashed analysis export packages.
class CaseWorkflowBinding(Base):
    __tablename__ = "case_workflow_bindings"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(32), nullable=False, default="CAMUNDA_8")
    process_definition_key: Mapped[str] = mapped_column(String(160), nullable=False)
    process_instance_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    business_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("engine_name = 'CAMUNDA_8'", name="ck_workflow_binding_engine"),
        CheckConstraint("status IN ('ACTIVE','COMPLETED','CANCELLED')", name="ck_workflow_binding_status"),
        CheckConstraint("length(trim(process_definition_key)) > 0 AND length(trim(process_instance_id)) > 0 AND length(trim(business_key)) > 0",
                        name="ck_workflow_binding_identifiers"),
        UniqueConstraint("id", "case_id", name="uq_workflow_binding_id_case"),
        Index("ix_workflow_binding_case_created", "case_id", "created_at"),
    )

Index("uq_workflow_binding_active_case", CaseWorkflowBinding.case_id, unique=True,
      postgresql_where=(CaseWorkflowBinding.status == "ACTIVE"))


class WorkflowOutboxEvent(Base):
    __tablename__ = "workflow_outbox_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("event_type ~ '^[A-Z][A-Z0-9_]{2,63}$'", name="ck_workflow_outbox_event_type"),
        CheckConstraint("status IN ('PENDING','IN_FLIGHT','DELIVERED','DEAD_LETTER')", name="ck_workflow_outbox_status"),
        CheckConstraint("attempts BETWEEN 0 AND 8", name="ck_workflow_outbox_attempts"),
        CheckConstraint("(status = 'IN_FLIGHT' AND claimed_by IS NOT NULL AND locked_until IS NOT NULL) OR "
                        "(status IN ('PENDING','DELIVERED','DEAD_LETTER') AND claimed_by IS NULL AND locked_until IS NULL)",
                        name="ck_workflow_outbox_lease_state"),
        CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_workflow_outbox_payload_hash"),
        CheckConstraint("length(trim(idempotency_key)) >= 8", name="ck_workflow_outbox_idem_key"),
        CheckConstraint("(status = 'DELIVERED' AND delivered_at IS NOT NULL) OR status <> 'DELIVERED'",
                        name="ck_workflow_outbox_delivered_at"),
        UniqueConstraint("case_id", "idempotency_key", name="uq_workflow_outbox_case_idem"),
        ForeignKeyConstraint(["binding_id", "case_id"], ["case_workflow_bindings.id", "case_workflow_bindings.case_id"],
                             name="fk_workflow_outbox_binding_case", ondelete="RESTRICT"),
        Index("ix_workflow_outbox_claim", "status", "available_at", "created_at"),
        Index("ix_workflow_outbox_case_created", "case_id", "created_at"),
    )


class WorkflowInboxEvent(Base):
    __tablename__ = "workflow_inbox_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    process_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("process_sequence > 0", name="ck_workflow_inbox_sequence"),
        CheckConstraint("event_type ~ '^[A-Z][A-Z0-9_]{2,63}$'", name="ck_workflow_inbox_event_type"),
        CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_workflow_inbox_payload_hash"),
        UniqueConstraint("binding_id", "process_sequence", name="uq_workflow_inbox_binding_sequence"),
        ForeignKeyConstraint(["binding_id", "case_id"], ["case_workflow_bindings.id", "case_workflow_bindings.case_id"],
                             name="fk_workflow_inbox_binding_case", ondelete="RESTRICT"),
        Index("ix_workflow_inbox_case_received", "case_id", "received_at"),
    )


class CaseEvidenceRequest(Base):
    __tablename__ = "case_evidence_requests"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(100), nullable=False)
    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_no: Mapped[int] = mapped_column(Integer, nullable=False)
    required_item_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False)
    based_on_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="AWAITING_EVIDENCE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("request_no > 0", name="ck_case_evidence_request_no"),
        CheckConstraint("jsonb_typeof(required_item_codes) = 'array' AND jsonb_array_length(required_item_codes) > 0",
                        name="ck_case_evidence_required_items"),
        CheckConstraint("length(trim(reason)) >= 12 AND length(trim(requested_by)) > 0",
                        name="ck_case_evidence_request_reason"),
        CheckConstraint("status IN ('AWAITING_EVIDENCE','RECEIVED','EXPIRED','CANCELLED')",
                        name="ck_case_evidence_request_status"),
        CheckConstraint("(status = 'AWAITING_EVIDENCE' AND resolved_at IS NULL) OR "
                        "(status IN ('RECEIVED','EXPIRED','CANCELLED') AND resolved_at IS NOT NULL)",
                        name="ck_case_evidence_request_resolution"),
        UniqueConstraint("case_id", "request_no", name="uq_case_evidence_request_no"),
        UniqueConstraint("id", "case_id", name="uq_case_evidence_request_id_case"),
        ForeignKeyConstraint(["binding_id", "case_id"], ["case_workflow_bindings.id", "case_workflow_bindings.case_id"],
                             name="fk_case_evidence_request_binding_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["based_on_version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_evidence_request_version_case", ondelete="RESTRICT"),
        Index("ix_case_evidence_request_case_status", "case_id", "status", "created_at"),
    )


class CaseResubmission(Base):
    __tablename__ = "case_resubmissions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    evidence_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    based_on_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    received_document_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    impact_list: Mapped[dict] = mapped_column(JSONB, nullable=False)
    impact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_new_version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("jsonb_typeof(received_document_ids) = 'array' AND jsonb_array_length(received_document_ids) > 0",
                        name="ck_case_resubmission_documents"),
        CheckConstraint("jsonb_typeof(impact_list) = 'object'", name="ck_case_resubmission_impact_object"),
        CheckConstraint("impact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_resubmission_impact_hash"),
        CheckConstraint("requested_new_version_no > 0 AND length(trim(created_by)) > 0",
                        name="ck_case_resubmission_next_version"),
        UniqueConstraint("evidence_request_id", name="uq_case_resubmission_request"),
        ForeignKeyConstraint(["evidence_request_id", "case_id"], ["case_evidence_requests.id", "case_evidence_requests.case_id"],
                             name="fk_case_resubmission_request_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["based_on_version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_resubmission_version_case", ondelete="RESTRICT"),
        Index("ix_case_resubmission_case_created", "case_id", "created_at"),
    )


class CaseWorkflowReopen(Base):
    __tablename__ = "case_workflow_reopens"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    based_on_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    new_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("reason_code IN ('EVIDENCE_UPDATED','POLICY_VERSION_CHANGED','PRODUCT_VERSION_CHANGED','EXTERNAL_REVIEW_REOPEN')",
                        name="ck_case_workflow_reopen_reason_code"),
        CheckConstraint("status IN ('OPEN','CONSUMED','CANCELLED')", name="ck_case_workflow_reopen_status"),
        CheckConstraint("(status = 'OPEN' AND new_version_id IS NULL AND consumed_at IS NULL) OR "
                        "(status = 'CONSUMED' AND new_version_id IS NOT NULL AND consumed_at IS NOT NULL) OR "
                        "(status = 'CANCELLED' AND new_version_id IS NULL AND consumed_at IS NULL)",
                        name="ck_case_workflow_reopen_completion"),
        CheckConstraint("length(trim(reason)) >= 12 AND length(trim(requested_by)) > 0",
                        name="ck_case_workflow_reopen_reason"),
        CheckConstraint("(reason_code <> 'POLICY_VERSION_CHANGED' OR (policy_reference IS NOT NULL AND policy_version IS NOT NULL)) AND "
                        "(reason_code <> 'PRODUCT_VERSION_CHANGED' OR (product_code IS NOT NULL AND product_version IS NOT NULL))",
                        name="ck_case_workflow_reopen_external_version"),
        ForeignKeyConstraint(["based_on_version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_workflow_reopen_base_version_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["new_version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_workflow_reopen_new_version_case", ondelete="RESTRICT"),
        Index("ix_case_workflow_reopen_case_created", "case_id", "created_at"),
    )

Index("uq_case_workflow_reopen_open_case", CaseWorkflowReopen.case_id, unique=True,
      postgresql_where=(CaseWorkflowReopen.status == "OPEN"))


class CaseOverrideApplicationReceipt(Base):
    """Append-only receipt from the authoritative Business Engine; DATA-AI does not apply the override."""
    __tablename__ = "case_override_application_receipts"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_application_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    applied_proposal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_version_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    applied_by: Mapped[str] = mapped_column(String(160), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("applied_proposal_sha256 ~ '^[0-9a-f]{64}$' AND applied_version_sha256 ~ '^[0-9a-f]{64}$'",
                        name="ck_override_application_receipt_hashes"),
        CheckConstraint("length(trim(external_application_reference)) > 0 AND length(trim(applied_by)) > 0",
                        name="ck_override_application_receipt_actor_ref"),
        CheckConstraint("length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0",
                        name="ck_override_application_receipt_policy"),
        UniqueConstraint("request_id", name="uq_override_application_receipt_request"),
        ForeignKeyConstraint(["request_id", "case_id"], ["case_override_requests.id", "case_override_requests.case_id"],
                             name="fk_override_application_receipt_request_case", ondelete="RESTRICT"),
        Index("ix_override_application_receipt_case_received", "case_id", "received_at"),
    )


class CaseWorkflowReleaseGate(Base):
    __tablename__ = "case_workflow_release_gates"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    external_gate_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    product_code: Mapped[str] = mapped_column(String(100), nullable=False)
    product_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("gate_code IN ('G3_SHADOW','G4_OPERATIONAL')", name="ck_case_workflow_release_gate_code"),
        CheckConstraint("length(trim(actor_id)) > 0 AND length(trim(external_gate_reference)) > 0",
                        name="ck_case_workflow_release_gate_actor_ref"),
        CheckConstraint("length(trim(product_code)) > 0 AND length(trim(product_version)) > 0 AND "
                        "length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0",
                        name="ck_case_workflow_release_gate_versions"),
        CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_workflow_release_gate_hash"),
        CheckConstraint("(gate_code = 'G3_SHADOW' AND actor_role IN ('BANK_POLICY_OWNER','RELEASE_AUTHORITY')) OR "
                        "(gate_code = 'G4_OPERATIONAL' AND actor_role = 'RELEASE_AUTHORITY')",
                        name="ck_case_workflow_release_actor_role"),
        UniqueConstraint("case_id", "version_id", "gate_code", name="uq_case_workflow_release_gate_version"),
        ForeignKeyConstraint(["version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_workflow_release_gate_version_case", ondelete="RESTRICT"),
        Index("ix_case_workflow_release_case_created", "case_id", "created_at"),
    )


class CaseWorkflowExportPackage(Base):
    __tablename__ = "case_workflow_export_packages"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    package_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="DATA_AI_EVIDENCE_PACKAGE")
    package_path: Mapped[str] = mapped_column(Text, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("package_kind = 'DATA_AI_EVIDENCE_PACKAGE'", name="ck_case_workflow_export_kind"),
        CheckConstraint("package_sha256 ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$'",
                        name="ck_case_workflow_export_hashes"),
        CheckConstraint("length(trim(package_path)) > 0 AND length(trim(requested_by)) > 0",
                        name="ck_case_workflow_export_path_actor"),
        ForeignKeyConstraint(["version_id", "case_id"], ["case_analysis_versions.id", "case_analysis_versions.case_id"],
                             name="fk_case_workflow_export_version_case", ondelete="RESTRICT"),
        Index("ix_case_workflow_export_case_created", "case_id", "created_at"),
    )

# V10.0 DATA-AI handoff records. These are evidence/contract records only;
# credit calculations and legal consent decisions remain external authorities.
class CaseScopeConsentAttestation(Base):
    __tablename__ = "case_scope_consent_attestations"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_code: Mapped[str] = mapped_column(String(80), nullable=False)
    scope_status: Mapped[str] = mapped_column(String(20), nullable=False)
    consent_status: Mapped[str] = mapped_column(String(20), nullable=False)
    consent_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose_code: Mapped[str] = mapped_column(String(80), nullable=False)
    notice_version: Mapped[str] = mapped_column(String(60), nullable=False)
    backend_decision_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    attestation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attested_by: Mapped[str] = mapped_column(String(160), nullable=False)
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("scope_status IN ('IN_SCOPE','OUT_OF_SCOPE')", name="ck_scope_attestation_scope_status"),
        CheckConstraint("consent_status IN ('GRANTED','REVOKED','NOT_GRANTED')", name="ck_scope_attestation_consent_status"),
        CheckConstraint("scope_code = 'VN_UNSECURED_SALARIED_VND'", name="ck_scope_attestation_product_scope"),
        CheckConstraint("attestation_sha256 ~ '^[0-9a-f]{64}$'", name="ck_scope_attestation_hash"),
        CheckConstraint("length(trim(consent_reference)) > 0 AND length(trim(purpose_code)) > 0 AND length(trim(notice_version)) > 0 AND length(trim(backend_decision_reference)) > 0 AND length(trim(attested_by)) > 0", name="ck_scope_attestation_refs"),
        UniqueConstraint("case_id", "backend_decision_reference", name="uq_case_scope_backend_decision"),
        Index("ix_scope_attestation_case_latest", "case_id", "attested_at", "id"),
    )


class CaseInputDeclarationRevision(Base):
    __tablename__ = "case_input_declaration_revisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    section_code: Mapped[str] = mapped_column(String(32), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(160), nullable=False)
    source_channel: Mapped[str] = mapped_column(String(32), nullable=False, default="BACKEND")
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    supersedes_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("section_code IN ('HOUSEHOLD','EMPLOYMENT','EXPENSES','LIABILITIES','SALARY_ACCOUNTS')", name="ck_case_input_declaration_section"),
        CheckConstraint("revision_no > 0", name="ck_case_input_declaration_revision_no"),
        CheckConstraint("jsonb_typeof(payload) = 'object' AND payload <> '{}'::jsonb", name="ck_case_input_declaration_payload"),
        CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_input_declaration_hash"),
        CheckConstraint("length(trim(submitted_by)) > 0", name="ck_case_input_declaration_actor"),
        UniqueConstraint("case_id", "section_code", "revision_no", name="uq_case_input_declaration_revision"),
        UniqueConstraint("id", "case_id", name="uq_case_input_declaration_id_case"),
        ForeignKeyConstraint(["supersedes_revision_id", "case_id"], ["case_input_declaration_revisions.id", "case_input_declaration_revisions.case_id"], name="fk_case_input_declaration_supersedes_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["case_id", "customer_id"], ["cases.id", "cases.customer_id"], name="fk_case_input_declaration_case_customer", ondelete="RESTRICT"),
        Index("ix_case_input_declaration_latest", "case_id", "section_code", "revision_no"),
        Index("uq_case_input_declaration_client_request", "case_id", "client_request_id", unique=True,
              postgresql_where=sql_text("client_request_id IS NOT NULL")),
    )


class CaseInputDeclarationEvidenceLink(Base):
    __tablename__ = "case_input_declaration_evidence_links"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    declaration_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    link_purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="SUPPORTING_EVIDENCE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("document_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_input_declaration_evidence_hash"),
        UniqueConstraint("declaration_revision_id", "document_id", name="uq_case_input_declaration_evidence"),
        ForeignKeyConstraint(["declaration_revision_id", "case_id"], ["case_input_declaration_revisions.id", "case_input_declaration_revisions.case_id"], name="fk_case_input_decl_evidence_revision_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["document_id", "case_id"], ["documents.id", "documents.case_id"], name="fk_case_input_decl_evidence_document_case", ondelete="RESTRICT"),
    )


class CaseInputReviewDecision(Base):
    __tablename__ = "case_input_review_decisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    declaration_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reviewed_by: Mapped[str] = mapped_column(String(160), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(24), nullable=False, default="MAKER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("target_type IN ('DECLARATION_REVISION','EXTRACTED_FIELD','PAYROLL_EVIDENCE','EARNING_MATCH','TRANSACTION','INCOME_LEDGER')", name="ck_case_input_review_target"),
        CheckConstraint("decision_code IN ('CONFIRMED','RETURNED','UNABLE_TO_VERIFY','REJECTED')", name="ck_case_input_review_decision"),
        CheckConstraint("length(trim(reason)) >= 8 AND length(trim(reviewed_by)) > 0", name="ck_case_input_review_reason_actor"),
        CheckConstraint("reviewer_role = 'MAKER'", name="ck_case_input_review_role"),
        CheckConstraint("jsonb_typeof(evidence_refs) = 'array'", name="ck_case_input_review_evidence_array"),
        ForeignKeyConstraint(["declaration_revision_id", "case_id"], ["case_input_declaration_revisions.id", "case_input_declaration_revisions.case_id"], name="fk_case_input_review_declaration_case", ondelete="RESTRICT"),
        Index("ix_case_input_review_target_latest", "case_id", "target_type", "target_id", "created_at"),
    )


class CaseFinancialInputBundle(Base):
    __tablename__ = "case_financial_input_bundles"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bundle_no: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_status: Mapped[str] = mapped_column(String(32), nullable=False)
    readiness: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bundle_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("bundle_no > 0", name="ck_financial_input_bundle_no"),
        CheckConstraint("readiness_status IN ('READY_FOR_BUSINESS_ENGINE','BLOCKED','INSUFFICIENT_EVIDENCE','NEEDS_MAKER_REVIEW')", name="ck_financial_input_bundle_readiness"),
        CheckConstraint("jsonb_typeof(readiness) = 'object' AND jsonb_typeof(bundle_data) = 'object'", name="ck_financial_input_bundle_objects"),
        CheckConstraint("bundle_sha256 ~ '^[0-9a-f]{64}$'", name="ck_financial_input_bundle_hash"),
        UniqueConstraint("case_id", "bundle_no", name="uq_financial_input_bundle_no"),
        UniqueConstraint("id", "case_id", name="uq_financial_input_bundle_id_case"),
        Index("ix_financial_input_bundle_case_created", "case_id", "created_at"),
    )


class CaseProposedScheduleReference(Base):
    __tablename__ = "case_proposed_schedule_references"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bundle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    schedule_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    product_code: Mapped[str] = mapped_column(String(80), nullable=False)
    product_version: Mapped[str] = mapped_column(String(80), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="VND")
    provided_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("schedule_sha256 ~ '^[0-9a-f]{64}$'", name="ck_proposed_schedule_hash"),
        CheckConstraint("term_months BETWEEN 6 AND 36", name="ck_proposed_schedule_term"),
        CheckConstraint("currency = 'VND'", name="ck_proposed_schedule_currency"),
        CheckConstraint("length(trim(product_code)) > 0 AND length(trim(product_version)) > 0 AND length(trim(provided_by)) > 0", name="ck_proposed_schedule_refs"),
        ForeignKeyConstraint(["bundle_id", "case_id"], ["case_financial_input_bundles.id", "case_financial_input_bundles.case_id"], name="fk_proposed_schedule_bundle_case", ondelete="RESTRICT"),
        UniqueConstraint("id", "case_id", name="uq_proposed_schedule_id_case"),
        Index("ix_proposed_schedule_case_created", "case_id", "created_at"),
    )


class CaseBusinessEngineReceipt(Base):
    __tablename__ = "case_business_engine_receipts"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    bundle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    input_bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    calculation_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    product_code: Mapped[str] = mapped_column(String(80), nullable=False)
    product_version: Mapped[str] = mapped_column(String(80), nullable=False)
    product_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False)
    scenario_references: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    received_by: Mapped[str] = mapped_column(String(160), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint("input_bundle_sha256 ~ '^[0-9a-f]{64}$' AND output_sha256 ~ '^[0-9a-f]{64}$' AND product_sha256 ~ '^[0-9a-f]{64}$' AND policy_sha256 ~ '^[0-9a-f]{64}$'", name="ck_business_engine_receipt_hashes"),
        CheckConstraint("result_status IN ('COMPLETED','HOLD','FAILED')", name="ck_business_engine_receipt_status"),
        CheckConstraint("jsonb_typeof(scenario_references) = 'object'", name="ck_business_engine_scenario_object"),
        CheckConstraint("result_status <> 'COMPLETED' OR (schedule_reference_id IS NOT NULL AND scenario_references ? 'BASELINE' AND scenario_references ? 'STRESS_1' AND scenario_references ? 'STRESS_2' AND jsonb_object_length(scenario_references) = 3)", name="ck_business_engine_completed_scenarios"),
        CheckConstraint("length(trim(calculation_reference)) > 0 AND length(trim(calculation_version)) > 0 AND length(trim(policy_reference)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(product_code)) > 0 AND length(trim(product_version)) > 0 AND length(trim(received_by)) > 0", name="ck_business_engine_receipt_refs"),
        ForeignKeyConstraint(["bundle_id", "case_id"], ["case_financial_input_bundles.id", "case_financial_input_bundles.case_id"], name="fk_business_engine_receipt_bundle_case", ondelete="RESTRICT"),
        ForeignKeyConstraint(["schedule_reference_id", "case_id"], ["case_proposed_schedule_references.id", "case_proposed_schedule_references.case_id"], name="fk_business_engine_receipt_schedule_case", ondelete="RESTRICT"),
        Index("ix_business_engine_receipt_case_received", "case_id", "received_at"),
    )
