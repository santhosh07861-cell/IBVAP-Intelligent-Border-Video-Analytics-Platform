"""
IBVAP Evidence Router — AI Detection History & Evidence Gallery
Serves real evidence snapshots captured by the AI surveillance pipeline.

Fixed:
  - `import os` moved to top (was at line 122, causing NameError in list_evidence)
  - limit/offset .default attribute error removed (values are plain ints now)
  - /api/evidence/{id}/image now serves the actual file correctly
  - Structured logging added throughout
"""

import os
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database.connection import get_db
from database.schema import Evidence, Camera
from backend.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evidence", tags=["AI Evidence & Detection History"])


@router.get("")
@router.get("/")
def list_evidence(
    camera_id: Optional[str] = None,
    object_class: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    sort: Optional[str] = Query("newest"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info(
        f"[EVIDENCE] API list_evidence called — camera_id={camera_id} "
        f"object_class={object_class} event_type={event_type} "
        f"severity={severity} search={search} sort={sort} limit={limit} offset={offset}"
    )

    query = db.query(Evidence)
    if camera_id and camera_id != "all":
        query = query.filter(Evidence.camera_id == camera_id)

    order_clause = desc(Evidence.created_at) if sort == "newest" else Evidence.created_at
    items = query.order_by(order_clause).all()
    logger.info(f"[EVIDENCE] Raw DB query returned {len(items)} records")

    results = []
    for item in items:
        meta = item.metadata_json or {}
        obj_cls = meta.get("object_class", "person").lower()
        display_label = meta.get("display_label") or ("TRUCK / LORRY" if obj_cls in ["truck", "lorry"] else obj_cls.upper())
        ev_type = meta.get("event_type", "NORMAL DETECTION")
        sev = meta.get("severity", "INFO")
        cam_num = meta.get("camera_number", item.camera_id)
        cam_name = meta.get("camera_name", "Border Outpost Camera")
        location = meta.get("location", "Sector 4 Border Outpost")

        # Apply filters
        if object_class and object_class != "all":
            req_cls = object_class.lower()
            if req_cls in ["truck", "lorry"] and obj_cls not in ["truck", "lorry"]:
                continue
            elif req_cls not in ["truck", "lorry"] and obj_cls != req_cls:
                continue

        if event_type and event_type != "all":
            if event_type.upper() in ["NORMAL DETECTION", "DETECTION"]:
                if ev_type.upper() not in ["NORMAL DETECTION", "DETECTION"]:
                    continue
            elif ev_type.lower() != event_type.lower():
                continue

        if severity and severity != "all" and sev.upper() != severity.upper():
            continue

        if search:
            s = search.lower()
            match = (
                s in str(cam_num).lower()
                or s in str(cam_name).lower()
                or s in str(location).lower()
                or s in str(obj_cls).lower()
                or s in str(display_label).lower()
                or s in str(ev_type).lower()
                or s in str(meta.get("track_id", "")).lower()
            )
            if not match:
                continue

        # Determine best image URL:
        if item.file_path and os.path.exists(item.file_path):
            img_url = f"/api/evidence/{item.id}/image"
        elif item.file_url:
            img_url = item.file_url
        else:
            img_url = None

        results.append(
            {
                "id": item.id,
                "incident_id": item.incident_id,
                "camera_id": item.camera_id,
                "camera_number": cam_num,
                "camera_name": cam_name,
                "location": location,
                "object_class": obj_cls,
                "display_label": display_label,
                "confidence": meta.get("confidence", 0.90),
                "track_id": meta.get("track_id", "P-101"),
                "event_type": ev_type,
                "risk_score": meta.get("risk_score", 0.0),
                "severity": sev,
                "captured_at": item.created_at.isoformat() if item.created_at else None,
                "bbox": meta.get("bbox", [0.2, 0.2, 0.4, 0.6]),
                "alert_id": meta.get("alert_id"),
                "event_id": meta.get("event_id"),
                "file_path": item.file_path,
                "file_url": img_url,
                "evidence_url": img_url,
            }
        )

    # Paginate
    total = len(results)
    limit_val = int(limit)
    offset_val = int(offset)
    paginated = results[offset_val: offset_val + limit_val]

    return {
        "total": total,
        "limit": limit_val,
        "offset": offset_val,
        "items": paginated,
    }


@router.get("/file/{year}/{month}/{day}/{camera_id}/{filename}")
def get_evidence_file_direct(
    year: str, month: str, day: str, camera_id: str, filename: str
):
    """Serves date-structured evidence snapshots directly."""
    full_path = os.path.join("storage", "evidence", "detections", year, month, day, camera_id, filename)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Evidence snapshot file not found")
    return FileResponse(full_path, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Alias /api/detections → /api/evidence  (keeps frontend routes working)
# ---------------------------------------------------------------------------
detections_router = APIRouter(
    prefix="/api/detections", tags=["AI Detection History Alias"]
)


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
    current_user=Depends(get_current_user),
):
    return list_evidence(
        camera_id=camera_id,
        object_class=object_class,
        event_type=event_type,
        severity=severity,
        search=search,
        limit=limit,
        offset=offset,
        db=db,
        current_user=current_user,
    )


# ---------------------------------------------------------------------------
# Individual evidence record detail
# ---------------------------------------------------------------------------
@router.get("/{evidence_id}/image")
def get_evidence_image(evidence_id: str, db: Session = Depends(get_db)):
    """Serve the actual stored snapshot JPEG for a given evidence ID."""
    item = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not item:
        logger.warning(f"[EVIDENCE] Image request for unknown ID: {evidence_id}")
        raise HTTPException(status_code=404, detail="Evidence record not found")

    if not item.file_path:
        logger.warning(f"[EVIDENCE] Evidence {evidence_id} has no file_path stored")
        raise HTTPException(status_code=404, detail="Evidence has no associated file path")

    if not os.path.exists(item.file_path):
        logger.warning(
            f"[EVIDENCE] File missing on disk for evidence {evidence_id}: {item.file_path}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"Evidence image file not found on disk: {item.file_path}",
        )

    logger.info(f"[EVIDENCE] Serving image for evidence {evidence_id}: {item.file_path}")
    return FileResponse(item.file_path, media_type="image/jpeg")


@router.get("/{evidence_id}")
def get_evidence_detail(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return full metadata for a single evidence record."""
    item = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    meta = item.metadata_json or {}
    cam = db.query(Camera).filter(Camera.id == item.camera_id).first()

    # Use the /image API endpoint so the browser gets the real binary
    if item.file_path and os.path.exists(item.file_path):
        image_api_url = f"/api/evidence/{item.id}/image"
    elif item.file_url:
        image_api_url = item.file_url
    else:
        image_api_url = None

    return {
        "id": item.id,
        "incident_id": item.incident_id,
        "camera_id": item.camera_id,
        "camera_number": meta.get(
            "camera_number", cam.camera_id if cam else item.camera_id
        ),
        "camera_name": meta.get(
            "camera_name", cam.name if cam else "Border Surveillance Camera"
        ),
        "location": meta.get(
            "location", cam.location if cam else "Sector 4 / Gate 2"
        ),
        "camera_status": cam.status if cam else "UNKNOWN",
        "object_class": meta.get("object_class", "person"),
        "confidence": meta.get("confidence", 0.90),
        "track_id": meta.get("track_id", "P-101"),
        "event_type": meta.get("event_type", "DETECTION"),
        "risk_score": meta.get("risk_score", 0.0),
        "severity": meta.get("severity", "INFO"),
        "captured_at": item.created_at.isoformat() if item.created_at else None,
        "bbox": meta.get("bbox", [0.2, 0.2, 0.4, 0.6]),
        "alert_id": meta.get("alert_id"),
        "event_id": meta.get("event_id"),
        "file_path": item.file_path,
        "file_url": image_api_url,
        "evidence_url": image_api_url,
    }
