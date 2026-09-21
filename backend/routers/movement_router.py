"""
IBVAP Watchlist Movement Tracking Router
Serves persistent chronological cross-camera movement chains for confirmed watchlist persons.
Source of truth is strictly the persistent database.
"""

import os
import logging
from typing import List, Optional, Tuple
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import (
    WatchlistMovementChain,
    WatchlistMovementEvent,
    FaceWatchlist,
    Camera,
    Evidence,
    FaceDetection
)
from backend.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/movement", tags=["Watchlist Movement Tracking"])


def _resolve_event_evidence_file(event: WatchlistMovementEvent, db: Session) -> Tuple[Optional[str], Optional[str]]:
    """
    Authoritatively locates the real physical evidence snapshot file on disk for a WatchlistMovementEvent.
    Checks:
    1. Direct Evidence DB record via event.evidence_id
    2. Physical snapshot / crop file from event.evidence_url or event.crop_url
    3. Associated real FaceDetection records for this person on this camera around this observation
    Returns (abs_or_rel_file_path, serving_url) if file physically exists on disk, else (None, None).
    """
    # 1. Check Evidence table if evidence_id is present
    if event.evidence_id:
        ev = db.query(Evidence).filter(Evidence.id == event.evidence_id).first()
        if ev and ev.file_path and os.path.exists(ev.file_path) and os.path.isfile(ev.file_path):
            return ev.file_path, f"/api/movement/events/{event.id}/evidence/image"

    # 2. Check event.evidence_url
    if event.evidence_url:
        candidates = []
        url = str(event.evidence_url).strip()
        if url.startswith("/api/faces/snapshots/"):
            filename = url.replace("/api/faces/snapshots/", "").strip()
            candidates.append(os.path.join("storage", "evidence", "face", "snapshots", filename))
        elif url.startswith("/api/faces/crops/"):
            filename = url.replace("/api/faces/crops/", "").strip()
            candidates.append(os.path.join("storage", "evidence", "face", "crops", filename))
        elif url.startswith("/static/"):
            rel = url.replace("/static/", "").strip()
            candidates.append(os.path.join("storage", "evidence", rel))
        elif url.startswith("/api/movement/events/"):
            # Internal reference, skip to candidate lookups
            pass
        else:
            candidates.append(url)
            candidates.append(os.path.join("storage", "evidence", "face", "snapshots", os.path.basename(url)))

        for c in candidates:
            if c and os.path.exists(c) and os.path.isfile(c):
                return c, f"/api/movement/events/{event.id}/evidence/image"

    # 3. Check event.crop_url
    if event.crop_url:
        candidates = []
        url = str(event.crop_url).strip()
        if url.startswith("/api/faces/crops/"):
            filename = url.replace("/api/faces/crops/", "").strip()
            candidates.append(os.path.join("storage", "evidence", "face", "crops", filename))
        else:
            candidates.append(url)
        for c in candidates:
            if c and os.path.exists(c) and os.path.isfile(c):
                return c, f"/api/movement/events/{event.id}/evidence/image"

    # 4. Fallback: Search real FaceDetection records for this person & camera
    if event.watchlist_person_id and (event.camera_id or event.camera_number):
        fds = db.query(FaceDetection).filter(
            FaceDetection.identity_id == event.watchlist_person_id,
            (FaceDetection.camera_id == event.camera_id) | (FaceDetection.camera_id == event.camera_number)
        ).order_by(FaceDetection.timestamp.desc()).all()

        for fd in fds:
            if fd.snapshot_url:
                fn = os.path.basename(fd.snapshot_url)
                p = os.path.join("storage", "evidence", "face", "snapshots", fn)
                if os.path.exists(p) and os.path.isfile(p):
                    event.evidence_url = fd.snapshot_url
                    if fd.crop_url:
                        event.crop_url = fd.crop_url
                    try:
                        db.commit()
                    except Exception:
                        pass
                    return p, f"/api/movement/events/{event.id}/evidence/image"

            if fd.crop_url:
                fn = os.path.basename(fd.crop_url)
                p = os.path.join("storage", "evidence", "face", "crops", fn)
                if os.path.exists(p) and os.path.isfile(p):
                    event.crop_url = fd.crop_url
                    try:
                        db.commit()
                    except Exception:
                        pass
                    return p, f"/api/movement/events/{event.id}/evidence/image"

    # Evidence genuinely unavailable on disk
    logger.warning(
        f"[WATCHLIST_EVIDENCE_NOT_AVAILABLE] event_id={event.id} person='{event.watchlist_person_name}' "
        f"cam={event.camera_number} evidence_id={event.evidence_id} evidence_url={event.evidence_url} "
        f"reason=File does not exist in storage"
    )
    return None, None


def _serialize_event(event: WatchlistMovementEvent, db: Optional[Session] = None) -> dict:
    cam_name = event.camera_name
    cam_loc = event.location or "LOCATION NOT CONFIGURED"
    cam_lat = event.latitude
    cam_lon = event.longitude

    has_real_evidence = False
    evidence_serving_url = None

    if db:
        cam = db.query(Camera).filter(
            (Camera.id == event.camera_id) | (Camera.camera_id == event.camera_number)
        ).first()
        if cam:
            if cam.name:
                cam_name = cam.name
            if cam.location:
                cam_loc = cam.location
            if cam.latitude is not None:
                cam_lat = cam.latitude
            if cam.longitude is not None:
                cam_lon = cam.longitude

        file_path, _ = _resolve_event_evidence_file(event, db)
        if file_path:
            has_real_evidence = True
            evidence_serving_url = f"/api/movement/events/{event.id}/evidence/image"
    else:
        has_real_evidence = bool(event.evidence_url or event.crop_url)
        evidence_serving_url = f"/api/movement/events/{event.id}/evidence/image" if has_real_evidence else None

    return {
        "id": event.id,
        "chain_id": event.chain_id,
        "sequence_number": event.sequence_number,
        "event_label": f"EVENT {event.sequence_number}",
        "watchlist_person_id": event.watchlist_person_id,
        "watchlist_person_name": event.watchlist_person_name,
        "camera_id": event.camera_id,
        "camera_number": event.camera_number,
        "camera_name": cam_name,
        "location": cam_loc,
        "latitude": cam_lat,
        "longitude": cam_lon,
        "first_seen_at": event.first_seen_at.isoformat() + "Z" if event.first_seen_at else None,
        "last_seen_at": event.last_seen_at.isoformat() + "Z" if event.last_seen_at else None,
        "timestamp": event.timestamp.isoformat() + "Z" if event.timestamp else None,
        "date": event.timestamp.strftime("%Y-%m-%d") if event.timestamp else "",
        "time": event.timestamp.strftime("%H:%M:%S") if event.timestamp else "",
        "confidence": event.confidence,
        "face_similarity": event.face_similarity,
        "track_id": event.track_id,
        "evidence_id": event.evidence_id,
        "evidence_url": evidence_serving_url if has_real_evidence else None,
        "crop_url": event.crop_url,
        "has_real_evidence": has_real_evidence,
        "created_at": event.created_at.isoformat() + "Z" if event.created_at else None
    }

def _serialize_chain(chain: WatchlistMovementChain, db: Session) -> dict:
    now = datetime.utcnow()
    sec_since_detect = (now - chain.last_detected_at).total_seconds() if chain.last_detected_at else 999999
    if sec_since_detect <= 120:
        dyn_status = "ACTIVE"
    elif chain.total_detections > 0:
        dyn_status = "LAST SEEN"
    else:
        dyn_status = "NO CURRENT DETECTION"

    photo_url = None
    wl = db.query(FaceWatchlist).filter(FaceWatchlist.id == chain.watchlist_person_id).first()
    if wl and wl.photo_url:
        photo_url = wl.photo_url

    raw_events = (
        db.query(WatchlistMovementEvent)
        .filter(WatchlistMovementEvent.chain_id == chain.id)
        .order_by(WatchlistMovementEvent.sequence_number.asc(), WatchlistMovementEvent.first_seen_at.asc())
        .all()
    )

    # Consolidate consecutive detections from the SAME camera into a single trajectory visit node
    consolidated_events: List[WatchlistMovementEvent] = []
    for ev in raw_events:
        if consolidated_events and (
            consolidated_events[-1].camera_id == ev.camera_id or
            consolidated_events[-1].camera_number == ev.camera_number
        ):
            prev = consolidated_events[-1]
            if ev.last_seen_at and (not prev.last_seen_at or ev.last_seen_at > prev.last_seen_at):
                prev.last_seen_at = ev.last_seen_at
            if ev.first_seen_at and (not prev.first_seen_at or ev.first_seen_at < prev.first_seen_at):
                prev.first_seen_at = ev.first_seen_at
            prev.confidence = max(prev.confidence or 0.0, ev.confidence or 0.0)
            prev.face_similarity = max(prev.face_similarity or 0.0, ev.face_similarity or 0.0)

            # Preserve real physical evidence from either event
            ev_file, _ = _resolve_event_evidence_file(ev, db)
            prev_file, _ = _resolve_event_evidence_file(prev, db)
            if ev_file and not prev_file:
                prev.evidence_url = ev.evidence_url
                prev.evidence_id = ev.evidence_id
                prev.crop_url = ev.crop_url
            elif not prev.evidence_url and ev.evidence_url:
                prev.evidence_url = ev.evidence_url
                prev.evidence_id = ev.evidence_id
            if ev.crop_url and not prev.crop_url:
                prev.crop_url = ev.crop_url
        else:
            consolidated_events.append(ev)

    serialized_events = []
    for idx, ev in enumerate(consolidated_events, start=1):
        s_ev = _serialize_event(ev, db)
        s_ev["sequence_number"] = idx
        s_ev["event_label"] = f"EVENT {idx}"
        serialized_events.append(s_ev)

    # Authoritative current/last camera from DB
    curr_cam_name = chain.current_camera_name
    curr_cam_loc = chain.current_location or "LOCATION NOT CONFIGURED"
    curr_lat = chain.current_latitude
    curr_lon = chain.current_longitude

    if chain.current_camera_id or chain.current_camera_number:
        curr_cam = db.query(Camera).filter(
            (Camera.id == chain.current_camera_id) | (Camera.camera_id == chain.current_camera_number)
        ).first()
        if curr_cam:
            if curr_cam.name:
                curr_cam_name = curr_cam.name
            if curr_cam.location:
                curr_cam_loc = curr_cam.location
            if curr_cam.latitude is not None:
                curr_lat = curr_cam.latitude
            if curr_cam.longitude is not None:
                curr_lon = curr_cam.longitude

    return {
        "id": chain.id,
        "watchlist_person_id": chain.watchlist_person_id,
        "person_name": chain.person_name,
        "person_id": chain.person_id,
        "category": chain.category,
        "status": dyn_status,
        "current_camera_id": chain.current_camera_id,
        "current_camera_number": chain.current_camera_number,
        "current_camera_name": curr_cam_name,
        "current_location": curr_cam_loc,
        "current_latitude": curr_lat,
        "current_longitude": curr_lon,
        "first_detected_at": chain.first_detected_at.isoformat() + "Z" if chain.first_detected_at else None,
        "last_detected_at": chain.last_detected_at.isoformat() + "Z" if chain.last_detected_at else None,
        "total_detections": chain.total_detections,
        "photo_url": photo_url,
        "events_count": len(serialized_events),
        "events": serialized_events
    }

@router.get("/chains")
def list_movement_chains(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = (
        db.query(WatchlistMovementChain)
        .join(FaceWatchlist, FaceWatchlist.id == WatchlistMovementChain.watchlist_person_id)
        .filter(FaceWatchlist.is_active == True)
        .order_by(WatchlistMovementChain.last_detected_at.desc())
    )
    chains = query.limit(limit).all()
    serialized = [_serialize_chain(c, db) for c in chains]
    if status_filter and status_filter.upper() != "ALL":
        target = status_filter.upper().replace("_", " ")
        serialized = [c for c in serialized if c["status"].upper().replace("_", " ") == target]
    return serialized

@router.get("/chains/{person_or_chain_id}")
def get_movement_chain(
    person_or_chain_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    chain = (
        db.query(WatchlistMovementChain)
        .join(FaceWatchlist, FaceWatchlist.id == WatchlistMovementChain.watchlist_person_id)
        .filter(
            FaceWatchlist.is_active == True,
            (WatchlistMovementChain.id == person_or_chain_id) |
            (WatchlistMovementChain.watchlist_person_id == person_or_chain_id) |
            (WatchlistMovementChain.person_id == person_or_chain_id)
        )
        .first()
    )

    if not chain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist movement chain not found"
        )

    return _serialize_chain(chain, db)

@router.delete("/chains")
def clear_all_movement_chains(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Purges all watchlist movement chains and their associated movement event nodes.
    Does not affect the registered watchlist persons or cameras.
    """
    chains = db.query(WatchlistMovementChain).all()
    count = len(chains)
    for chain in chains:
        db.delete(chain)
    db.commit()
    logger.info(f"[WATCHLIST_MOVEMENT] Cleared all movement chains (count={count}) by user {getattr(current_user, 'username', 'admin')}")
    return {"success": True, "message": f"Cleared {count} movement chains", "deleted_count": count}


@router.delete("/chains/{chain_id}")
def delete_movement_chain(
    chain_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    chain = db.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain_id).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Movement chain not found")
    person_name = chain.person_name
    db.delete(chain)
    db.commit()
    logger.info(f"[WATCHLIST_MOVEMENT] Deleted chain {chain_id} for person '{person_name}'")
    return {"success": True, "message": f"Movement chain for '{person_name}' deleted"}


@router.delete("/events/{event_id}")
def delete_movement_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Delete a specific observation event node from a watchlist movement chain.
    If it's the last event in the chain, removes the chain as well.
    """
    event = db.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Movement event not found")
    chain_id = event.chain_id
    db.delete(event)
    db.commit()

    remaining = (
        db.query(WatchlistMovementEvent)
        .filter(WatchlistMovementEvent.chain_id == chain_id)
        .order_by(WatchlistMovementEvent.first_seen_at.asc())
        .all()
    )
    if not remaining:
        chain = db.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain_id).first()
        if chain:
            db.delete(chain)
            db.commit()
    else:
        for idx, ev in enumerate(remaining, start=1):
            ev.sequence_number = idx
        chain = db.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain_id).first()
        if chain:
            last_ev = remaining[-1]
            chain.current_camera_id = last_ev.camera_id
            chain.current_camera_number = last_ev.camera_number
            chain.current_camera_name = last_ev.camera_name
            chain.current_location = last_ev.location
            chain.current_latitude = last_ev.latitude
            chain.current_longitude = last_ev.longitude
            chain.last_detected_at = last_ev.last_seen_at or last_ev.timestamp
        db.commit()

    return {"success": True, "message": "Movement event deleted"}


# ---------------------------------------------------------------------------
# Dedicated Event Real Evidence Endpoints
# ---------------------------------------------------------------------------
@router.get("/events/{event_id}/evidence")
def get_movement_event_evidence(
    event_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Retrieve validated real surveillance evidence metadata for a specific movement event.
    Verifies that the physical evidence file exists on disk.
    If missing, returns 404 with structured error detail.
    """
    event = db.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.id == event_id).first()
    if not event:
        logger.warning(f"[WATCHLIST_EVIDENCE] event_id={event_id} not found in database")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movement event record not found"
        )

    file_path, serving_url = _resolve_event_evidence_file(event, db)
    if not file_path or not os.path.exists(file_path):
        logger.warning(
            f"[WATCHLIST_EVIDENCE] event_id={event_id} person='{event.watchlist_person_name}' "
            f"camera={event.camera_number} evidence file not found on disk"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="EVIDENCE NOT AVAILABLE: Stored evidence snapshot file not found on disk"
        )

    cam_name = event.camera_name
    cam_loc = event.location or "LOCATION NOT CONFIGURED"
    cam = db.query(Camera).filter(
        (Camera.id == event.camera_id) | (Camera.camera_id == event.camera_number)
    ).first()
    if cam:
        if cam.name:
            cam_name = cam.name
        if cam.location:
            cam_loc = cam.location

    return {
        "exists": True,
        "evidence_id": event.evidence_id or f"EVID-{event.id[:8]}",
        "event_id": event.id,
        "chain_id": event.chain_id,
        "camera_id": event.camera_id,
        "camera_number": event.camera_number,
        "camera_name": cam_name,
        "location": cam_loc,
        "watchlist_person_id": event.watchlist_person_id,
        "watchlist_person_name": event.watchlist_person_name,
        "timestamp": event.timestamp.isoformat() + "Z" if event.timestamp else None,
        "first_seen_at": event.first_seen_at.isoformat() + "Z" if event.first_seen_at else None,
        "last_seen_at": event.last_seen_at.isoformat() + "Z" if event.last_seen_at else None,
        "face_similarity": float(event.face_similarity or event.confidence or 0.0),
        "confidence": float(event.confidence or 0.0),
        "image_url": f"/api/movement/events/{event.id}/evidence/image",
        "file_size_bytes": os.path.getsize(file_path),
        "media_type": "image/jpeg"
    }


@router.api_route("/events/{event_id}/evidence/image", methods=["GET", "HEAD"])
def get_movement_event_evidence_image(
    event_id: str,
    db: Session = Depends(get_db)
):
    """
    Securely serves the real physical evidence snapshot JPEG for a specific movement event.
    Verifies that the target path is strictly within storage directories.
    """
    event = db.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Movement event record not found")

    file_path, _ = _resolve_event_evidence_file(event, db)
    if not file_path or not os.path.exists(file_path):
        logger.warning(
            f"[WATCHLIST_EVIDENCE_IMAGE] event_id={event_id} person='{event.watchlist_person_name}' "
            f"file not found on disk: {file_path}"
        )
        raise HTTPException(
            status_code=404,
            detail="EVIDENCE NOT AVAILABLE: Snapshot file not found on disk"
        )

    # Security verification: ensure path is inside workspace storage
    abs_target = os.path.abspath(file_path)
    abs_storage = os.path.abspath("storage")
    if not abs_target.startswith(abs_storage):
        logger.warning(f"[SECURITY] Denied serving path outside storage: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(file_path, media_type="image/jpeg")

