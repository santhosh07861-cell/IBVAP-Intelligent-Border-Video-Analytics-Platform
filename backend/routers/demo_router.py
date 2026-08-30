import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import Camera, Event, Incident, Alert, Evidence, ANPRResult, FaceDetection, AuditLog
from backend.auth import get_current_user, RequireRole
from event_engine.correlation.correlator import EventCorrelator
from storage.evidence_manager import EvidenceManager

router = APIRouter(prefix="/api/demo", tags=["SIH Demo Engine"])

correlator = EventCorrelator()
evidence_mgr = EvidenceManager()

@router.post("/trigger-intrusion")
def trigger_demo_intrusion(
    camera_id: str = "CAM-01",
    is_night: bool = True,
    in_restricted_zone: bool = True,
    fence_crossed: bool = True,
    loitering: bool = True,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Triggers an end-to-end SIH Demo Workflow:
    Person detection -> Restricted zone intrusion -> Night condition -> Risk calculation (0-100) -> Alert -> Snapshot Evidence -> Incident Creation -> WebSockets.
    """
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        cam_id = "CAM-01"
    else:
        cam_id = cam.camera_id

    # Create dummy snapshot for evidence
    import numpy as np
    import cv2
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.putText(dummy_frame, "IBVAP SIH DEMO INTRUSION DETECTED", (100, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
    cv2.rectangle(dummy_frame, (300, 200), (600, 550), (0, 0, 255), 3)
    cv2.putText(dummy_frame, "PERSON [TRACK #104] 0.94", (300, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.polylines(dummy_frame, [np.array([[200, 150], [800, 150], [850, 600], [150, 600]], np.int32)], True, (255, 0, 0), 2)

    ev_path = evidence_mgr.save_snapshot(dummy_frame, cam_id)

    event_data = {
        "event_id": str(uuid.uuid4()),
        "camera_id": cam_id,
        "track_id": 104,
        "event_type": "INTRUSION",
        "confidence": 0.94,
        "conditions": {
            "night_mode": is_night,
            "restricted_zone": in_restricted_zone,
            "fence_crossing": fence_crossed,
            "loitering": loitering,
            "repeated_crossing": False
        }
    }

    incident = correlator.process_event(db, event_data, evidence_path=ev_path)

    # Also add an ANPR event for testing ANPR dashboard
    anpr = ANPRResult(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        plate_text="RJ19CB4821",
        plate_confidence=0.95,
        ocr_confidence=0.92,
        vehicle_type="car",
        timestamp=datetime.utcnow()
    )
    db.add(anpr)
    db.commit()

    return {
        "status": "success",
        "message": "SIH Demo Intrusion workflow triggered successfully!",
        "incident_id": incident.id if incident else None,
        "incident_number": incident.incident_number if incident else None,
        "risk_score": incident.risk_score if incident else 90.0,
        "severity": incident.severity if incident else "CRITICAL"
    }

@router.post("/upload-video")
async def upload_demo_video(
    file: UploadFile = File(...),
    camera_name: str = "Uploaded Demo Feed",
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Primary reliable SIH demo path: Upload custom MP4 video file.
    """
    os.makedirs("storage/uploads", exist_ok=True)
    file_path = f"storage/uploads/{uuid.uuid4().hex[:8]}_{file.filename}"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    cam_id = f"CAM-UP-{uuid.uuid4().hex[:4].upper()}"
    cam = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        name=camera_name,
        description=f"Uploaded MP4 video: {file.filename}",
        location="Sector 4 Border Outpost",
        stream_url=file_path,
        protocol="MP4",
        status="ONLINE",
        is_demo=True
    )
    db.add(cam)
    db.commit()

    return {
        "status": "success",
        "camera_id": cam_id,
        "file_path": file_path,
        "message": f"Demo MP4 video uploaded and attached to camera {cam_id}."
    }

from pydantic import BaseModel

class StreamStartRequest(BaseModel):
    camera_id: str = "CAM-01"
    source_type: str = "MP4"  # MP4, WEBCAM, RTSP
    source_path: str = "storage/demo_videos/border_patrol.mp4"
    fallback_mode: bool = False

@router.post("/start-stream")
def start_demo_stream(
    req: StreamStartRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    from backend.main import manager as ws_manager
    from backend.stream_manager import stream_manager

    # Ensure Camera exists in DB
    cam = db.query(Camera).filter(Camera.camera_id == req.camera_id).first()
    if not cam:
        cam = Camera(
            id=str(uuid.uuid4()),
            camera_id=req.camera_id,
            name=f"Demo Camera {req.camera_id}",
            description="Active Demo Stream Camera",
            location="Border Outpost Sector 4",
            stream_url=req.source_path,
            protocol=req.source_type,
            status="CONNECTING",
            is_demo=True
        )
        db.add(cam)
        db.commit()

    stream_manager.start_stream(
        camera_id=req.camera_id,
        source_type=req.source_type,
        source_path=req.source_path,
        websocket_manager=ws_manager
    )

    return {
        "status": "success",
        "message": f"Stream ingestion started for camera {req.camera_id}",
        "camera_id": req.camera_id,
        "source_type": req.source_type
    }

@router.post("/stop-stream")
def stop_demo_stream(
    camera_id: str = "CAM-01",
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    from backend.stream_manager import stream_manager
    stream_manager.stop_stream(camera_id)
    return {
        "status": "success",
        "message": f"Stream ingestion stopped for camera {camera_id}"
    }

@router.post("/trigger-watchlist-match")
async def trigger_demo_watchlist_match(
    camera_id: str = "CAM-01",
    person_name: str = "Madu",
    person_badge_id: str = "M89",
    similarity: float = 0.89,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Triggers an end-to-end Watchlist Match Security Workflow:
    Active Watchlist Person -> Facial Recognition Match (0.89) -> Critical Security Alert ->
    Real Frame Evidence Snapshot -> Database Event & Alert -> WebSocket Broadcast.
    """
    from database.schema import FaceWatchlist, FaceDetection
    from backend.main import manager as ws_manager
    import numpy as np
    import cv2

    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    cam_id = cam.id if cam else camera_id
    cam_num = cam.camera_id if cam else camera_id
    cam_name = cam.name if cam else "Border Outpost Primary Camera"
    cam_loc = cam.location or "Sector 4 Border Outpost" if cam else "Sector 4 Border Outpost"

    # Find or create active watchlist profile for demonstration
    wl_entry = db.query(FaceWatchlist).filter(FaceWatchlist.person_id == person_badge_id).first()
    if not wl_entry:
        wl_entry = db.query(FaceWatchlist).filter(FaceWatchlist.is_active == True).first()

    if not wl_entry:
        wl_entry = FaceWatchlist(
            id=str(uuid.uuid4()),
            name=person_name,
            person_id=person_badge_id,
            category="WATCHLIST",
            embedding=[0.05] * 128,
            is_active=True,
            notes="Demo enrolled watchlist subject",
            created_at=datetime.utcnow()
        )
        db.add(wl_entry)
        db.commit()
        db.refresh(wl_entry)

    matched_name = wl_entry.name
    matched_id = wl_entry.person_id
    category = wl_entry.category or "WATCHLIST"
    track_num = 104

    # Create real surveillance frame with annotated watchlist match overlay
    w, h = 1280, 720
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    # Background surveillance night gradient
    for y in range(h):
        val = int(12 + (y / h) * 20)
        frame[y, :] = [val, val + 5, val + 15]

    # Ground horizon
    cv2.line(frame, (0, int(h * 0.55)), (w, int(h * 0.55)), (40, 50, 70), 1)

    # Face box coordinates
    fx, fy, fw, fh = 480, 160, 280, 320
    x2, y2 = fx + fw, fy + fh

    now_dt = datetime.utcnow()

    # Top Tactical Bar
    cv2.rectangle(frame, (0, 0), (w, 48), (10, 10, 26), -1)
    cv2.rectangle(frame, (0, 46), (w, 48), (30, 30, 235), -1)
    cv2.putText(frame, f"🚨 DANGER — WATCHLIST PERSON DETECTED | {matched_name.upper()} | ID: {matched_id}", (20, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (50, 50, 255), 2)
    cv2.putText(frame, f"CAM: {cam_num} - {cam_name} | LOC: {cam_loc} | TIME: {now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')} | TRACK: #F{track_num}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 220), 1)

    # Face Box & Tactical Corners (Bright Red)
    box_color = (30, 30, 235)
    cv2.rectangle(frame, (fx, fy), (x2, y2), box_color, 2)
    corner_len = 25
    cv2.line(frame, (fx, fy), (fx + corner_len, fy), (255, 255, 255), 2)
    cv2.line(frame, (fx, fy), (fx, fy + corner_len), (255, 255, 255), 2)
    cv2.line(frame, (x2, fy), (x2 - corner_len, fy), (255, 255, 255), 2)
    cv2.line(frame, (x2, fy), (x2, fy + corner_len), (255, 255, 255), 2)
    cv2.line(frame, (fx, y2), (fx + corner_len, y2), (255, 255, 255), 2)
    cv2.line(frame, (fx, y2), (fx, y2 - corner_len), (255, 255, 255), 2)
    cv2.line(frame, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 2)
    cv2.line(frame, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 2)

    # 5 Face landmarks (Yellow)
    landmarks_abs = [
        (fx + int(fw * 0.32), fy + int(fh * 0.38)),
        (fx + int(fw * 0.68), fy + int(fh * 0.38)),
        (fx + int(fw * 0.50), fy + int(fh * 0.55)),
        (fx + int(fw * 0.35), fy + int(fh * 0.72)),
        (fx + int(fw * 0.65), fy + int(fh * 0.72))
    ]
    for lx, ly in landmarks_abs:
        cv2.circle(frame, (lx, ly), 4, (0, 255, 255), -1)

    # Match Label Banner
    status_tag = f"WATCHLIST MATCH: {matched_name.upper()} | ID: {matched_id} ({int(similarity * 100)}%)"
    (tw, th), _ = cv2.getTextSize(status_tag, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
    cv2.rectangle(frame, (fx, max(52, fy - 26)), (fx + tw + 12, max(52, fy)), box_color, -1)
    cv2.putText(frame, status_tag, (fx + 6, max(68, fy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)

    # Bottom Security Level Bar
    cv2.rectangle(frame, (0, h - 32), (w, h), (10, 10, 26), -1)
    sec_footer = f"SEVERITY: CRITICAL (RISK 95/100) | MATCH SIMILARITY: {similarity:.2f} | STATUS: VERIFIED SECURITY WATCHLIST MATCH"
    cv2.putText(frame, sec_footer, (20, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (30, 30, 235), 2)

    # Save real snapshot to storage
    os.makedirs("storage/evidence/face/snapshots", exist_ok=True)
    clean_cam = cam_num.replace("-", "_")
    snap_filename = f"{clean_cam}_F{track_num}_KNOWN_{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
    full_snap_path = os.path.join("storage/evidence/face/snapshots", snap_filename)
    cv2.imwrite(full_snap_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    snap_url = f"/api/faces/snapshots/{snap_filename}"
    file_size = os.path.getsize(full_snap_path) if os.path.exists(full_snap_path) else 0

    # Save crop
    os.makedirs("storage/evidence/face/crops", exist_ok=True)
    crop_img = frame[fy:y2, fx:x2]
    crop_filename = f"crop_{clean_cam}_F{track_num}_{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
    full_crop_path = os.path.join("storage/evidence/face/crops", crop_filename)
    cv2.imwrite(full_crop_path, crop_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    crop_url = f"/api/faces/crops/{crop_filename}"

    bbox_norm = [round(fx / w, 4), round(fy / h, 4), round(fw / w, 4), round(fh / h, 4)]
    landmarks_norm = [[round(lx / w, 4), round(ly / h, 4)] for lx, ly in landmarks_abs]

    # Database records
    face_rec = FaceDetection(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        track_id=track_num,
        identity_id=wl_entry.id,
        identity_name=matched_name,
        recognition_status="KNOWN",
        detection_confidence=0.96,
        recognition_confidence=similarity,
        bbox=bbox_norm,
        landmarks=landmarks_norm,
        crop_url=crop_url,
        snapshot_url=snap_url,
        quality_score=0.92,
        timestamp=now_dt
    )
    db.add(face_rec)

    ev_wl = Event(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        event_type="FACE_WATCHLIST_MATCH",
        severity="CRITICAL",
        risk_score=95.0,
        confidence=similarity,
        details={
            "person_name": matched_name,
            "person_id": matched_id,
            "category": category,
            "track_id": f"F-{track_num}",
            "similarity_score": similarity,
            "camera_name": cam_name,
            "camera_location": cam_loc,
            "status": "VERIFIED_WATCHLIST_MATCH"
        },
        timestamp=now_dt,
        track_id=track_num
    )
    db.add(ev_wl)

    al_wl = Alert(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        event_type="FACE_WATCHLIST_MATCH",
        severity="CRITICAL",
        risk_score=95.0,
        confidence=similarity,
        status="NEW",
        evidence_url=snap_url,
        timestamp=now_dt
    )
    db.add(al_wl)

    cam_lat = float(cam.latitude) if cam and cam.latitude is not None else 26.9124
    cam_lng = float(cam.longitude) if cam and cam.longitude is not None else 70.9025
    date_str = now_dt.strftime("%Y-%m-%d")
    time_str = now_dt.strftime("%H:%M:%S")
    ts_str = now_dt.isoformat()

    ev_evidence = Evidence(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        evidence_type="snapshot",
        file_path=full_snap_path,
        file_url=snap_url,
        file_size_bytes=file_size,
        metadata_json={
            "object_class": "person",
            "display_label": f"WATCHLIST: {matched_name.upper()}",
            "event_type": "FACE_WATCHLIST_MATCH",
            "severity": "CRITICAL",
            "risk_score": 95.0,
            "confidence": similarity,
            "track_id": f"F-{track_num}",
            "person_name": matched_name,
            "person_id": matched_id,
            "category": category,
            "camera_number": cam_num,
            "camera_name": cam_name,
            "location": cam_loc,
            "latitude": cam_lat,
            "longitude": cam_lng,
            "date": date_str,
            "time": time_str,
            "timestamp": ts_str,
            "captured_at": ts_str,
        },
        created_at=now_dt
    )
    db.add(ev_evidence)
    db.commit()

    # WebSockets Broadcasts
    await ws_manager.broadcast({
        "type": "ALERT_NEW",
        "alert_id": al_wl.id,
        "event_id": ev_wl.id,
        "camera_id": cam_id,
        "camera_number": cam_num,
        "camera_name": cam_name,
        "location": cam_loc,
        "object_class": "person",
        "track_id": f"F-{track_num}",
        "confidence": similarity,
        "event_type": "FACE_WATCHLIST_MATCH",
        "alert_title": "🚨 DANGER — WATCHLIST PERSON DETECTED",
        "person_name": matched_name,
        "person_id": matched_id,
        "category": category,
        "similarity": similarity,
        "risk_score": 95.0,
        "severity": "CRITICAL",
        "timestamp": now_dt.isoformat(),
        "evidence_url": snap_url,
        "alert": {
            "id": al_wl.id,
            "camera_id": cam_id,
            "camera_number": cam_num,
            "camera_name": cam_name,
            "location": cam_loc,
            "object_class": "person",
            "track_id": f"F-{track_num}",
            "confidence": similarity,
            "event_type": "FACE_WATCHLIST_MATCH",
            "alert_title": "🚨 DANGER — WATCHLIST PERSON DETECTED",
            "person_name": matched_name,
            "person_id": matched_id,
            "severity": "CRITICAL",
            "risk_score": 95.0,
            "evidence_url": snap_url,
            "timestamp": now_dt.isoformat()
        }
    })

    await ws_manager.broadcast({
        "type": "FACE_WATCHLIST_MATCH",
        "alert_id": al_wl.id,
        "event_id": ev_wl.id,
        "camera_id": cam_id,
        "camera_number": cam_num,
        "camera_name": cam_name,
        "location": cam_loc,
        "person_name": matched_name,
        "person_id": matched_id,
        "category": category,
        "track_id": f"F-{track_num}",
        "similarity": similarity,
        "severity": "CRITICAL",
        "risk_score": 95.0,
        "evidence_url": snap_url,
        "snapshot_url": snap_url,
        "crop_url": crop_url,
        "timestamp": now_dt.isoformat()
    })

    await ws_manager.broadcast({
        "type": "FACE_DETECTION_UPDATE",
        "face_id": face_rec.id,
        "camera_id": cam_id,
        "camera_number": cam_num,
        "camera_name": cam_name,
        "location": cam_loc,
        "track_id": track_num,
        "bbox": bbox_norm,
        "identity_id": wl_entry.id,
        "identity_name": matched_name,
        "person_id": matched_id,
        "category": category,
        "recognition_status": "KNOWN",
        "detection_confidence": 0.96,
        "recognition_confidence": similarity,
        "crop_url": crop_url,
        "snapshot_url": snap_url,
        "quality_score": 0.92,
        "timestamp": now_dt.isoformat()
    })

    await ws_manager.broadcast({
        "type": "EVIDENCE_NEW",
        "evidence_id": ev_evidence.id,
        "camera_id": cam_id,
        "camera_number": cam_num,
        "camera_name": cam_name,
        "location": cam_loc,
        "object_class": "person",
        "display_label": f"WATCHLIST: {matched_name.upper()}",
        "track_id": f"F-{track_num}",
        "event_type": "FACE_WATCHLIST_MATCH",
        "severity": "CRITICAL",
        "confidence": similarity,
        "risk_score": 95.0,
        "file_url": snap_url,
        "timestamp": now_dt.isoformat()
    })

    return {
        "status": "success",
        "message": f"Verified Watchlist Match workflow triggered for {matched_name} ({matched_id})",
        "alert_id": al_wl.id,
        "event_id": ev_wl.id,
        "person_name": matched_name,
        "person_id": matched_id,
        "similarity": similarity,
        "camera_id": cam_num,
        "location": cam_loc,
        "severity": "CRITICAL",
        "risk_score": 95.0,
        "snapshot_url": snap_url,
        "crop_url": crop_url
    }

