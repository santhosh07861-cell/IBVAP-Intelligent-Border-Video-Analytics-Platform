"""
IBVAP Face Intelligence & Recognition Router
Supports real-time face detection logs, KPI analytics, watchlist enrollment,
embedding extraction, and image serving.
"""

import os
import uuid
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, List
import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database.connection import get_db
from database.schema import FaceDetection, FaceWatchlist, Camera, AuditLog
from backend.auth import get_current_user, RequireRole
from ai_engine.face.real_face_engine import RealFaceEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/faces", tags=["Face Detection & Recognition"])

# Singleton engine instance for watchlist embedding extraction
_face_engine = RealFaceEngine()

# Ensure directories exist
os.makedirs("storage/evidence/face/crops", exist_ok=True)
os.makedirs("storage/evidence/face/snapshots", exist_ok=True)
os.makedirs("storage/evidence/face/watchlist", exist_ok=True)

# ---------------------------------------------------------------------------
# Static Image Serving
# ---------------------------------------------------------------------------
@router.get("/crops/{filename}")
def get_face_crop(filename: str):
    file_path = os.path.join("storage/evidence/face/crops", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Face crop image not found")
    return FileResponse(file_path, media_type="image/jpeg")

@router.get("/snapshots/{filename}")
def get_face_snapshot(filename: str):
    file_path = os.path.join("storage/evidence/face/snapshots", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Face snapshot image not found")
    return FileResponse(file_path, media_type="image/jpeg")

@router.get("/watchlist/photo/{filename}")
def get_watchlist_photo(filename: str):
    file_path = os.path.join("storage/evidence/face/watchlist", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Watchlist photo not found")
    return FileResponse(file_path, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Face Detection Logs & History
# ---------------------------------------------------------------------------
@router.get("")
@router.get("/")
def get_face_detections(
    camera_id: Optional[str] = None,
    recognition_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = db.query(FaceDetection)

    if camera_id and camera_id != "all":
        query = query.filter(FaceDetection.camera_id == camera_id)

    if recognition_status and recognition_status != "all":
        query = query.filter(FaceDetection.recognition_status == recognition_status.upper())

    if search:
        s = f"%{search.lower()}%"
        query = query.filter(
            (func.lower(FaceDetection.identity_name).like(s)) |
            (func.lower(FaceDetection.recognition_status).like(s))
        )

    total = query.count()
    records = query.order_by(desc(FaceDetection.timestamp)).offset(offset).limit(limit).all()

    items = []
    for r in records:
        cam = db.query(Camera).filter(Camera.id == r.camera_id).first()
        cam_num = cam.camera_id if cam else r.camera_id
        cam_name = cam.name if cam else "Border Surveillance Camera"
        location = cam.location or "Sector 4 Border Outpost" if cam else "Sector 4 Border Outpost"

        wl_entry = db.query(FaceWatchlist).filter(FaceWatchlist.id == r.identity_id).first() if r.identity_id else None
        p_badge = wl_entry.person_id if wl_entry else (r.identity_id[:6].upper() if r.identity_id else None)
        p_cat = wl_entry.category if wl_entry else "WATCHLIST"

        items.append({
            "id": r.id,
            "camera_id": r.camera_id,
            "camera_number": cam_num,
            "camera_name": cam_name,
            "location": location,
            "track_id": r.track_id,
            "identity_id": r.identity_id,
            "identity_name": r.identity_name or "UNKNOWN",
            "person_id": p_badge,
            "category": p_cat,
            "recognition_status": r.recognition_status,
            "detection_confidence": r.detection_confidence,
            "recognition_confidence": r.recognition_confidence,
            "bbox": r.bbox,
            "landmarks": r.landmarks,
            "crop_url": r.crop_url,
            "snapshot_url": r.snapshot_url,
            "quality_score": r.quality_score,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items
    }


# ---------------------------------------------------------------------------
# Face KPI Summary (Strictly Current Runtime State)
# ---------------------------------------------------------------------------
@router.get("/kpis")
def get_face_kpis(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    from backend.stream_manager import stream_manager

    # Count live active faces across online camera stream workers
    active_faces_count = 0
    known_active = 0
    unknown_active = 0
    uncertain_active = 0

    for worker in stream_manager.workers.values():
        if worker.is_running and hasattr(worker, "latest_face_objs") and worker.latest_face_objs:
            for f in worker.latest_face_objs:
                active_faces_count += 1
                status = f.get("recognition_status", "UNKNOWN")
                if status == "KNOWN":
                    known_active += 1
                elif status == "UNCERTAIN":
                    uncertain_active += 1
                else:
                    unknown_active += 1

    total_watchlist = db.query(FaceWatchlist).filter(FaceWatchlist.is_active == True).count()
    monitored_cams = db.query(Camera).filter(Camera.status == "ONLINE").count()
    total_matches_db = db.query(FaceDetection).filter(FaceDetection.recognition_status == "KNOWN").count()
    total_24h_db = db.query(FaceDetection).filter(FaceDetection.timestamp >= datetime.utcnow() - timedelta(hours=24)).count()

    return {
        "active_faces": active_faces_count,
        "total_detections_24h": total_24h_db,
        "known_faces": known_active,
        "unknown_faces": unknown_active,
        "uncertain_faces": uncertain_active,
        "watchlist_matches": total_matches_db,
        "total_watchlist_enrolled": total_watchlist,
        "monitored_cameras": monitored_cams
    }


# ---------------------------------------------------------------------------
# Watchlist / Enrollment Endpoints
# ---------------------------------------------------------------------------
@router.get("/watchlist")
def list_watchlist(
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = db.query(FaceWatchlist)
    if category and category != "all":
        query = query.filter(FaceWatchlist.category == category.upper())
    if is_active is not None:
        query = query.filter(FaceWatchlist.is_active == is_active)
    if search:
        s = f"%{search.lower()}%"
        query = query.filter(
            (func.lower(FaceWatchlist.name).like(s)) |
            (func.lower(FaceWatchlist.person_id).like(s))
        )

    records = query.order_by(desc(FaceWatchlist.created_at)).all()
    results = []
    for r in records:
        results.append({
            "id": r.id,
            "name": r.name,
            "person_id": r.person_id,
            "category": r.category,
            "photo_url": r.photo_url,
            "is_active": r.is_active,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        })
    return results


@router.post("/watchlist")
async def enroll_person(
    name: str = Form(...),
    person_id: str = Form(...),
    category: str = Form("WATCHLIST"),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(RequireRole(["ADMIN", "ADMINISTRATOR", "SECURITY OPERATOR", "OPERATOR"]))
):
    """
    Enrolls a subject into the Face Watchlist:
    1. Validates face exists in image
    2. Ensures exactly 1 usable face is present
    3. Evaluates quality score
    4. Extracts 128-d SFace embedding
    5. Saves profile photo and records entry in database
    """
    # Check duplicate person_id
    existing = db.query(FaceWatchlist).filter(FaceWatchlist.person_id == person_id.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Person ID '{person_id}' is already registered to '{existing.name}'.")

    # Read image buffer
    img_bytes = None
    if file and hasattr(file, "read"):
        img_bytes = await file.read()
    elif image_base64:
        header_split = image_base64.split(",")
        raw_b64 = header_split[1] if len(header_split) > 1 else header_split[0]
        raw_b64 = raw_b64.strip().replace(" ", "+")
        missing_padding = len(raw_b64) % 4
        if missing_padding:
            raw_b64 += "=" * (4 - missing_padding)
        try:
            img_bytes = base64.b64decode(raw_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode base64 image: {str(e)}")

    if not img_bytes:
        raise HTTPException(status_code=400, detail="No face image provided. Please upload an image or capture via webcam.")

    # Decode image
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise HTTPException(status_code=400, detail="Invalid image file or unreadable format.")

    # Detect faces
    faces = _face_engine.detect_faces(img)
    if not faces:
        raise HTTPException(status_code=400, detail="No face detected in the uploaded image. Please ensure the subject's face is clearly visible and well-lit.")

    if len(faces) > 1:
        raise HTTPException(status_code=400, detail=f"Multiple faces ({len(faces)}) detected. Please provide an image containing only ONE individual for enrollment.")

    face = faces[0]
    if not face.is_high_quality and face.quality_score < 0.35:
        raise HTTPException(
            status_code=400,
            detail=f"Face image quality is too low (Score: {face.quality_score:.2f}). Reason: {face.quality_details.get('reason', 'poor clarity')}. Please provide a sharper, well-lit photo."
        )

    # Extract 128-d embedding
    embedding = _face_engine.extract_embedding(img, face)
    if embedding is None:
        raise HTTPException(status_code=500, detail="Failed to generate neural face feature embedding.")

    emb_list = embedding.flatten().tolist()

    # Save enrollment profile image
    enroll_id = str(uuid.uuid4())
    filename = f"watchlist_{person_id.strip()}_{enroll_id[:6]}.jpg"
    file_path = os.path.join("storage/evidence/face/watchlist", filename)
    cv2.imwrite(file_path, img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    photo_url = f"/api/faces/watchlist/photo/{filename}"

    watchlist_entry = FaceWatchlist(
        id=enroll_id,
        name=name.strip(),
        person_id=person_id.strip(),
        category=category.upper().strip(),
        photo_url=photo_url,
        embedding=emb_list,
        is_active=True,
        notes=notes,
        created_at=datetime.utcnow()
    )
    db.add(watchlist_entry)

    # Audit log
    audit = AuditLog(
        username=current_user.username if current_user else "admin",
        action="ENROLL_FACE_WATCHLIST",
        resource="face_watchlist",
        details={"person_id": person_id, "name": name, "category": category}
    )
    db.add(audit)
    db.commit()
    db.refresh(watchlist_entry)

    logger.info(f"[ENROLLMENT] Successfully enrolled: {name} ({person_id}) category={category}")

    return {
        "success": True,
        "message": f"Successfully enrolled {name} into Face Watchlist.",
        "entry": {
            "id": watchlist_entry.id,
            "name": watchlist_entry.name,
            "person_id": watchlist_entry.person_id,
            "category": watchlist_entry.category,
            "photo_url": watchlist_entry.photo_url,
            "is_active": watchlist_entry.is_active,
            "notes": watchlist_entry.notes,
            "quality_score": face.quality_score,
            "created_at": watchlist_entry.created_at.isoformat()
        }
    }


from pydantic import BaseModel

class WatchlistUpdatePayload(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None

@router.put("/watchlist/{entry_id}")
async def update_watchlist_entry(
    entry_id: str,
    payload: Optional[WatchlistUpdatePayload] = None,
    name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(RequireRole(["ADMIN", "ADMINISTRATOR", "SECURITY OPERATOR", "OPERATOR"]))
):
    entry = db.query(FaceWatchlist).filter(FaceWatchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found.")

    up_name = payload.name if payload and payload.name is not None else name
    up_cat = payload.category if payload and payload.category is not None else category
    up_active = payload.is_active if payload and payload.is_active is not None else is_active
    up_notes = payload.notes if payload and payload.notes is not None else notes

    if up_name is not None:
        entry.name = up_name.strip()
    if up_cat is not None:
        entry.category = up_cat.upper().strip()
    if up_active is not None:
        entry.is_active = bool(up_active)
    if up_notes is not None:
        entry.notes = up_notes

    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)

    # Audit log
    audit = AuditLog(
        username=current_user.username if current_user else "admin",
        action="UPDATE_FACE_WATCHLIST",
        resource="face_watchlist",
        details={"person_id": entry.person_id, "name": entry.name, "is_active": entry.is_active}
    )
    db.add(audit)
    db.commit()

    return {
        "success": True,
        "message": f"Watchlist entry for {entry.name} updated.",
        "entry": {
            "id": entry.id,
            "name": entry.name,
            "person_id": entry.person_id,
            "category": entry.category,
            "is_active": entry.is_active,
            "notes": entry.notes,
            "photo_url": entry.photo_url
        }
    }


@router.delete("/watchlist/{entry_id}")
def delete_watchlist_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(RequireRole(["Administrator", "Admin"]))
):
    entry = db.query(FaceWatchlist).filter(FaceWatchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found.")

    entry_name = entry.name
    p_id = entry.person_id

    # Remove photo if exists
    if entry.photo_url:
        fname = os.path.basename(entry.photo_url)
        local_path = os.path.join("storage/evidence/face/watchlist", fname)
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_FACE_WATCHLIST",
        resource="face_watchlist",
        details={"entry_id": entry_id, "name": entry_name, "person_id": p_id}
    )
    db.add(audit)
    db.delete(entry)
    db.commit()
    return {"success": True, "message": "Watchlist entry deleted."}


class BulkDeleteFaceRequest(BaseModel):
    detection_ids: List[str]


@router.delete("/detections/{detection_id}")
@router.delete("/{detection_id}")
def delete_face_detection(
    detection_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(RequireRole(["Administrator", "Security Operator"]))
):
    """
    Deletes a historical FaceDetection record and its associated crop/snapshot files.
    Does NOT modify or delete FaceWatchlist entries.
    """
    rec = db.query(FaceDetection).filter(FaceDetection.id == detection_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Face detection record not found.")

    # Safely clean up associated crop and snapshot files
    for url in [rec.crop_url, rec.snapshot_url]:
        if url:
            fname = os.path.basename(url)
            for sub in ["crops", "snapshots"]:
                p = os.path.join("storage/evidence/face", sub, fname)
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        logger.info(f"[FACE CLEANUP] Deleted {p}")
                    except Exception as e:
                        logger.error(f"[FACE CLEANUP] Error deleting {p}: {e}")

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_FACE_DETECTION",
        resource="face_detections",
        details={
            "detection_id": detection_id,
            "camera_id": rec.camera_id,
            "identity_name": rec.identity_name,
            "status": rec.recognition_status
        }
    )
    db.add(audit)
    db.delete(rec)
    db.commit()
    return {"success": True, "message": "Face detection record deleted successfully.", "deleted_id": detection_id}


@router.post("/detections/bulk-delete", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def bulk_delete_face_detections(
    payload: BulkDeleteFaceRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Permanently bulk-deletes multiple historical FaceDetection records and associated files.
    """
    if not payload.detection_ids:
        raise HTTPException(status_code=400, detail="No detection IDs provided for deletion")

    if len(payload.detection_ids) > 100:
        raise HTTPException(status_code=400, detail="Cannot delete more than 100 face records at once")

    items = db.query(FaceDetection).filter(FaceDetection.id.in_(payload.detection_ids)).all()
    if not items:
        return {"success": True, "deleted_count": 0, "deleted_ids": [], "message": "No matching face records found"}

    deleted_ids = []
    for item in items:
        deleted_ids.append(item.id)
        for url in [item.crop_url, item.snapshot_url]:
            if url:
                fname = os.path.basename(url)
                for sub in ["crops", "snapshots"]:
                    p = os.path.join("storage/evidence/face", sub, fname)
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
        db.delete(item)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="BULK_DELETE_FACE_DETECTIONS",
        resource="face_detections",
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
        "message": f"Successfully deleted {len(deleted_ids)} face detection records"
    }


