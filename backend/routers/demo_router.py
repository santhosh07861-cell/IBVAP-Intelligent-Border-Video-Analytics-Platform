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

