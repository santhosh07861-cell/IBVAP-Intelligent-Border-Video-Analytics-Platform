import re
import time
import uuid
import cv2
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import Camera, CameraHealth, CameraZone, ZoneRule, AuditLog
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])

def mask_stream_url(url: str) -> str:
    if "rtsp://" in url and "@" in url:
        return re.sub(r":([^@]+)@", ":****@", url)
    return url

class CameraCreate(BaseModel):
    camera_id: str
    name: str
    description: Optional[str] = None
    location: str
    latitude: float = 26.9124
    longitude: float = 70.9025
    stream_url: str
    protocol: str = "MP4"  # RTSP, WEBCAM, MP4, ONVIF
    is_demo: bool = False

class CameraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    camera_id: str
    name: str
    description: Optional[str] = None
    location: Optional[str] = ""
    latitude: Optional[float] = 26.9124
    longitude: Optional[float] = 70.9025
    protocol: Optional[str] = "MP4"
    status: Optional[str] = "OFFLINE"
    fps: Optional[float] = 0.0
    resolution: Optional[str] = "1920x1080"
    analytics_enabled: Optional[bool] = True
    is_demo: Optional[bool] = False

class TestConnectionRequest(BaseModel):
    protocol: str  # WEBCAM, RTSP, MP4
    stream_url: str

@router.get("", response_model=List[CameraResponse])
def list_cameras(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cameras = db.query(Camera).all()
    return cameras

@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam

@router.post("", response_model=CameraResponse, dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def create_camera(payload: CameraCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    existing = db.query(Camera).filter(Camera.camera_id == payload.camera_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Camera ID already exists")

    stream_url = payload.stream_url.strip()
    if stream_url.startswith("htpp://"): stream_url = "http://" + stream_url[7:]
    elif stream_url.startswith("htp://"): stream_url = "http://" + stream_url[6:]
    if (stream_url.startswith("http://") or stream_url.startswith("https://")) and not any(stream_url.endswith(x) for x in ["/video", "/shot.jpg", ".mp4", "/mjpeg"]):
        stream_url = stream_url.rstrip("/") + "/video"

    cam = Camera(
        id=str(uuid.uuid4()),
        camera_id=payload.camera_id,
        name=payload.name,
        description=payload.description,
        location=payload.location,
        latitude=payload.latitude,
        longitude=payload.longitude,
        stream_url=stream_url,
        protocol=payload.protocol.upper(),
        status="OFFLINE",
        is_demo=payload.is_demo
    )
    db.add(cam)

    health = CameraHealth(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        status="OFFLINE",
        fps=0.0,
        latency_ms=0.0,
        processing_status="IDLE"
    )
    db.add(health)

    # Automatically create default Virtual Fence Zone & Intrusion Rule
    zone = CameraZone(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        name=f"Perimeter Fence - {cam.name}",
        zone_type="RESTRICTED AREA",
        geometry_type="polygon",
        coordinates=[[0.15, 0.25], [0.85, 0.25], [0.92, 0.82], [0.08, 0.82]],
        is_active=True
    )
    db.add(zone)

    rule = ZoneRule(
        id=str(uuid.uuid4()),
        zone_id=zone.id,
        object_type="all",
        direction="ANY",
        min_confidence=0.3,
        loitering_threshold_sec=2,
        severity="HIGH",
        cooldown_sec=5,
        enabled=True
    )
    db.add(rule)

    db.commit()
    db.refresh(cam)

    audit = AuditLog(username=current_user.username, action="CREATE_CAMERA", resource="cameras", details={"camera_id": payload.camera_id})
    db.add(audit)
    db.commit()

    return cam

@router.post("/test-connection", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def test_connection(payload: TestConnectionRequest, current_user = Depends(get_current_user)):
    """
    Tests connection to a video source (RTSP, Webcam, or MP4) using OpenCV.
    Masks credentials in RTSP URLs. Automatically handles IP Webcam stream URLs.
    """
    url = payload.stream_url.strip()
    if (url.startswith("http://") or url.startswith("https://")) and not any(url.endswith(x) for x in ["/video", "/shot.jpg", ".mp4", "/mjpeg"]):
        url = url.rstrip("/") + "/video"

    masked_url = mask_stream_url(url)
    proto = payload.protocol.upper()
    start_t = time.time()

    # Fast TCP pre-check to avoid OpenCV ffmpeg blocking on unreachable IPs
    if url.startswith("http://") or url.startswith("https://") or url.startswith("rtsp://"):
        try:
            import socket, urllib.parse
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else 554)
            if host:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                res = s.connect_ex((host, port))
                s.close()
                if res != 0:
                    return {
                        "status": "FAILED",
                        "protocol": proto,
                        "stream_url": masked_url,
                        "latency_ms": 0.0,
                        "message": f"Could not reach IP {host}:{port}. Ensure phone/camera is on the same Wi-Fi and IP Webcam server is running."
                    }
        except Exception:
            pass

    try:
        if proto == "WEBCAM":
            dev_idx = int(url) if str(url).isdigit() else 0
            cap = cv2.VideoCapture(dev_idx)
        elif proto == "RTSP" or url.startswith("http://") or url.startswith("https://"):
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(url)

        if not cap.isOpened():
            return {
                "status": "FAILED",
                "protocol": proto,
                "stream_url": masked_url,
                "latency_ms": 0.0,
                "message": f"Could not open {proto} stream source at {masked_url}."
            }

        ret, frame = cap.read()
        latency = round((time.time() - start_t) * 1000, 1)
        cap.release()

        if ret and frame is not None:
            return {
                "status": "SUCCESS",
                "protocol": proto,
                "stream_url": masked_url,
                "latency_ms": latency,
                "message": f"Successfully connected to {proto} stream source. Frame resolution: {frame.shape[1]}x{frame.shape[0]}."
            }
        else:
            return {
                "status": "FAILED",
                "protocol": proto,
                "stream_url": masked_url,
                "latency_ms": latency,
                "message": f"Connected to {proto} source but failed to receive video frames."
            }
    except Exception as e:
        return {
            "status": "FAILED",
            "protocol": proto,
            "stream_url": masked_url,
            "latency_ms": 0.0,
            "message": f"Error testing connection: {str(e)}"
        }

@router.post("/{camera_id}/start", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def start_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    from backend.main import manager as ws_manager
    from backend.stream_manager import stream_manager

    # Fast TCP pre-check for RTSP/HTTP stream sources (supports IPv4 & IPv6)
    url = cam.stream_url.strip()
    if url.startswith("http://") or url.startswith("https://") or url.startswith("rtsp://"):
        try:
            import socket, urllib.parse
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else 554)
            if host:
                af = socket.AF_INET6 if ":" in host else socket.AF_INET
                s = socket.socket(af, socket.SOCK_STREAM)
                s.settimeout(1.5)
                res = s.connect_ex((host, port))
                s.close()
                if res != 0:
                    cam.status = "ERROR"
                    if cam.health: cam.health.status = "ERROR"
                    db.commit()
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot connect to {host}:{port}. Ensure your Mac and Phone are on the SAME Wi-Fi network."
                    )
        except HTTPException:
            raise
        except Exception:
            pass

    # Force reset stream worker if existing worker is stopped or in error state
    stream_manager.stop_stream(cam.camera_id)

    cam.status = "CONNECTING"
    if cam.health:
        cam.health.status = "CONNECTING"
    db.commit()

    stream_manager.start_stream(
        camera_id=cam.camera_id,
        source_type=cam.protocol,
        source_path=cam.stream_url,
        websocket_manager=ws_manager
    )

    return {
        "status": "success",
        "message": f"Camera stream {cam.camera_id} started.",
        "camera_id": cam.camera_id
    }

@router.post("/{camera_id}/stop", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def stop_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    from backend.stream_manager import stream_manager
    stream_manager.stop_stream(cam.camera_id)

    cam.status = "STOPPED"
    cam.fps = 0.0
    if cam.health:
        cam.health.status = "STOPPED"
        cam.health.fps = 0.0
        cam.health.latency_ms = 0.0
        cam.health.processing_status = "IDLE"
    db.commit()

    return {
        "status": "success",
        "message": f"Camera stream {cam.camera_id} stopped.",
        "camera_id": cam.camera_id
    }

@router.delete("/{camera_id}", dependencies=[Depends(RequireRole(["Administrator"]))])
def delete_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    from backend.stream_manager import stream_manager
    stream_manager.stop_stream(cam.camera_id)

    db.delete(cam)
    db.commit()

    return {"status": "success", "message": f"Camera {camera_id} deleted successfully."}

from fastapi.responses import StreamingResponse

@router.get("/{camera_id}/stream")
def get_camera_stream(camera_id: str):
    """
    Streams real-time MJPEG video frames from active StreamWorker for the specified camera.
    """
    from backend.stream_manager import stream_manager
    cid = camera_id

    def frame_generator():
        while True:
            worker = stream_manager.workers.get(cid)
            if worker and worker.is_running:
                jpeg_bytes = worker.get_latest_jpeg()
                if jpeg_bytes:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
            time.sleep(0.04)

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

