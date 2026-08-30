"""
IBVAP Evidence Router — AI Detection History & Evidence Gallery
Serves and manages real evidence snapshots captured by the AI surveillance pipeline.
Includes secure deletion with audit logging and physical file cleanup.
"""

import os
import logging
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database.connection import get_db
from database.schema import Evidence, Camera, AuditLog, User
from backend.auth import get_current_user, RequireRole
from ai_engine.detection.real_ai_detector import get_display_label, get_track_prefix, VEHICLE_CLASSES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evidence", tags=["AI Evidence & Detection History"])


class BulkDeleteEvidenceRequest(BaseModel):
    evidence_ids: List[str]


def _safe_remove_evidence_file(file_path: Optional[str]) -> bool:
    """
    Safely deletes an evidence snapshot file from disk.
    Verifies that the target path is strictly within the storage directory to prevent path traversal.
    """
    if not file_path:
        return False
    try:
        abs_target = os.path.abspath(file_path)
        abs_storage = os.path.abspath("storage")
        if not abs_target.startswith(abs_storage):
            logger.warning(f"[SECURITY] Refused deletion of path outside storage dir: {file_path}")
            return False
        if os.path.exists(abs_target) and os.path.isfile(abs_target):
            os.remove(abs_target)
            logger.info(f"[EVIDENCE CLEANUP] Successfully deleted snapshot file: {abs_target}")
            return True
    except Exception as e:
        logger.error(f"[EVIDENCE CLEANUP] Error deleting evidence file {file_path}: {e}")
    return False


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
    current_user: User = Depends(get_current_user),
):
    query = db.query(Evidence)
    if camera_id and camera_id != "all":
        query = query.filter(Evidence.camera_id == camera_id)

    order_clause = desc(Evidence.created_at) if sort == "newest" else Evidence.created_at
    items = query.order_by(order_clause).all()

    # Preload cameras to associate camera location, latitude, longitude
    all_cams = db.query(Camera).all()
    cam_map = {}
    for c in all_cams:
        cam_map[c.id] = c
        cam_map[c.camera_id] = c

    results = []
    for item in items:
        meta = item.metadata_json or {}
        cam_obj = cam_map.get(item.camera_id) or cam_map.get(meta.get("camera_number"))
        obj_cls = meta.get("object_class", "unknown").lower()
        display_label = meta.get("display_label") or get_display_label(obj_cls)
        prefix = get_track_prefix(obj_cls)
        ev_type = meta.get("event_type", "NORMAL DETECTION")
        sev = meta.get("severity", "INFO")
        cam_num = meta.get("camera_number") or (cam_obj.camera_id if cam_obj else item.camera_id)
        cam_name = meta.get("camera_name") or (cam_obj.name if cam_obj else None)
        location = meta.get("location") or (cam_obj.location if cam_obj else None)
        cam_lat = meta.get("latitude") if meta.get("latitude") is not None else (float(cam_obj.latitude) if cam_obj and cam_obj.latitude is not None else None)
        cam_lng = meta.get("longitude") if meta.get("longitude") is not None else (float(cam_obj.longitude) if cam_obj and cam_obj.longitude is not None else None)
        
        created_dt = item.created_at or datetime.utcnow()
        date_str = meta.get("date") or created_dt.strftime("%Y-%m-%d")
        time_str = meta.get("time") or created_dt.strftime("%H:%M:%S")
        raw_ts = meta.get("timestamp") or meta.get("captured_at") or created_dt.isoformat()
        timestamp_str = raw_ts if (isinstance(raw_ts, str) and (raw_ts.endswith("Z") or "+" in raw_ts)) else f"{raw_ts}Z"

        # Apply filters
        if object_class and object_class != "all":
            req_cls = object_class.lower()
            if req_cls in ["truck", "lorry"] and obj_cls not in ["truck", "lorry"]:
                continue
            elif req_cls == "vehicle" and obj_cls not in VEHICLE_CLASSES:
                continue
            elif req_cls not in ["truck", "lorry", "vehicle"] and obj_cls != req_cls:
                continue

        if event_type and event_type != "all":
            if event_type.upper() in ["NORMAL DETECTION", "DETECTION"]:
                if ev_type.upper() not in ["NORMAL DETECTION", "DETECTION"]:
                    continue
            elif ev_type.lower() != event_type.lower():
                continue

        if severity and severity != "all" and sev.lower() != severity.lower():
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
                "latitude": float(cam_lat) if cam_lat is not None else None,
                "longitude": float(cam_lng) if cam_lng is not None else None,
                "object_class": obj_cls,
                "display_label": display_label,
                "confidence": float(meta.get("confidence", 0.0)),
                "track_id": meta.get("track_id", "N/A"),
                "event_type": ev_type,
                "risk_score": float(meta.get("risk_score", 0.0)),
                "severity": sev,
                "date": date_str,
                "time": time_str,
                "timestamp": timestamp_str,
                "captured_at": timestamp_str,
                "bbox": meta.get("bbox", None),
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


@router.get("/{evidence_id}/image")
def get_evidence_image(evidence_id: str, db: Session = Depends(get_db)):
    """Serve the actual stored snapshot JPEG for a given evidence ID."""
    item = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    if not item.file_path or not os.path.exists(item.file_path):
        raise HTTPException(status_code=404, detail="Evidence image file not found on disk")

    return FileResponse(item.file_path, media_type="image/jpeg")


@router.get("/{evidence_id}")
def get_evidence_detail(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return full metadata for a single evidence record."""
    item = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    meta = item.metadata_json or {}
    cam = db.query(Camera).filter(Camera.id == item.camera_id).first()
    obj_cls = meta.get("object_class", "unknown").lower()
    prefix = get_track_prefix(obj_cls)

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
        "object_class": obj_cls,
        "display_label": meta.get("display_label") or get_display_label(obj_cls),
        "confidence": meta.get("confidence", 0.90),
        "track_id": meta.get("track_id", f"{prefix}-101"),
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


@router.delete("/{evidence_id}")
def delete_evidence(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RequireRole(["Administrator", "Security Operator"]))
):
    """
    Safely permanently deletes an evidence record and its associated snapshot file.
    Creates an audit log entry for security accountability.
    """
    item = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Evidence record #{evidence_id} not found")

    meta = item.metadata_json or {}
    file_path = item.file_path
    obj_class = meta.get("object_class", "unknown")
    track_id = meta.get("track_id", "O-101")
    cam_id = item.camera_id

    # 1. Clean up physical evidence snapshot on disk
    file_deleted = _safe_remove_evidence_file(file_path)

    # 2. Record audit log
    audit = AuditLog(
        user_id=current_user.id,
        username=current_user.username,
        action="DELETE_EVIDENCE",
        resource="evidence",
        details={
            "evidence_id": evidence_id,
            "object_class": obj_class,
            "display_label": meta.get("display_label"),
            "track_id": track_id,
            "camera_id": cam_id,
            "file_path": file_path,
            "file_deleted": file_deleted
        }
    )
    db.add(audit)

    # 3. Delete evidence record from database
    db.delete(item)
    db.commit()

    logger.info(f"[EVIDENCE] Deleted record {evidence_id} ({obj_class} | {track_id}) by user {current_user.username}")

    return {
        "success": True,
        "message": f"Detection evidence #{evidence_id[:8]} deleted successfully",
        "deleted_id": evidence_id,
        "file_deleted": file_deleted
    }


@router.post("/bulk-delete")
def bulk_delete_evidence(
    payload: BulkDeleteEvidenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RequireRole(["Administrator", "Security Operator"]))
):
    """
    Bulk deletes multiple evidence records and their snapshot files.
    """
    if not payload.evidence_ids:
        raise HTTPException(status_code=400, detail="No evidence IDs provided for deletion")

    if len(payload.evidence_ids) > 100:
        raise HTTPException(status_code=400, detail="Cannot delete more than 100 records at once")

    items = db.query(Evidence).filter(Evidence.id.in_(payload.evidence_ids)).all()
    if not items:
        return {"success": True, "deleted_count": 0, "deleted_ids": [], "message": "No matching records found"}

    deleted_ids = []
    files_deleted_count = 0

    for item in items:
        if _safe_remove_evidence_file(item.file_path):
            files_deleted_count += 1
        deleted_ids.append(item.id)
        db.delete(item)

    # Record single bulk audit log
    audit = AuditLog(
        user_id=current_user.id,
        username=current_user.username,
        action="BULK_DELETE_EVIDENCE",
        resource="evidence",
        details={
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids,
            "files_deleted_count": files_deleted_count
        }
    )
    db.add(audit)
    db.commit()

    logger.info(f"[EVIDENCE] Bulk deleted {len(deleted_ids)} records by user {current_user.username}")

    return {
        "success": True,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "message": f"Successfully deleted {len(deleted_ids)} detection records"
    }


# ---------------------------------------------------------------------------
# Alias /api/detections → /api/evidence  (keeps frontend compatibility)
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
    current_user: User = Depends(get_current_user),
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


@detections_router.delete("/{detection_id}")
def delete_detection_alias(
    detection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RequireRole(["Administrator", "Security Operator"]))
):
    return delete_evidence(detection_id, db=db, current_user=current_user)


@detections_router.post("/bulk-delete")
def bulk_delete_detections_alias(
    payload: BulkDeleteEvidenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RequireRole(["Administrator", "Security Operator"]))
):
    return bulk_delete_evidence(payload, db=db, current_user=current_user)
