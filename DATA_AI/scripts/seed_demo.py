"""Insert synthetic demo records after Flyway migrations. Never use real customer data here."""
import uuid
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.database import get_session_factory
from app import models

BANK_ID = uuid.UUID("b0000000-0000-4000-8000-000000000001")
CUSTOMER_ID = uuid.UUID("b1000000-0000-4000-8000-000000000001")
CASE_ID = uuid.UUID("b2000000-0000-4000-8000-000000000001")
APP_ID = uuid.UUID("b3000000-0000-4000-8000-000000000001")
STAFF_ID = uuid.UUID("b4000000-0000-4000-8000-000000000001")


def main():
    db: Session = get_session_factory()()
    try:
        if not db.query(models.BankOrganization).filter_by(id=BANK_ID).first():
            db.add(models.BankOrganization(id=BANK_ID, bank_code="DEMO-BANK", bank_name="Demo Bank (Synthetic)"))
        if not db.query(models.CustomerProfile).filter_by(id=CUSTOMER_ID).first():
            db.add(models.CustomerProfile(id=CUSTOMER_ID, bank_id=BANK_ID, customer_code="DEMO-CUS-001",
                full_name="Nguyen Van An (DEMO)", date_of_birth=date(1995, 5, 20), gender="OTHER",
                phone="0900000001", email="demo.customer@example.local", identity_type="CCCD",
                identity_last4="1234", marital_status="SINGLE", dependents_count=0))
            db.flush()
            db.add(models.CustomerAddress(customer_id=CUSTOMER_ID, address_type="RESIDENTIAL", country_code="VN",
                province_name="Ho Chi Minh City", district_name="District 1", ward_name="Ben Nghe",
                street_address="1 Demo Street", is_primary=True))
            db.add(models.CustomerEmployment(customer_id=CUSTOMER_ID, employment_type="SALARIED",
                employer_name="Demo Company", job_title="Software Engineer", industry="Technology",
                start_date=date(2022, 1, 1), monthly_income_declared=Decimal("25000000.00"), income_currency="VND"))
        if not db.query(models.Case).filter_by(id=CASE_ID).first():
            db.add(models.Case(id=CASE_ID, external_case_id="DEMO-CASE-001", bank_id="DEMO-BANK",
                customer_id=CUSTOMER_ID, status="SUBMITTED"))
            db.flush()
            db.add(models.LoanApplication(id=APP_ID, case_id=CASE_ID, customer_id=CUSTOMER_ID,
                product_code="PERSONAL_UNSECURED", requested_amount=Decimal("80000000.00"),
                requested_term_months=24, loan_purpose="Household expenses (synthetic demo)"))
            db.add(models.ApplicantSubmission(case_id=CASE_ID, applicant_ref="DEMO-CUS-001", form_version="1.0",
                form_data={"full_name":"Nguyen Van An (DEMO)","phone":"0900000001","email":"demo.customer@example.local",
                    "employment_type":"SALARIED","monthly_income_declared":"25000000","currency":"VND"},
                consent_reference="DEMO-CONSENT-NOT-VALID", submitted_by="seed_demo"))
        if not db.query(models.StaffUser).filter_by(id=STAFF_ID).first():
            db.add(models.StaffUser(id=STAFF_ID, bank_id=BANK_ID, employee_code="DEMO-STAFF-001",
                full_name="Demo Data Staff", email="demo.staff@example.local", staff_type="DATA_AI_STAFF"))
            db.flush()
            role = db.query(models.AccessRole).filter_by(role_code="DATA_AI_STAFF").first()
            if role:
                db.add(models.StaffUserRole(staff_user_id=STAFF_ID, role_id=role.id))
        db.commit()
        print("Synthetic demo data inserted. No real personal data was used.")
        print(f"Bank ID: {BANK_ID}\nCustomer ID: {CUSTOMER_ID}\nCase ID: {CASE_ID}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
