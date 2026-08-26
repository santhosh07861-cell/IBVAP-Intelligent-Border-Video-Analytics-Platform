from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.connection import get_db
from database.schema import AuditLog
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/audit", tags=["Audit Logging"])

@router.get("", dependencies=[Depends(RequireRole(["Administrator", "Security Operator", "Analyst"]))])
def list_audit_logs(limit: int = 100, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return logs
