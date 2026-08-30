import uuid
from datetime import datetime
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import Camera, CameraZone, ZoneRule, AuditLog
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/zones", tags=["Zones & Virtual Fences"])

class ZoneCreate(BaseModel):
    camera_id: str
    name: str
    zone_type: str = "RESTRICTED AREA"  # RESTRICTED AREA, NO ENTRY, PERIMETER FENCE, BORDER FENCE, LOITERING ZONE, CUSTOM
    geometry_type: str = "polygon"
    coordinates: List[List[float]] = Field(..., min_items=3)
    object_type: str = "all"  # all, person, car, truck, drone
    severity: str = "HIGH"  # HIGH, CRITICAL, MEDIUM, LOW
    min_confidence: float = 0.3
    loitering_threshold_sec: int = 5
    cooldown_sec: int = 30

class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    zone_type: Optional[str] = None
    is_active: Optional[bool] = None
    coordinates: Optional[List[List[float]]] = None

@router.get("", response_model=List[dict])
def list_zones(
    camera_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Returns real configured zones and virtual fences from the database.
    Supports filtering by camera UUID or string camera_id (e.g. CAM-01).
    """
    query = db.query(CameraZone)
    if camera_id:
        cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
        target_id = cam.id if cam else camera_id
        query = query.filter((CameraZone.camera_id == target_id) | (CameraZone.camera_id == camera_id))

    zones = query.all()
    res = []
    for z in zones:
        cam = db.query(Camera).filter(Camera.id == z.camera_id).first()
        rules = db.query(ZoneRule).filter(ZoneRule.zone_id == z.id).all()
        res.append({
            "id": z.id,
            "camera_id": z.camera_id,
            "camera_number": cam.camera_id if cam else z.camera_id,
            "camera_name": cam.name if cam else "Camera",
            "name": z.name,
            "zone_type": z.zone_type,
            "geometry_type": z.geometry_type,
            "coordinates": z.coordinates,
            "is_active": z.is_active,
            "created_at": getattr(z, "created_at", datetime.utcnow()).isoformat() if hasattr(z, "created_at") and z.created_at else datetime.utcnow().isoformat(),
            "rules": [
                {
                    "id": r.id,
                    "object_type": r.object_type,
                    "direction": r.direction,
                    "min_confidence": r.min_confidence,
                    "loitering_threshold_sec": r.loitering_threshold_sec,
                    "severity": r.severity,
                    "cooldown_sec": getattr(r, "cooldown_sec", 30),
                    "enabled": r.enabled
                } for r in rules
            ]
        })
    return res

@router.post("", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def create_zone(
    payload: ZoneCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Creates a new real Virtual Fence / Zone in the database with user-drawn polygon coordinates.
    """
    # Resolve canonical Camera UUID
    cam = db.query(Camera).filter(
        (Camera.camera_id == payload.camera_id) | (Camera.id == payload.camera_id)
    ).first()
    if not cam:
        raise HTTPException(status_code=404, detail=f"Camera '{payload.camera_id}' not found.")

    if len(payload.coordinates) < 3:
        raise HTTPException(status_code=400, detail="Polygon must contain at least 3 coordinate points.")

    # Validate coordinate normalization [0.0, 1.0]
    cleaned_coords = []
    for pt in payload.coordinates:
        if len(pt) < 2:
            continue
        cx = max(0.0, min(1.0, float(pt[0])))
        cy = max(0.0, min(1.0, float(pt[1])))
        cleaned_coords.append([round(cx, 4), round(cy, 4)])

    if len(cleaned_coords) < 3:
        raise HTTPException(status_code=400, detail="Invalid polygon coordinates.")

    zone = CameraZone(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        name=payload.name.strip(),
        zone_type=payload.zone_type.strip().upper(),
        geometry_type=payload.geometry_type,
        coordinates=cleaned_coords,
        is_active=True
    )
    db.add(zone)

    rule = ZoneRule(
        id=str(uuid.uuid4()),
        zone_id=zone.id,
        object_type=payload.object_type.lower(),
        direction="ANY",
        min_confidence=float(payload.min_confidence),
        loitering_threshold_sec=int(payload.loitering_threshold_sec),
        severity=payload.severity.upper(),
        cooldown_sec=int(payload.cooldown_sec),
        enabled=True
    )
    db.add(rule)

    db.commit()
    db.refresh(zone)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="CREATE_VIRTUAL_FENCE_ZONE",
        resource="zones",
        details={
            "zone_id": zone.id,
            "zone_name": zone.name,
            "camera_id": cam.camera_id,
            "points_count": len(cleaned_coords)
        }
    )
    db.add(audit)
    db.commit()

    try:
        from backend.main import manager
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast({
                "type": "ZONES_UPDATE",
                "action": "CREATE",
                "camera_id": cam.camera_id,
                "zone_id": zone.id,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }))
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Virtual fence zone '{zone.name}' saved successfully.",
        "zone_id": zone.id,
        "camera_id": cam.camera_id,
        "name": zone.name,
        "coordinates": zone.coordinates,
        "is_active": zone.is_active
    }

@router.patch("/{zone_id}/toggle", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def toggle_zone(
    zone_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Toggles active/disabled status for a virtual fence zone.
    """
    zone = db.query(CameraZone).filter(CameraZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found.")

    zone.is_active = not zone.is_active
    db.commit()
    db.refresh(zone)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="TOGGLE_ZONE_STATUS",
        resource="zones",
        details={"zone_id": zone.id, "zone_name": zone.name, "is_active": zone.is_active}
    )
    db.add(audit)
    db.commit()

    try:
        from backend.main import manager
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast({
                "type": "ZONES_UPDATE",
                "action": "TOGGLE",
                "zone_id": zone.id,
                "is_active": zone.is_active,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }))
    except Exception:
        pass

    return {
        "status": "success",
        "zone_id": zone.id,
        "is_active": zone.is_active,
        "message": f"Zone '{zone.name}' is now {'ACTIVE' if zone.is_active else 'DISABLED'}."
    }

@router.delete("/{zone_id}", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def delete_zone(
    zone_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Permanently deletes a virtual fence zone and its associated rules from the database.
    """
    zone = db.query(CameraZone).filter(CameraZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found.")

    # Delete rules attached to this zone
    db.query(ZoneRule).filter(ZoneRule.zone_id == zone.id).delete()

    zone_name = zone.name
    camera_id = zone.camera_id

    db.delete(zone)
    db.commit()

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_VIRTUAL_FENCE_ZONE",
        resource="zones",
        details={"zone_id": zone_id, "zone_name": zone_name, "camera_id": camera_id}
    )
    db.add(audit)
    db.commit()

    try:
        from backend.main import manager
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast({
                "type": "ZONES_UPDATE",
                "action": "DELETE",
                "zone_id": zone_id,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }))
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Zone '{zone_name}' permanently deleted from database."
    }
