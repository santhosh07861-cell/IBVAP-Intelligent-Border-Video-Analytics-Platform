from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import Alert, AuditLog
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

@router.get("")
def list_alerts(
    camera_id: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Alert)
    if camera_id:
        query = query.filter(Alert.camera_id == camera_id)
    if severity:
        query = query.filter(Alert.severity == severity)
    if status:
        query = query.filter(Alert.status == status)

    alerts = query.order_by(Alert.timestamp.desc()).limit(limit).all()
    return alerts

@router.put("/{alert_id}/acknowledge", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "ACKNOWLEDGED"

    audit = AuditLog(username=current_user.username, action="ACKNOWLEDGE_ALERT", resource="alerts", details={"alert_id": alert_id})
    db.add(audit)
    db.commit()

    return {"status": "success", "alert_id": alert_id, "alert_status": alert.status}
