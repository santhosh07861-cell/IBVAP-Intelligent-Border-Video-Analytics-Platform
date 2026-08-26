import uuid
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import CameraZone, ZoneRule, AuditLog
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/zones", tags=["Zones & Virtual Fences"])

class ZoneCreate(BaseModel):
    camera_id: str
    name: str
    zone_type: str = "RESTRICTED AREA"  # BOP PERIMETER, RESTRICTED AREA, NO ENTRY, BORDER FENCE, ROAD CROSSING, CUSTOM
    geometry_type: str = "polygon"
    coordinates: List[List[float]]

class RuleCreate(BaseModel):
    object_type: str = "person"
    direction: str = "ANY"
    min_confidence: float = 0.5
    loitering_threshold_sec: int = 10
    severity: str = "HIGH"

@router.get("", response_model=List[dict])
def list_zones(camera_id: Optional[str] = None, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    query = db.query(CameraZone)
    if camera_id:
        query = query.filter(CameraZone.camera_id == camera_id)
    zones = query.all()
    res = []
    for z in zones:
        rules = db.query(ZoneRule).filter(ZoneRule.zone_id == z.id).all()
        res.append({
            "id": z.id,
            "camera_id": z.camera_id,
            "name": z.name,
            "zone_type": z.zone_type,
            "geometry_type": z.geometry_type,
            "coordinates": z.coordinates,
            "is_active": z.is_active,
            "rules": [
                {
                    "id": r.id,
                    "object_type": r.object_type,
                    "direction": r.direction,
                    "min_confidence": r.min_confidence,
                    "loitering_threshold_sec": r.loitering_threshold_sec,
                    "severity": r.severity,
                    "enabled": r.enabled
                } for r in rules
            ]
        })
    return res

@router.post("", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def create_zone(payload: ZoneCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    zone = CameraZone(
        id=str(uuid.uuid4()),
        camera_id=payload.camera_id,
        name=payload.name,
        zone_type=payload.zone_type,
        geometry_type=payload.geometry_type,
        coordinates=payload.coordinates,
        is_active=True
    )
    db.add(zone)

    rule = ZoneRule(
        id=str(uuid.uuid4()),
        zone_id=zone.id,
        object_type="person",
        direction="ANY",
        min_confidence=0.5,
        loitering_threshold_sec=10,
        severity="HIGH",
        enabled=True
    )
    db.add(rule)

    db.commit()
    db.refresh(zone)

    audit = AuditLog(username=current_user.username, action="CREATE_VIRTUAL_FENCE_ZONE", resource="zones", details={"zone_name": payload.name})
    db.add(audit)
    db.commit()

    return {"status": "success", "zone_id": zone.id}
