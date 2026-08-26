from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database.connection import get_db
from database.schema import Evidence, Camera
from backend.auth import get_current_user

router = APIRouter(prefix="/api/evidence", tags=["AI Evidence & Detection History"])

@router.get("")
@router.get("/")
def list_evidence(
    camera_id: Optional[str] = None,
    object_class: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Evidence)

    if camera_id:
        query = query.filter(Evidence.camera_id == camera_id)

    items = query.order_by(desc(Evidence.created_at)).all()
    results = []

    for item in items:
        meta = item.metadata_json or {}
        obj_cls = meta.get("object_class", "person")
        ev_type = meta.get("event_type", "INTRUSION")
        sev = meta.get("severity", "HIGH")
        cam_num = meta.get("camera_number", item.camera_id)
        cam_name = meta.get("camera_name", "Border Outpost Camera")
        location = meta.get("location", "Sector 4 / Gate 2")

        # Filters
        if object_class and object_class != "all" and obj_cls.lower() != object_class.lower():
            continue
        if event_type and event_type != "all" and ev_type.lower() != event_type.lower():
            continue
        if severity and severity != "all" and sev.upper() != severity.upper():
            continue
        if search:
            s = search.lower()
            match = (
                s in str(cam_num).lower() or
                s in str(cam_name).lower() or
                s in str(location).lower() or
                s in str(obj_cls).lower() or
                s in str(ev_type).lower() or
                s in str(meta.get("track_id", "")).lower()
            )
            if not match:
                continue

        results.append({
            "id": item.id,
            "incident_id": item.incident_id,
            "camera_id": item.camera_id,
            "camera_number": cam_num,
            "camera_name": cam_name,
            "location": location,
            "object_class": obj_cls,
            "confidence": meta.get("confidence", 0.90),
            "track_id": meta.get("track_id", "P-101"),
            "event_type": ev_type,
            "risk_score": meta.get("risk_score", 75.0),
            "severity": sev,
            "captured_at": item.created_at.isoformat(),
            "bbox": meta.get("bbox", [0.2, 0.2, 0.4, 0.6]),
            "alert_id": meta.get("alert_id"),
            "event_id": meta.get("event_id"),
            "file_path": item.file_path,
            "file_url": item.file_url,
            "evidence_url": item.file_url
        })

    limit_val = int(limit.default) if hasattr(limit, 'default') else int(limit)
    offset_val = int(offset.default) if hasattr(offset, 'default') else int(offset)

    total = len(results)
    paginated = results[offset_val : offset_val + limit_val]

    return {
        "total": total,
        "limit": limit_val,
        "offset": offset_val,
        "items": paginated
    }

# Alias /api/detections -> /api/evidence
detections_router = APIRouter(prefix="/api/detections", tags=["AI Detection History Alias"])

@detections_router.get("")
@detections_router.get("/")
def list_detections_alias(
    camera_id: Optional[str] = None,
    object_class: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return list_evidence(
        camera_id=camera_id, object_class=object_class, event_type=event_type,
        severity=severity, search=search, limit=limit, offset=offset,
        db=db, current_user=current_user
    )

@router.get("/{evidence_id}")
def get_evidence_detail(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    item = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    meta = item.metadata_json or {}
    cam = db.query(Camera).filter(Camera.id == item.camera_id).first()

    return {
        "id": item.id,
        "incident_id": item.incident_id,
        "camera_id": item.camera_id,
        "camera_number": meta.get("camera_number", cam.camera_id if cam else item.camera_id),
        "camera_name": meta.get("camera_name", cam.name if cam else "Border Surveillance Camera"),
        "location": meta.get("location", cam.location if cam else "Sector 4 / Gate 2"),
        "camera_status": cam.status if cam else "ONLINE",
        "object_class": meta.get("object_class", "person"),
        "confidence": meta.get("confidence", 0.90),
        "track_id": meta.get("track_id", "P-101"),
        "event_type": meta.get("event_type", "INTRUSION"),
        "risk_score": meta.get("risk_score", 75.0),
        "severity": meta.get("severity", "HIGH"),
        "captured_at": item.created_at.isoformat(),
        "bbox": meta.get("bbox", [0.2, 0.2, 0.4, 0.6]),
        "alert_id": meta.get("alert_id"),
        "event_id": meta.get("event_id"),
        "file_path": item.file_path,
        "file_url": item.file_url
    }
