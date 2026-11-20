from sqlalchemy.orm import Session
from app import models

def create_case(db: Session, external_case_id: str, bank_id: str, analysis_date=None):
    obj = models.Case(external_case_id=external_case_id, bank_id=bank_id, analysis_date=analysis_date)
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

def get_case(db: Session, case_id):
    return db.query(models.Case).filter(models.Case.id == case_id).first()

def list_case_documents(db: Session, case_id):
    return db.query(models.Document).filter(models.Document.case_id == case_id).order_by(models.Document.created_at.desc()).all()

def list_case_transactions(db: Session, case_id):
    return db.query(models.Transaction).filter(models.Transaction.case_id == case_id).order_by(models.Transaction.source_row).all()
