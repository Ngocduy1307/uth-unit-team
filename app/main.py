from uuid import UUID
import secrets
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, repository, service
from app.schemas import CaseCreate, CaseOut, DocumentOut
from app.config import settings

app = FastAPI(
    title="UNIT Income & Affordability - DATA AI Service",
    version="1.0.0",
    description=("Document intelligence service for evidence intake, OCR, extraction suggestions "
                "and transaction classification. Does not calculate DSR or approve loans."),
)

def require_internal_token(x_internal_service_token: str | None = Header(default=None)):
    # Local development may disable auth. Production must set a long random token and
    # place this service behind the authenticated Spring Boot gateway/network policy.
    if settings.internal_service_token:
        if not x_internal_service_token or not secrets.compare_digest(
            x_internal_service_token, settings.internal_service_token
        ):
            raise HTTPException(status_code=401, detail="Invalid internal service token")

@app.get("/health", tags=["operations"])
def health():
    return {"status": "ok", "service": "data-ai", "version": "1.0.0"}

@app.get("/ready", tags=["operations"])
def ready(db: Session = Depends(get_db)):
    from sqlalchemy import text
    db.execute(text("SELECT 1"))
    try:
        migration_version = db.execute(text("SELECT version FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 1")).scalar()
    except Exception:
        raise HTTPException(503, "Database reachable but Flyway migrations are not applied")
    return {"status": "ready", "database": "reachable", "flyway_latest_version": migration_version}

@app.post("/api/v1/cases", response_model=CaseOut, status_code=201, dependencies=[Depends(require_internal_token)])
def create_case(payload: CaseCreate, db: Session = Depends(get_db)):
    if db.query(models.Case).filter_by(external_case_id=payload.external_case_id).first():
        raise HTTPException(409, "external_case_id already exists")
    return repository.create_case(db, payload.external_case_id, payload.bank_id, payload.analysis_date)

@app.get("/api/v1/cases/{case_id}", dependencies=[Depends(require_internal_token)])
def get_case(case_id: UUID, db: Session = Depends(get_db)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return {"id": str(case.id), "external_case_id": case.external_case_id,
            "bank_id": case.bank_id, "analysis_date": case.analysis_date,
            "status": case.status, "created_at": case.created_at}

@app.post("/api/v1/cases/{case_id}/documents", response_model=DocumentOut, status_code=201, dependencies=[Depends(require_internal_token)])
async def upload_document(case_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    # Enforce size while streaming into memory for this pilot-sized upload limit.
    content = await file.read(settings.max_file_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_file_mb} MiB")
    try:
        return service.save_upload(db, case, file.filename or "upload", content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.post("/api/v1/cases/{case_id}/documents/{document_id}/process", dependencies=[Depends(require_internal_token)])
def process(case_id: UUID, document_id: UUID, db: Session = Depends(get_db)):
    case = repository.get_case(db, case_id)
    doc = db.query(models.Document).filter_by(id=document_id, case_id=case_id).first()
    if not case or not doc:
        raise HTTPException(404, "Case/document not found")
    try:
        return service.process_document(db, case, doc)
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, f"Processing failed: {type(exc).__name__}")

@app.get("/api/v1/cases/{case_id}/documents", dependencies=[Depends(require_internal_token)])
def documents(case_id: UUID, db: Session = Depends(get_db)):
    if not repository.get_case(db, case_id):
        raise HTTPException(404, "Case not found")
    return repository.list_case_documents(db, case_id)

@app.get("/api/v1/cases/{case_id}/transactions", dependencies=[Depends(require_internal_token)])
def transactions(case_id: UUID, db: Session = Depends(get_db)):
    if not repository.get_case(db, case_id):
        raise HTTPException(404, "Case not found")
    return repository.list_case_transactions(db, case_id)

@app.get("/api/v1/cases/{case_id}/fields", dependencies=[Depends(require_internal_token)])
def extracted_fields(case_id: UUID, db: Session = Depends(get_db)):
    if not repository.get_case(db, case_id):
        raise HTTPException(404, "Case not found")
    return (db.query(models.ExtractedField)
            .join(models.Document, models.Document.id == models.ExtractedField.document_id)
            .filter(models.Document.case_id == case_id)
            .order_by(models.ExtractedField.created_at).all())

# ---- Customer form snapshots and staff-only Excel export -----------------
from fastapi import Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from app.schemas import ApplicantSubmissionIn
from app.export_service import build_data_workbook
import json

@app.post("/api/v1/cases/{case_id}/applicant-submissions", status_code=201,
          dependencies=[Depends(require_internal_token)], tags=["applicant-data"])
def create_applicant_submission(
    case_id: UUID,
    payload: ApplicantSubmissionIn,
    x_actor_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Backend-to-DATA-AI endpoint. Backend must validate consent and allowed form fields first."""
    case = repository.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if len(json.dumps(payload.form_data, ensure_ascii=False, default=str).encode("utf-8")) > 100_000:
        raise HTTPException(413, "Applicant form payload exceeds 100 KB")
    existing = db.query(models.ApplicantSubmission).filter_by(
        case_id=case_id, applicant_ref=payload.applicant_ref, form_version=payload.form_version
    ).first()
    if existing:
        raise HTTPException(409, "This applicant form version already exists; submit a new form_version")
    obj = models.ApplicantSubmission(
        case_id=case_id,
        applicant_ref=payload.applicant_ref,
        form_version=payload.form_version,
        form_data=payload.form_data,
        consent_reference=payload.consent_reference,
        submitted_by=(x_actor_id or "backend")[:120],
    )
    db.add(obj)
    db.add(models.AuditEvent(case_id=case_id, actor=(x_actor_id or "backend")[:100],
        action="APPLICANT_FORM_RECEIVED", entity_type="applicant_submission",
        entity_id=payload.applicant_ref, details={"form_version": payload.form_version}))
    db.commit()
    db.refresh(obj)
    return {"id": str(obj.id), "case_id": str(obj.case_id), "applicant_ref": obj.applicant_ref,
            "form_version": obj.form_version, "submitted_at": obj.submitted_at.isoformat()}


def require_export_staff(
    x_actor_id: str | None = Header(default=None),
    x_actor_roles: str | None = Header(default=None),
    x_bank_id: str | None = Header(default=None),
):
    roles = {r.strip().upper() for r in (x_actor_roles or "").replace(";", ",").split(",") if r.strip()}
    if not x_actor_id or not x_bank_id:
        raise HTTPException(401, "Missing trusted actor or bank context from Backend")
    if not roles.intersection({"STAFF", "BANK_STAFF", "DATA_AI_STAFF", "BANK_ADMIN", "SYSTEM_ADMIN", "ADMIN"}):
        raise HTTPException(403, "Staff role required to export data")
    return {"actor_id": x_actor_id[:120], "bank_id": x_bank_id[:100], "roles": sorted(roles)}

@app.get("/api/v1/admin/exports/excel", dependencies=[Depends(require_internal_token)],
         tags=["data-export"])
def export_excel(
    case_id: UUID | None = Query(default=None),
    staff=Depends(require_export_staff),
    db: Session = Depends(get_db),
):
    """Create an XLSX snapshot for the staff member's bank. Backend must overwrite identity headers."""
    if case_id:
        case = repository.get_case(db, case_id)
        if not case or case.bank_id != staff["bank_id"]:
            raise HTTPException(404, "Case not found in caller bank scope")
    output, counts = build_data_workbook(db, staff["bank_id"], case_id)
    job = models.ExportJob(bank_id=staff["bank_id"], requested_by=staff["actor_id"],
        export_scope="BOTH", filters={"case_id": str(case_id) if case_id else None},
        row_counts=counts, status="COMPLETED")
    db.add(job)
    export_bank = db.query(models.BankOrganization).filter_by(bank_code=staff["bank_id"]).first()
    db.add(models.ManagementAuditLog(bank_id=export_bank.id if export_bank else None, actor_external_id=staff["actor_id"], action="DATA_EXCEL_EXPORTED",
        target_type="export_job", target_id=str(job.id),
        after_data={"scope": "BOTH", "row_counts": counts, "bank_id": staff["bank_id"],
                    "case_id": str(case_id) if case_id else None}))
    if case_id:
        db.add(models.AuditEvent(case_id=case_id, actor=staff["actor_id"], action="DATA_EXCEL_EXPORTED",
            entity_type="export", entity_id=str(job.id), details={"scope": "BOTH", "row_counts": counts,
            "bank_id": staff["bank_id"]}))
    db.commit()
    filename = f"data_ai_export_{job.id}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"',
               "X-Export-Id": str(job.id), "Cache-Control": "no-store"}
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers)

@app.get("/api/v1/admin/exports/history", dependencies=[Depends(require_internal_token)],
         tags=["data-export"])
def export_history(staff=Depends(require_export_staff), db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    rows = db.query(models.ExportJob).filter_by(bank_id=staff["bank_id"]).order_by(models.ExportJob.created_at.desc()).limit(limit).all()
    return [{"id": str(r.id), "requested_by": r.requested_by, "scope": r.export_scope,
             "filters": r.filters, "row_counts": r.row_counts, "status": r.status,
             "created_at": r.created_at} for r in rows]

# ---- Customer / staff / configurable form management ----------------------
from datetime import datetime, timezone
from app.schemas import CustomerCreate, CustomerUpdate, LoanApplicationCreate, StaffSyncIn, FormDefinitionUpdate, BankOrganizationIn, BankBranchIn


def _validate_form_values(fields, form_data):
    import re
    from decimal import Decimal, InvalidOperation
    from datetime import date as date_type
    errors = []
    for field in fields:
        key = field.field_key
        value = form_data.get(key)
        if field.is_required and value in (None, ""):
            errors.append(key)
            continue
        if value in (None, ""):
            continue
        rules = field.validation_json or {}
        try:
            if field.data_type == "number":
                number = Decimal(str(value))
                if "minimum" in rules and number < Decimal(str(rules["minimum"])): errors.append(key)
                if "maximum" in rules and number > Decimal(str(rules["maximum"])): errors.append(key)
            elif field.data_type == "date":
                date_type.fromisoformat(str(value))
            elif field.data_type in {"text", "email", "phone", "select", "textarea"}:
                if not isinstance(value, str): errors.append(key); continue
                if "max_length" in rules and len(value) > int(rules["max_length"]): errors.append(key)
                pattern = rules.get("pattern")
                if pattern and not re.fullmatch(pattern, value): errors.append(key)
                options = field.options_json or rules.get("options")
                if field.data_type == "select" and options and value not in options: errors.append(key)
            elif field.data_type == "checkbox" and not isinstance(value, bool):
                errors.append(key)
        except (ValueError, InvalidOperation, TypeError):
            errors.append(key)
    return sorted(set(errors))


def _customer_out(customer, db):
    address = db.query(models.CustomerAddress).filter_by(customer_id=customer.id).order_by(models.CustomerAddress.is_primary.desc()).first()
    employment = db.query(models.CustomerEmployment).filter_by(customer_id=customer.id).order_by(models.CustomerEmployment.is_current.desc()).first()
    return {
        "id": str(customer.id), "customer_code": customer.customer_code,
        "full_name": customer.full_name, "date_of_birth": customer.date_of_birth,
        "gender": customer.gender, "nationality": customer.nationality,
        "phone": customer.phone, "email": customer.email,
        "identity_type": customer.identity_type, "identity_last4": customer.identity_last4,
        "marital_status": customer.marital_status, "dependents_count": customer.dependents_count,
        "preferred_contact_method": customer.preferred_contact_method,
        "customer_status": customer.customer_status,
        "address": ({"address_type": address.address_type, "country_code": address.country_code,
                     "province_code": address.province_code, "province_name": address.province_name,
                     "district_name": address.district_name, "ward_name": address.ward_name,
                     "street_address": address.street_address} if address else None),
        "employment": ({"employment_type": employment.employment_type, "employer_name": employment.employer_name,
                        "job_title": employment.job_title, "industry": employment.industry,
                        "start_date": employment.start_date, "monthly_income_declared": employment.monthly_income_declared,
                        "income_currency": employment.income_currency, "is_current": employment.is_current} if employment else None),
        "created_at": customer.created_at, "updated_at": customer.updated_at,
    }


@app.post("/api/v1/customers", status_code=201, tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None)):
    if db.query(models.CustomerProfile).filter_by(customer_code=payload.customer_code).first():
        raise HTTPException(409, "customer_code already exists")
    if payload.bank_id and not db.query(models.BankOrganization).filter_by(id=payload.bank_id).first():
        raise HTTPException(400, "Unknown bank_id")
    customer = models.CustomerProfile(**payload.model_dump(exclude={"address", "employment"}))
    db.add(customer)
    db.flush()
    if payload.address:
        db.add(models.CustomerAddress(customer_id=customer.id, **payload.address.model_dump()))
    if payload.employment:
        db.add(models.CustomerEmployment(customer_id=customer.id, **payload.employment.model_dump()))
    db.add(models.ManagementAuditLog(bank_id=customer.bank_id, actor_external_id=x_actor_id or "backend", action="CUSTOMER_CREATED",
        target_type="customer", target_id=str(customer.id), after_data={"customer_code": customer.customer_code}))
    db.commit(); db.refresh(customer)
    return _customer_out(customer, db)


@app.get("/api/v1/customers/{customer_id}", tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def get_customer(customer_id: UUID, db: Session = Depends(get_db)):
    customer = db.query(models.CustomerProfile).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    return _customer_out(customer, db)


@app.get("/api/v1/customers", tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def list_customers(bank_id: UUID | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = db.query(models.CustomerProfile)
    if bank_id:
        query = query.filter(models.CustomerProfile.bank_id == bank_id)
    rows = query.order_by(models.CustomerProfile.created_at.desc()).offset(offset).limit(limit).all()
    return [_customer_out(c, db) for c in rows]


@app.patch("/api/v1/customers/{customer_id}", tags=["customer-management"], dependencies=[Depends(require_internal_token)])
def update_customer(customer_id: UUID, payload: CustomerUpdate, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None)):
    customer = db.query(models.CustomerProfile).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    update_data = payload.model_dump(exclude_unset=True)
    address_data = update_data.pop("address", None)
    employment_data = update_data.pop("employment", None)
    before = {k: getattr(customer, k) for k in update_data}
    for key, value in update_data.items():
        setattr(customer, key, value)
    if address_data is not None:
        address = db.query(models.CustomerAddress).filter_by(customer_id=customer.id, is_primary=True).first()
        if address is None:
            address = models.CustomerAddress(customer_id=customer.id, **address_data)
            db.add(address)
        else:
            for key, value in address_data.items(): setattr(address, key, value)
    if employment_data is not None:
        employment = db.query(models.CustomerEmployment).filter_by(customer_id=customer.id, is_current=True).first()
        if employment is None:
            employment = models.CustomerEmployment(customer_id=customer.id, **employment_data)
            db.add(employment)
        else:
            for key, value in employment_data.items(): setattr(employment, key, value)
    customer.updated_at = datetime.now(timezone.utc)
    db.add(models.ManagementAuditLog(bank_id=customer.bank_id, actor_external_id=x_actor_id or "backend", action="CUSTOMER_UPDATED",
        target_type="customer", target_id=str(customer.id), before_data={k: str(v) if v is not None else None for k,v in before.items()},
        after_data=payload.model_dump(exclude_unset=True, mode="json")))
    db.commit(); db.refresh(customer)
    return _customer_out(customer, db)


@app.post("/api/v1/customers/{customer_id}/applications", status_code=201, tags=["application-management"], dependencies=[Depends(require_internal_token)])
def create_customer_application(customer_id: UUID, payload: LoanApplicationCreate, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None)):
    customer = db.query(models.CustomerProfile).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    bank = db.query(models.BankOrganization).filter_by(bank_code=payload.bank_id, status="ACTIVE").first()
    if not bank:
        raise HTTPException(400, "Unknown or inactive bank_id. Register the bank organization first.")
    if customer.bank_id and customer.bank_id != bank.id:
        raise HTTPException(403, "Customer does not belong to the requested bank")
    if customer.bank_id is None:
        customer.bank_id = bank.id
    if db.query(models.Case).filter_by(external_case_id=payload.external_case_id).first():
        raise HTTPException(409, "external_case_id already exists")
    case = models.Case(external_case_id=payload.external_case_id, bank_id=payload.bank_id, customer_id=customer.id, status="SUBMITTED")
    db.add(case); db.flush()
    application = models.LoanApplication(case_id=case.id, customer_id=customer.id,
        product_code=payload.product_code, requested_amount=payload.requested_amount,
        requested_term_months=payload.requested_term_months, loan_purpose=payload.loan_purpose,
        preferred_disbursement_account_last4=payload.preferred_disbursement_account_last4)
    db.add(application)
    address = db.query(models.CustomerAddress).filter_by(customer_id=customer.id).order_by(models.CustomerAddress.is_primary.desc()).first()
    employment = db.query(models.CustomerEmployment).filter_by(customer_id=customer.id).order_by(models.CustomerEmployment.is_current.desc()).first()
    form_data = dict(payload.form_data)
    form_data.update({"customer_code": customer.customer_code, "full_name": customer.full_name,
        "phone": customer.phone, "email": customer.email, "date_of_birth": str(customer.date_of_birth) if customer.date_of_birth else None,
        "gender": customer.gender, "marital_status": customer.marital_status, "dependents_count": customer.dependents_count,
        "identity_last4": customer.identity_last4,
        "street_address": address.street_address if address else None,
        "province_name": address.province_name if address else None,
        "employment_type": employment.employment_type if employment else None,
        "employer_name": employment.employer_name if employment else None,
        "job_title": employment.job_title if employment else None,
        "monthly_income_declared": str(employment.monthly_income_declared) if employment and employment.monthly_income_declared is not None else None,
        "requested_amount": str(payload.requested_amount), "requested_term_months": payload.requested_term_months,
        "loan_purpose": payload.loan_purpose})
    active_form = db.query(models.FormDefinition).filter_by(form_code="CUSTOMER_LOAN_APPLICATION", is_active=True).order_by(models.FormDefinition.created_at.desc()).first()
    if active_form and active_form.version != payload.form_version:
        raise HTTPException(409, f"Form version mismatch. Active version is {active_form.version}")
    if active_form:
        configured_fields = db.query(models.FormFieldDefinition).filter_by(form_definition_id=active_form.id, is_active=True).all()
        invalid_fields = _validate_form_values(configured_fields, form_data)
        if invalid_fields:
            raise HTTPException(422, {"message": "Application form contains missing or invalid fields", "fields": invalid_fields})
    db.add(models.ApplicantSubmission(case_id=case.id, applicant_ref=customer.customer_code,
        form_version=payload.form_version, form_data=form_data, consent_reference=payload.consent_reference,
        submitted_by=x_actor_id or "backend"))
    db.add(models.ManagementAuditLog(bank_id=bank.id, actor_external_id=x_actor_id or "backend", action="APPLICATION_CREATED",
        target_type="loan_application", target_id=str(application.id), after_data={"case_id": str(case.id), "customer_id": str(customer.id)}))
    db.commit(); db.refresh(application)
    return {"case_id": str(case.id), "application_id": str(application.id), "customer_id": str(customer.id),
        "external_case_id": case.external_case_id, "application_status": application.application_status,
        "submitted_at": application.submitted_at}


def _trusted_staff_context(x_actor_id: str | None, x_actor_roles: str | None, x_bank_id: str | None):
    roles = {r.strip().upper() for r in (x_actor_roles or "").replace(";", ",").split(",") if r.strip()}
    if not x_actor_id or not x_bank_id:
        raise HTTPException(401, "Missing trusted actor or bank context from Backend")
    return x_actor_id[:160], roles, x_bank_id[:100]


@app.post("/api/v1/internal/staff-sync", tags=["staff-management"], dependencies=[Depends(require_internal_token)])
def sync_staff(payload: StaffSyncIn, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None)):
    """Mirror staff identity and roles from Backend/SSO. No password or credential is stored here."""
    if payload.bank_id and not db.query(models.BankOrganization).filter_by(id=payload.bank_id).first():
        raise HTTPException(400, "Unknown staff bank_id")
    if payload.branch_id:
        branch = db.query(models.BankBranch).filter_by(id=payload.branch_id).first()
        if not branch or branch.bank_id != payload.bank_id:
            raise HTTPException(400, "Staff branch must belong to the selected bank")
    staff = db.query(models.StaffUser).filter_by(employee_code=payload.employee_code).first()
    if not staff:
        staff = models.StaffUser(employee_code=payload.employee_code, full_name=payload.full_name, email=payload.email)
        db.add(staff)
    staff.full_name = payload.full_name; staff.email = payload.email; staff.bank_id = payload.bank_id
    staff.branch_id = payload.branch_id; staff.phone = payload.phone; staff.staff_type = payload.staff_type
    staff.external_identity_id = payload.external_identity_id; staff.status = "ACTIVE"
    db.flush()
    desired_roles = set(r.upper() for r in payload.roles)
    existing_links = db.query(models.StaffUserRole).filter_by(staff_user_id=staff.id).all()
    for existing_link in existing_links:
        existing_role = db.query(models.AccessRole).filter_by(id=existing_link.role_id).first()
        if existing_role and existing_role.role_code not in desired_roles:
            db.delete(existing_link)
    assigned = []
    for role_code in desired_roles:
        role = db.query(models.AccessRole).filter_by(role_code=role_code).first()
        if not role:
            raise HTTPException(400, f"Unsupported role: {role_code}")
        link = db.query(models.StaffUserRole).filter_by(staff_user_id=staff.id, role_id=role.id).first()
        if not link:
            db.add(models.StaffUserRole(staff_user_id=staff.id, role_id=role.id))
        assigned.append(role_code)
    db.add(models.ManagementAuditLog(bank_id=payload.bank_id, actor_external_id=x_actor_id or "backend", action="STAFF_SYNCED",
        target_type="staff_user", target_id=str(staff.id), after_data={"roles": assigned}))
    db.commit()
    return {"staff_id": str(staff.id), "employee_code": staff.employee_code, "roles": assigned, "status": staff.status}


@app.get("/api/v1/admin/forms/{form_code}", tags=["form-management"], dependencies=[Depends(require_internal_token)])
def get_form_definition(form_code: str, db: Session = Depends(get_db)):
    form = db.query(models.FormDefinition).filter_by(form_code=form_code, is_active=True).order_by(models.FormDefinition.created_at.desc()).first()
    if not form:
        raise HTTPException(404, "Active form not found")
    fields = db.query(models.FormFieldDefinition).filter_by(form_definition_id=form.id, is_active=True).order_by(models.FormFieldDefinition.display_order).all()
    return {"form_code": form.form_code, "form_name": form.form_name, "version": form.version,
        "audience": form.audience, "definition": form.definition_json,
        "fields": [{"field_key": f.field_key, "field_label": f.field_label, "data_type": f.data_type,
            "is_required": f.is_required, "is_sensitive": f.is_sensitive, "display_order": f.display_order,
            "validation": f.validation_json, "options": f.options_json} for f in fields]}


@app.put("/api/v1/admin/forms/{form_code}", tags=["form-management"], dependencies=[Depends(require_internal_token)])
def publish_form_definition(form_code: str, payload: FormDefinitionUpdate, db: Session = Depends(get_db),
                            x_actor_id: str | None = Header(default=None), x_actor_roles: str | None = Header(default=None),
                            x_bank_id: str | None = Header(default=None)):
    actor, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN", "ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    form_bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
    if "SYSTEM_ADMIN" not in roles and "ADMIN" not in roles and not form_bank:
        raise HTTPException(404, "Bank scope not found")
    if len(payload.fields) > 150:
        raise HTTPException(422, "A form can contain at most 150 fields")
    db.query(models.FormDefinition).filter_by(form_code=form_code, is_active=True).update({"is_active": False})
    form = models.FormDefinition(form_code=form_code, form_name=payload.form_name, version=payload.version,
        audience=payload.audience, definition_json=payload.definition_json, is_active=True)
    db.add(form); db.flush()
    for index, item in enumerate(payload.fields):
        key = item.get("field_key"); label = item.get("field_label"); dtype = item.get("data_type", "text")
        if not key or not label or dtype not in {"text", "email", "phone", "date", "number", "select", "checkbox", "textarea"}:
            db.rollback(); raise HTTPException(422, "Each field requires field_key, field_label and a supported data_type")
        db.add(models.FormFieldDefinition(form_definition_id=form.id, field_key=key, field_label=label,
            data_type=dtype, is_required=bool(item.get("is_required", False)),
            is_sensitive=bool(item.get("is_sensitive", False)), display_order=int(item.get("display_order", index)),
            validation_json=item.get("validation", {}), options_json=item.get("options", [])))
    db.add(models.ManagementAuditLog(bank_id=form_bank.id if form_bank else None, actor_external_id=actor, action="FORM_VERSION_PUBLISHED",
        target_type="form_definition", target_id=str(form.id), after_data={"form_code": form_code, "version": payload.version}))
    db.commit()
    return {"form_code": form_code, "version": payload.version, "field_count": len(payload.fields), "status": "PUBLISHED"}

@app.get("/api/v1/admin/staff", tags=["staff-management"], dependencies=[Depends(require_internal_token)])
def list_staff(db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
               x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
               limit: int = Query(100, ge=1, le=300)):
    _, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN", "ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
    query = db.query(models.StaffUser)
    if "SYSTEM_ADMIN" not in roles:
        if not bank:
            raise HTTPException(404, "Bank scope not found")
        query = query.filter(models.StaffUser.bank_id == bank.id)
    staff_rows = query.order_by(models.StaffUser.created_at.desc()).limit(limit).all()
    output = []
    for item in staff_rows:
        role_rows = (db.query(models.AccessRole.role_code).join(models.StaffUserRole,
            models.StaffUserRole.role_id == models.AccessRole.id).filter(models.StaffUserRole.staff_user_id == item.id).all())
        output.append({"id": str(item.id), "employee_code": item.employee_code, "full_name": item.full_name,
            "email": item.email, "phone": item.phone, "staff_type": item.staff_type,
            "status": item.status, "roles": [r[0] for r in role_rows]})
    return output


@app.get("/api/v1/admin/audit-logs", tags=["management-audit"], dependencies=[Depends(require_internal_token)])
def list_management_audit_logs(db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                               x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None),
                               limit: int = Query(100, ge=1, le=500)):
    _, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN", "ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    audit_query = db.query(models.ManagementAuditLog)
    if "SYSTEM_ADMIN" not in roles and "ADMIN" not in roles:
        bank = db.query(models.BankOrganization).filter_by(bank_code=bank_code).first()
        if not bank:
            raise HTTPException(404, "Bank scope not found")
        audit_query = audit_query.filter(models.ManagementAuditLog.bank_id == bank.id)
    rows = audit_query.order_by(models.ManagementAuditLog.created_at.desc()).limit(limit).all()
    return [{"id": str(r.id), "actor_staff_id": str(r.actor_staff_id) if r.actor_staff_id else None,
        "actor_external_id": r.actor_external_id, "action": r.action, "target_type": r.target_type,
        "target_id": r.target_id, "before_data": r.before_data, "after_data": r.after_data,
        "created_at": r.created_at} for r in rows]

@app.post("/api/v1/admin/banks", status_code=201, tags=["bank-management"], dependencies=[Depends(require_internal_token)])
def create_bank_organization(payload: BankOrganizationIn, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                            x_actor_roles: str | None = Header(default=None)):
    roles = {r.strip().upper() for r in (x_actor_roles or "").replace(";", ",").split(",") if r.strip()}
    if not x_actor_id:
        raise HTTPException(401, "Missing trusted actor")
    if "SYSTEM_ADMIN" not in roles and "ADMIN" not in roles:
        raise HTTPException(403, "System administrator role required")
    code = payload.bank_code.strip()
    name = payload.bank_name.strip()
    if not code or not name:
        raise HTTPException(422, "bank_code and bank_name are required")
    if db.query(models.BankOrganization).filter_by(bank_code=code).first():
        raise HTTPException(409, "bank_code already exists")
    bank = models.BankOrganization(bank_code=code, bank_name=name, status=payload.status)
    db.add(bank); db.flush()
    db.add(models.ManagementAuditLog(bank_id=bank.id, actor_external_id=x_actor_id, action="BANK_CREATED", target_type="bank", target_id=str(bank.id),
        after_data={"bank_code": code, "bank_name": name}))
    db.commit()
    return {"id": str(bank.id), "bank_code": bank.bank_code, "bank_name": bank.bank_name, "status": bank.status}


@app.post("/api/v1/admin/banks/{bank_id}/branches", status_code=201, tags=["bank-management"], dependencies=[Depends(require_internal_token)])
def create_bank_branch(bank_id: UUID, payload: BankBranchIn, db: Session = Depends(get_db), x_actor_id: str | None = Header(default=None),
                       x_actor_roles: str | None = Header(default=None), x_bank_id: str | None = Header(default=None)):
    actor, roles, bank_code = _trusted_staff_context(x_actor_id, x_actor_roles, x_bank_id)
    if not roles.intersection({"BANK_ADMIN", "SYSTEM_ADMIN", "ADMIN"}):
        raise HTTPException(403, "Administrator role required")
    bank = db.query(models.BankOrganization).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(404, "Bank not found")
    if "SYSTEM_ADMIN" not in roles and "ADMIN" not in roles and bank.bank_code != bank_code:
        raise HTTPException(403, "Bank administrator cannot manage another bank")
    branch_code = payload.branch_code.strip()
    branch_name = payload.branch_name.strip()
    if not branch_code or not branch_name:
        raise HTTPException(422, "branch_code and branch_name are required")
    branch = models.BankBranch(bank_id=bank.id, branch_code=branch_code, branch_name=branch_name,
        address=payload.address, status=payload.status)
    db.add(branch); db.flush()
    db.add(models.ManagementAuditLog(bank_id=bank.id, actor_external_id=actor, action="BANK_BRANCH_CREATED", target_type="bank_branch",
        target_id=str(branch.id), after_data={"bank_id": str(bank.id), "branch_code": branch_code}))
    db.commit()
    return {"id": str(branch.id), "bank_id": str(bank.id), "branch_code": branch.branch_code,
        "branch_name": branch.branch_name, "status": branch.status}
