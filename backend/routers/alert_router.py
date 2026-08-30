from typing import List, Optional
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import Alert, Event, Camera, AuditLog
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
        cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
        target_id = cam.id if cam else camera_id
        query = query.filter((Alert.camera_id == target_id) | (Alert.camera_id == camera_id))
    if severity:
        query = query.filter(Alert.severity == severity)
    if status:
        query = query.filter(Alert.status == status)

    alerts = query.order_by(Alert.timestamp.desc()).limit(limit).all()
    res = []
    for a in alerts:
        cam = db.query(Camera).filter((Camera.id == a.camera_id) | (Camera.camera_id == a.camera_id)).first()
        ev = db.query(Event).filter(Event.camera_id == a.camera_id, Event.timestamp == a.timestamp).first()
        ev_details = ev.details if (ev and isinstance(ev.details, dict)) else {}

        cam_number = cam.camera_id if cam else a.camera_id
        cam_name   = cam.name if cam else "Camera"
        cam_display = f"{cam_number} - {cam_name}" if (cam_number and cam_name) else (cam_number or a.camera_id)

        res.append({
            "id": a.id,
            "alert_id": a.id,
            "incident_id": a.incident_id,
            "camera_id": a.camera_id,
            "camera_number": cam_number,
            "camera_name": cam_name,
            "camera_display": cam_display,
            "location": cam.location if (cam and cam.location) else (ev_details.get("location") or "Campus Perimeter"),
            "event_type": a.event_type,
            "severity": a.severity,
            "risk_score": a.risk_score,
            "confidence": a.confidence,
            "status": a.status,
            "evidence_url": a.evidence_url,
            "person_name": ev_details.get("person_name"),
            "person_id": ev_details.get("person_id"),
            "category": ev_details.get("category"),
            "zone_id": ev_details.get("zone_id"),
            "zone_name": ev_details.get("zone_name"),
            # Always backend-generated UTC timestamp with Z suffix
            "timestamp": f"{a.timestamp.isoformat()}Z" if a.timestamp else None,
            "created_at": (f"{a.created_at.isoformat()}Z" if hasattr(a, "created_at") and a.created_at else (f"{a.timestamp.isoformat()}Z" if a.timestamp else None))
        })
    return res

@router.put("/{alert_id}/acknowledge", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "ACKNOWLEDGED"

    audit = AuditLog(username=current_user.username, action="ACKNOWLEDGE_ALERT", resource="alerts", details={"alert_id": alert_id})
    db.add(audit)
    db.commit()

    # Broadcast ALERT_UPDATED so all connected frontends sync status immediately
    try:
        from backend.main import manager
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(manager.broadcast({
                "type": "ALERT_UPDATED",
                "alert_id": alert_id,
                "status": "ACKNOWLEDGED"
            }))
    except Exception:
        pass  # Non-critical: broadcast best-effort

    return {"status": "success", "alert_id": alert_id, "alert_status": alert.status}


@router.put("/{alert_id}/resolve", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def resolve_alert(alert_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "RESOLVED"

    audit = AuditLog(username=current_user.username, action="RESOLVE_ALERT", resource="alerts", details={"alert_id": alert_id})
    db.add(audit)
    db.commit()

    try:
        from backend.main import manager
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(manager.broadcast({
                "type": "ALERT_UPDATED",
                "alert_id": alert_id,
                "status": "RESOLVED"
            }))
    except Exception:
        pass

    return {"status": "success", "alert_id": alert_id, "alert_status": alert.status}

@router.post("/resolve-all", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def resolve_all_alerts(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    updated_count = db.query(Alert).filter(Alert.status.in_(["NEW", "ACKNOWLEDGED"])).update({Alert.status: "RESOLVED"}, synchronize_session=False)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="RESOLVE_ALL_ALERTS",
        resource="alerts",
        details={"resolved_count": updated_count}
    )
    db.add(audit)
    db.commit()

    return {"status": "success", "resolved_count": updated_count}


class BulkDeleteAlertRequest(BaseModel):
    alert_ids: List[str]


@router.delete("/{alert_id}", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def delete_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Permanently deletes a security alert record from the database.
    Creates an immutable audit log entry.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert #{alert_id} not found")

    cam_id = alert.camera_id
    ev_type = alert.event_type
    sev = alert.severity
    ts = alert.timestamp.isoformat() if alert.timestamp else None

    # Record audit log
    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_ALERT",
        resource="alerts",
        details={
            "alert_id": alert_id,
            "camera_id": cam_id,
            "event_type": ev_type,
            "severity": sev,
            "timestamp": ts
        }
    )
    db.add(audit)

    # Delete alert
    db.delete(alert)
    db.commit()

    return {
        "success": True,
        "message": f"Alert #{alert_id[:8]} deleted successfully",
        "deleted_id": alert_id
    }


@router.post("/bulk-delete", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def bulk_delete_alerts(
    payload: BulkDeleteAlertRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Permanently bulk-deletes multiple security alert records from the database.
    """
    if not payload.alert_ids:
        raise HTTPException(status_code=400, detail="No alert IDs provided for deletion")

    if len(payload.alert_ids) > 100:
        raise HTTPException(status_code=400, detail="Cannot delete more than 100 alerts at once")

    items = db.query(Alert).filter(Alert.id.in_(payload.alert_ids)).all()
    if not items:
        return {"success": True, "deleted_count": 0, "deleted_ids": [], "message": "No matching alerts found"}

    deleted_ids = []
    for item in items:
        deleted_ids.append(item.id)
        db.delete(item)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="BULK_DELETE_ALERTS",
        resource="alerts",
        details={
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids
        }
    )
    db.add(audit)
    db.commit()

    return {
        "success": True,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "message": f"Successfully deleted {len(deleted_ids)} alert records"
    }

