"""
IBVAP ANPR Router
=================
Full REST API for the Automatic Number Plate Recognition system.

Endpoints:
  GET  /api/anpr                 — Paginated, filtered list of ANPR detections
  GET  /api/anpr/{id}            — Single ANPR detection record
  GET  /api/anpr/snapshots/{filename} — Serve ANPR evidence snapshot image
  GET  /api/anpr/watchlist       — List plate watchlist entries
  POST /api/anpr/watchlist       — Add plate to watchlist
  PUT  /api/anpr/watchlist/{id}  — Enable/disable watchlist entry
  DELETE /api/anpr/watchlist/{id} — Remove from watchlist
"""

import os
import logging
from typing import Optional, List
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from database.connection import get_db
from database.schema import ANPRResult, ANPRWatchlist, Camera, AuditLog
from backend.auth import get_current_user, RequireRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/anpr", tags=["ANPR"])

ANPR_SNAPSHOT_DIR = "storage/evidence/anpr/snapshots"


# ─── Request/Response Models ──────────────────────────────────────────────────

class ANPRWatchlistCreate(BaseModel):
    plate_number: str = Field(..., min_length=4, max_length=30, description="Plate number to watchlist (uppercase)")
    vehicle_type: Optional[str] = None
    reason: Optional[str] = None
    severity: str = Field("HIGH", description="HIGH or CRITICAL")
    notes: Optional[str] = None

class ANPRWatchlistUpdate(BaseModel):
    is_active: Optional[bool] = None
    reason: Optional[str] = None
    severity: Optional[str] = None
    notes: Optional[str] = None


def _anpr_to_dict(rec: ANPRResult) -> dict:
    """Serialize ANPRResult ORM record to response dict."""
    return {
        "id": rec.id,
        "camera_id": rec.camera_id,
        "plate_number": rec.plate_number,
        "vehicle_type": rec.vehicle_type or "UNKNOWN",
        "vehicle_track_id": rec.vehicle_track_id,
        "camera_name": rec.camera_name,
        "camera_location": rec.camera_location,
        "detection_confidence": rec.detection_confidence,
        "ocr_confidence": rec.ocr_confidence,
        "plate_bbox": rec.plate_bbox,
        "vehicle_bbox": rec.vehicle_bbox,
        "snapshot_url": rec.snapshot_url,
        "crop_url": rec.crop_url,
        "status": rec.status or "CONFIRMED",
        "is_watchlist_match": rec.is_watchlist_match or False,
        "timestamp": rec.timestamp.isoformat() if rec.timestamp else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def _watchlist_to_dict(entry: ANPRWatchlist) -> dict:
    return {
        "id": entry.id,
        "plate_number": entry.plate_number,
        "vehicle_type": entry.vehicle_type,
        "reason": entry.reason,
        "severity": entry.severity,
        "is_active": entry.is_active,
        "notes": entry.notes,
        "added_by": entry.added_by,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


# ─── ANPR Detection Endpoints ─────────────────────────────────────────────────

@router.get("")
def get_anpr_records(
    plate_query: Optional[str] = Query(None, description="Search plate number (partial match)"),
    vehicle_type: Optional[str] = Query(None, description="Filter by vehicle type (car, truck, bus, ...)"),
    camera_id: Optional[str] = Query(None, description="Filter by camera DB ID or camera_id"),
    status: Optional[str] = Query(None, description="CONFIRMED, UNCERTAIN, WATCHLIST_MATCH"),
    watchlist_only: bool = Query(False, description="Show only watchlist matches"),
    date_from: Optional[str] = Query(None, description="From date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="To date YYYY-MM-DD"),
    min_ocr_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    sort: str = Query("newest", description="newest or oldest"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(ANPRResult)

    if plate_query:
        query = query.filter(ANPRResult.plate_number.ilike(f"%{plate_query.upper().strip()}%"))

    if vehicle_type and vehicle_type.lower() != "all":
        query = query.filter(ANPRResult.vehicle_type.ilike(f"%{vehicle_type.upper()}%"))

    if camera_id and camera_id != "all":
        # Support both Camera.id (UUID) and Camera.camera_id (e.g. CAM-01) lookups
        cam = db.query(Camera).filter(
            (Camera.camera_id == camera_id) | (Camera.id == camera_id)
        ).first()
        if cam:
            query = query.filter(ANPRResult.camera_id == cam.id)

    if status:
        query = query.filter(ANPRResult.status == status.upper())

    if watchlist_only:
        query = query.filter(ANPRResult.is_watchlist_match == True)

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(ANPRResult.timestamp >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(ANPRResult.timestamp <= dt_to)
        except ValueError:
            pass

    if min_ocr_confidence is not None:
        query = query.filter(ANPRResult.ocr_confidence >= min_ocr_confidence)

    order_col = desc(ANPRResult.timestamp) if sort == "newest" else asc(ANPRResult.timestamp)
    total = query.count()
    records = query.order_by(order_col).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": [_anpr_to_dict(r) for r in records],
    }


@router.get("/stats")
def get_anpr_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Quick stats for the ANPR header dashboard bar."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total_today = db.query(ANPRResult).filter(ANPRResult.timestamp >= today_start).count()
    confirmed_today = db.query(ANPRResult).filter(
        ANPRResult.timestamp >= today_start,
        ANPRResult.status == "CONFIRMED"
    ).count()
    watchlist_matches = db.query(ANPRResult).filter(
        ANPRResult.timestamp >= today_start,
        ANPRResult.is_watchlist_match == True
    ).count()
    total_all = db.query(ANPRResult).count()
    return {
        "total_today": total_today,
        "confirmed_today": confirmed_today,
        "watchlist_matches_today": watchlist_matches,
        "total_all_time": total_all,
    }


@router.get("/snapshots/{filename}")
def serve_anpr_snapshot(filename: str, current_user=Depends(get_current_user)):
    """Serve ANPR evidence snapshot images from storage/evidence/anpr/snapshots/."""
    # Security: strip path traversal
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(ANPR_SNAPSHOT_DIR, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"ANPR snapshot not found: {safe_filename}")
    return FileResponse(file_path, media_type="image/jpeg")


@router.get("/{anpr_id}")
def get_anpr_record(
    anpr_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rec = db.query(ANPRResult).filter(ANPRResult.id == anpr_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="ANPR record not found")
    return _anpr_to_dict(rec)


# ─── Plate Watchlist Endpoints ────────────────────────────────────────────────

@router.get("/watchlist/list")
def get_watchlist(
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(ANPRWatchlist)
    if active_only:
        query = query.filter(ANPRWatchlist.is_active == True)
    entries = query.order_by(desc(ANPRWatchlist.created_at)).all()
    return [_watchlist_to_dict(e) for e in entries]


@router.post("/watchlist", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def add_to_watchlist(
    payload: ANPRWatchlistCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    plate = payload.plate_number.upper().strip().replace(" ", "")
    if not plate:
        raise HTTPException(status_code=400, detail="plate_number cannot be empty")

    existing = db.query(ANPRWatchlist).filter(ANPRWatchlist.plate_number == plate).first()
    if existing:
        # Re-activate if previously disabled
        existing.is_active = True
        existing.reason = payload.reason or existing.reason
        existing.severity = payload.severity or existing.severity
        existing.notes = payload.notes or existing.notes
        db.commit()
        db.refresh(existing)
        logger.info(f"[ANPR WATCHLIST] Re-activated plate: {plate}")
        return _watchlist_to_dict(existing)

    import uuid
    entry = ANPRWatchlist(
        id=str(uuid.uuid4()),
        plate_number=plate,
        vehicle_type=payload.vehicle_type.upper() if payload.vehicle_type else None,
        reason=payload.reason,
        severity=payload.severity.upper() if payload.severity else "HIGH",
        is_active=True,
        notes=payload.notes,
        added_by=current_user.username,
        created_at=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(f"[ANPR WATCHLIST] Added plate: {plate} severity={entry.severity} by={current_user.username}")
    return _watchlist_to_dict(entry)


@router.put("/watchlist/{entry_id}", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def update_watchlist_entry(
    entry_id: str,
    payload: ANPRWatchlistUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    entry = db.query(ANPRWatchlist).filter(ANPRWatchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    if payload.is_active is not None:
        entry.is_active = payload.is_active
    if payload.reason is not None:
        entry.reason = payload.reason
    if payload.severity is not None:
        entry.severity = payload.severity.upper()
    if payload.notes is not None:
        entry.notes = payload.notes

    db.commit()
    db.refresh(entry)
    logger.info(f"[ANPR WATCHLIST] Updated entry {entry_id}: is_active={entry.is_active}")
    return _watchlist_to_dict(entry)


@router.delete("/watchlist/{entry_id}", dependencies=[Depends(RequireRole(["Administrator"]))])
def delete_watchlist_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    entry = db.query(ANPRWatchlist).filter(ANPRWatchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    plate = entry.plate_number

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_ANPR_WATCHLIST",
        resource="anpr_watchlist",
        details={"entry_id": entry_id, "plate_number": plate}
    )
    db.add(audit)
    db.delete(entry)
    db.commit()
    logger.info(f"[ANPR WATCHLIST] Deleted plate: {plate} by {current_user.username}")
    return {"status": "deleted", "plate_number": plate}


class BulkDeleteANPRRequest(BaseModel):
    result_ids: List[str]


@router.delete("/results/{result_id}")
@router.delete("/{result_id}")
def delete_anpr_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(RequireRole(["Administrator", "Security Operator"]))
):
    """
    Deletes a historical ANPRResult record and its associated snapshot file.
    Does NOT modify or delete ANPRWatchlist entries.
    """
    rec = db.query(ANPRResult).filter(ANPRResult.id == result_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="ANPR detection record not found.")

    plate = rec.plate_number
    cam_id = rec.camera_id
    vtype = rec.vehicle_type

    if rec.snapshot_url:
        fname = os.path.basename(rec.snapshot_url)
        local_path = os.path.join("storage/evidence/anpr/snapshots", fname)
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                logger.info(f"[ANPR CLEANUP] Deleted {local_path}")
            except Exception as e:
                logger.error(f"[ANPR CLEANUP] Error deleting {local_path}: {e}")

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_ANPR_RESULT",
        resource="anpr_results",
        details={
            "result_id": result_id,
            "plate_number": plate,
            "camera_id": cam_id,
            "vehicle_type": vtype
        }
    )
    db.add(audit)
    db.delete(rec)
    db.commit()
    return {"success": True, "message": "ANPR detection record deleted successfully.", "deleted_id": result_id}


@router.post("/results/bulk-delete", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def bulk_delete_anpr_results(
    payload: BulkDeleteANPRRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Permanently bulk-deletes multiple ANPR detection records from the database.
    """
    if not payload.result_ids:
        raise HTTPException(status_code=400, detail="No result IDs provided for deletion")

    if len(payload.result_ids) > 100:
        raise HTTPException(status_code=400, detail="Cannot delete more than 100 ANPR records at once")

    items = db.query(ANPRResult).filter(ANPRResult.id.in_(payload.result_ids)).all()
    if not items:
        return {"success": True, "deleted_count": 0, "deleted_ids": [], "message": "No matching ANPR records found"}

    deleted_ids = []
    for item in items:
        deleted_ids.append(item.id)
        if item.snapshot_url:
            fname = os.path.basename(item.snapshot_url)
            local_path = os.path.join("storage/evidence/anpr/snapshots", fname)
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass
        db.delete(item)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="BULK_DELETE_ANPR_RESULTS",
        resource="anpr_results",
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
        "message": f"Successfully deleted {len(deleted_ids)} ANPR detection records"
    }


