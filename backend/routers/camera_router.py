import re
import os
import time
import uuid
import asyncio
import cv2
import socket
import urllib.parse
import urllib.request
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

# Force FFmpeg C++ socket layer to fail fast if stream hangs
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;1500000|stimeout;1500000|rw_timeout;1500000"

from database.connection import get_db
from database.schema import Camera, CameraHealth, CameraZone, ZoneRule, AuditLog, Detection, Track, Event
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])

def get_local_server_ip() -> str:
    """Dynamically resolves the host's primary local IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def normalize_camera_url(url: str, protocol: str = "RTSP") -> tuple[str, str]:
    """
    Normalizes camera stream URL and resolves canonical source type ('http_mjpeg', 'rtsp', 'webcam', 'mp4').
    Preserves exact HTTP / MJPEG / RTSP endpoints without invalid cross-protocol conversions.
    """
    url = url.strip()
    proto = protocol.upper().strip()

    if url.startswith("htpp://"): url = "http://" + url[7:]
    elif url.startswith("htp://"): url = "http://" + url[6:]

    if proto == "WEBCAM" or url.isdigit():
        return (str(int(url) if url.isdigit() else 0), "webcam")

    if url.startswith("rtsp://") or url.startswith("rtsps://"):
        return (url, "rtsp")

    if url.startswith("http://") or url.startswith("https://"):
        # Auto-convert https:// to http:// for phone apps and local IP addresses
        if url.startswith("https://"):
            try:
                parsed_u = urllib.parse.urlparse(url)
                if parsed_u.port in [8080, 4747, 8081, 8000, 8554] or (parsed_u.hostname and (parsed_u.hostname.startswith("192.168.") or parsed_u.hostname.startswith("10.") or parsed_u.hostname.startswith("172."))):
                    url = "http://" + url[8:]
            except Exception:
                pass

        if not any(url.endswith(x) for x in ["/video", "/videofeed", "/mjpegfeed", "/mjpeg", "/shot.jpg", ".mp4", ".avi", ".mkv"]):
            url = url.rstrip("/") + "/video"
        return (url, "http_mjpeg")

    if proto == "RTSP":
        return (url, "rtsp")

    if url.endswith(".mp4") or url.endswith(".avi") or url.endswith(".mkv") or "/" in url or "\\" in url or proto == "MP4":
        return (url, "mp4")

    return (url, "http_mjpeg")

def diagnose_stream_connection_error(url: str, host: str, port: int, err_code: int = 0) -> str:
    local_ip = get_local_server_ip()
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    parts = []

    if err_code in [61, 111]:  # ECONNREFUSED
        parts.append(f"Connection refused: Port {port} is closed on {host}. Make sure the IP Webcam / DroidCam app is running and 'Start Server' is active on the phone.")
    elif err_code in [65, 113]:  # EHOSTUNREACH
        parts.append(f"No route to host ({host}). The phone is unreachable or on a different network. Make sure the phone is connected to the same Wi-Fi router (or phone's Mobile Hotspot).")
    elif err_code in [60, 110, 35]:  # ETIMEDOUT / EAGAIN
        parts.append(f"Connection timed out: Host {host}:{port} did not respond. Check that your phone screen is on and the IP Webcam server is running.")
    else:
        parts.append(f"Cannot connect to stream host {host}:{port} (socket error code: {err_code}).")

    if scheme == "https":
        parts.append("Note: Phone camera apps stream over 'http://', NOT 'https://'.")

    if local_ip and "." in local_ip and host and "." in host:
        local_sub = ".".join(local_ip.split(".")[:3])
        host_sub = ".".join(host.split(".")[:3])
        if local_sub != host_sub:
            parts.append(
                f"⚠️ Network Subnet Mismatch: Server is on subnet '{local_sub}.x' (IP: {local_ip}), "
                f"while phone is on '{host}'. Connect both devices to the same Wi-Fi router, or turn on your phone's Mobile Hotspot and connect this PC to it."
            )

    return " ".join(parts)

def validate_stream_url(url: str, protocol: str) -> tuple[bool, Optional[str]]:
    """
    Validates stream URL format.
    Returns (is_valid, error_message).
    """
    protocol = protocol.upper()
    url = url.strip()

    if protocol == "WEBCAM":
        if url.isdigit():
            return True, None
        return False, "Invalid camera URL. For WEBCAM, enter a valid device index (e.g. 0 or 1)."

    if protocol == "MP4":
        if url.endswith(".mp4") or url.endswith(".avi") or url.endswith(".mkv") or url.startswith("http") or "/" in url or "\\" in url:
            return True, None
        return False, "Invalid video path. MP4 source must be a valid video file path or URL."

    # Protocol is RTSP or HTTP IP camera
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("rtsp://")):
        return False, "Invalid camera URL. Enter the complete phone IP address (e.g. http://192.168.1.100:8080/video)."

    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        if not host:
            return False, "Invalid camera URL. Enter the complete phone IP address."

        # Check if host is an IPv4 address
        ip_parts = host.split(".")
        if len(ip_parts) == 4:
            for part in ip_parts:
                if not part.isdigit() or not (0 <= int(part) <= 255):
                    return False, "Invalid camera URL. Enter the complete phone IP address."
        else:
            if any(p == "" for p in ip_parts) or (len(ip_parts) in [2, 3] and all(p.isdigit() for p in ip_parts if p)):
                return False, "Invalid camera URL. Enter the complete phone IP address."

        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False, "Invalid camera URL. Port must be between 1 and 65535."

        return True, None
    except Exception:
        return False, "Invalid camera URL. Enter the complete phone IP address."

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
    role: Optional[str] = "secondary"  # primary, secondary
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
    role: Optional[str] = "secondary"
    status: Optional[str] = "OFFLINE"
    fps: Optional[float] = 0.0
    resolution: Optional[str] = "1920x1080"
    analytics_enabled: Optional[bool] = True
    is_demo: Optional[bool] = False

class TestConnectionRequest(BaseModel):
    protocol: str  # WEBCAM, RTSP, MP4, HTTP_MJPEG
    stream_url: str

class TestConnectionResponse(BaseModel):
    connected: bool
    status: str
    source_type: str
    url: str
    fps: float
    width: int
    height: int
    latency_ms: float
    error: Optional[str] = None
    message: str

@router.get("", response_model=List[CameraResponse])
async def list_cameras(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cameras = db.query(Camera).all()
    if cameras:
        has_primary = any(c.role == "primary" for c in cameras)
        if not has_primary:
            cameras[0].role = "primary"
            db.commit()
    return cameras

@router.get("/discover-phone-cams")
def discover_phone_cams(current_user = Depends(get_current_user)):
    """
    Scans the local subnet for active phone IP cameras (IP Webcam: 8080, DroidCam: 4747, RTSP: 8554/554).
    Validates responsiveness and returns true reachable video stream endpoints.
    """
    local_ip = get_local_server_ip()
    if not local_ip or local_ip == "127.0.0.1" or "." not in local_ip:
        return {"discovered": [], "local_ip": local_ip, "subnet": "local"}

    prefix = ".".join(local_ip.split(".")[:3]) + "."
    my_last_octet = int(local_ip.split(".")[3])
    found_streams = []

    def probe_host(last_octet: int):
        if last_octet == my_last_octet:
            return None
        ip = f"{prefix}{last_octet}"
        candidates = [
            (8080, "IP Webcam", "/video"),
            (4747, "DroidCam", "/video"),
            (8081, "IP Cam", "/video"),
            (8554, "RTSP Camera", "/live"),
            (554, "RTSP Stream", "/stream")
        ]
        for port, app_name, path in candidates:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            try:
                if s.connect_ex((ip, port)) == 0:
                    scheme = "rtsp" if port in [8554, 554] else "http"
                    stream_url = f"{scheme}://{ip}:{port}{path}"
                    return {
                        "ip": ip,
                        "port": port,
                        "app": app_name,
                        "stream_url": stream_url,
                        "label": f"{app_name} ({ip}:{port})"
                    }
            except Exception:
                pass
            finally:
                s.close()
        return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=60) as executor:
        results = executor.map(probe_host, range(1, 255))
        for r in results:
            if r:
                found_streams.append(r)

    return {
        "local_ip": local_ip,
        "subnet": f"{prefix}x",
        "discovered": found_streams
    }

@router.get("/network-info")
def get_network_info(current_user = Depends(get_current_user)):
    ip = get_local_server_ip()
    subnet = ".".join(ip.split(".")[:3]) + ".x" if "." in ip else "local"
    return {
        "server_ip": ip,
        "subnet": subnet,
        "sample_phone_url": f"http://{subnet.replace('.x', '.<phone_ip>')}:8080/video"
    }

@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam

@router.post("", response_model=CameraResponse, dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def create_camera(payload: CameraCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    normalized_url, resolved_type = normalize_camera_url(payload.stream_url, payload.protocol)

    # Validate stream URL format
    is_valid, validation_err = validate_stream_url(normalized_url, payload.protocol)
    if not is_valid:
        raise HTTPException(status_code=400, detail=validation_err or "Invalid camera URL. Enter the complete phone IP address.")

    existing = db.query(Camera).filter(Camera.camera_id == payload.camera_id).first()
    if existing:
        existing.name = payload.name
        existing.description = payload.description
        existing.location = payload.location
        existing.latitude = payload.latitude
        existing.longitude = payload.longitude
        existing.stream_url = normalized_url
        existing.protocol = payload.protocol.upper()
        existing.is_demo = payload.is_demo
        db.commit()
        db.refresh(existing)
        return existing

    cam = Camera(
        id=str(uuid.uuid4()),
        camera_id=payload.camera_id,
        name=payload.name,
        description=payload.description,
        location=payload.location,
        latitude=payload.latitude,
        longitude=payload.longitude,
        stream_url=normalized_url,
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
        loitering_threshold_sec=5,
        severity="HIGH",
        cooldown_sec=30,
        enabled=True
    )
    db.add(rule)

    db.commit()
    db.refresh(cam)

    audit = AuditLog(username=current_user.username, action="CREATE_CAMERA", resource="cameras", details={"camera_id": payload.camera_id})
    db.add(audit)
    db.commit()

    return cam

@router.post("/test-connection", response_model=TestConnectionResponse, dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def test_connection(payload: TestConnectionRequest, current_user = Depends(get_current_user)):
    """
    Tests real backend-side connection to a video source (HTTP MJPEG, RTSP, Webcam, MP4).
    Opens the stream, reads real frames, measures actual latency & FPS, and returns comprehensive diagnostic status.
    """
    normalized_url, source_type = normalize_camera_url(payload.stream_url, payload.protocol)
    masked_url = mask_stream_url(normalized_url)

    # Step 1: Format Validation
    is_valid, validation_err = validate_stream_url(normalized_url, payload.protocol)
    if not is_valid:
        err_str = validation_err or "Invalid camera URL. Enter the complete phone IP address."
        return {
            "connected": False,
            "status": "FAILED",
            "source_type": source_type,
            "url": masked_url,
            "fps": 0.0,
            "width": 0,
            "height": 0,
            "latency_ms": 0.0,
            "error": err_str,
            "message": err_str
        }

    start_t = time.time()

    # Step 2: TCP Reachability Pre-check for Network Streams (HTTP / RTSP)
    if normalized_url.startswith("http://") or normalized_url.startswith("https://") or normalized_url.startswith("rtsp://"):
        try:
            parsed = urllib.parse.urlparse(normalized_url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else 554)
            if host:
                af = socket.AF_INET6 if ":" in host else socket.AF_INET
                s = socket.socket(af, socket.SOCK_STREAM)
                s.settimeout(0.5)
                res = s.connect_ex((host, port))
                s.close()
                if res != 0:
                    err_msg = diagnose_stream_connection_error(normalized_url, host, port, err_code=res)
                    latency = round((time.time() - start_t) * 1000, 1)
                    return {
                        "connected": False,
                        "status": "FAILED",
                        "source_type": source_type,
                        "url": masked_url,
                        "fps": 0.0,
                        "width": 0,
                        "height": 0,
                        "latency_ms": latency,
                        "error": err_msg,
                        "message": err_msg
                    }
        except Exception as e:
            pass

    # Step 3: Real Video Frame Ingestion Test
    def _attempt_frame_read():
        from video_engine.ingestion.source import create_video_source
        temp_src = None
        try:
            temp_src = create_video_source("TEST_CONN", payload.protocol, normalized_url)
            # Read 2 frames to confirm stability
            ret1, f1 = temp_src.read_frame()
            if not ret1 or f1 is None:
                time.sleep(0.05)
                ret1, f1 = temp_src.read_frame()

            if ret1 and f1 is not None:
                h, w = f1.shape[:2]
                fps = getattr(temp_src, "fps", 25.0) or 25.0
                return True, w, h, fps, None
            else:
                return False, 0, 0, 0.0, "Connected to network host, but failed to receive video frames from stream."
        except Exception as ex:
            return False, 0, 0, 0.0, str(ex)
        finally:
            if temp_src:
                try:
                    temp_src.release()
                except Exception:
                    pass

    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            fut = executor.submit(_attempt_frame_read)
            ok, width, height, fps, read_err = fut.result(timeout=2.5)

        latency = round((time.time() - start_t) * 1000, 1)
        if ok and width > 0 and height > 0:
            return {
                "connected": True,
                "status": "SUCCESS",
                "source_type": source_type,
                "url": masked_url,
                "fps": float(fps),
                "width": int(width),
                "height": int(height),
                "latency_ms": latency,
                "error": None,
                "message": f"Successfully connected to {source_type} stream source. Resolution: {width}x{height} @ {fps:.1f} FPS (Latency: {latency}ms)."
            }
        else:
            err_msg = read_err or f"Failed to ingest frames from {masked_url}."
            return {
                "connected": False,
                "status": "FAILED",
                "source_type": source_type,
                "url": masked_url,
                "fps": 0.0,
                "width": 0,
                "height": 0,
                "latency_ms": latency,
                "error": err_msg,
                "message": err_msg
            }
    except Exception as e:
        latency = round((time.time() - start_t) * 1000, 1)
        err_msg = f"Stream connection timed out: {e}"
        return {
            "connected": False,
            "status": "FAILED",
            "source_type": source_type,
            "url": masked_url,
            "fps": 0.0,
            "width": 0,
            "height": 0,
            "latency_ms": latency,
            "error": err_msg,
            "message": err_msg
        }

@router.post("/{camera_id}/start", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def start_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    from backend.main import manager as ws_manager
    from backend.stream_manager import stream_manager

    # Fast TCP pre-check for RTSP/HTTP stream sources
    url = cam.stream_url.strip()
    if url.startswith("http://") or url.startswith("https://") or url.startswith("rtsp://"):
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else 554)
            if host:
                af = socket.AF_INET6 if ":" in host else socket.AF_INET
                s = socket.socket(af, socket.SOCK_STREAM)
                s.settimeout(0.5)
                res = s.connect_ex((host, port))
                s.close()
                if res != 0:
                    cam.status = "ERROR"
                    if cam.health: cam.health.status = "ERROR"
                    db.commit()
                    err_msg = diagnose_stream_connection_error(url, host, port, err_code=res)
                    raise HTTPException(
                        status_code=400,
                        detail=err_msg
                    )
        except HTTPException:
            raise
        except Exception:
            pass

    # Stop existing worker for this camera if any
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
    stream_manager.stop_stream(cam.id)

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

@router.post("/{camera_id}/set-primary", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def set_primary_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    target = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="Camera not found")

    db.query(Camera).update({Camera.role: "secondary"})
    target.role = "primary"
    db.commit()
    db.refresh(target)

    return {
        "status": "success",
        "message": f"Camera {target.camera_id} set as PRIMARY camera.",
        "camera_id": target.camera_id,
        "role": target.role
    }

@router.delete("/{camera_id}", dependencies=[Depends(RequireRole(["Administrator"]))])
def delete_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    from backend.stream_manager import stream_manager
    stream_manager.stop_stream(cam.camera_id)
    stream_manager.stop_stream(cam.id)

    cam_id = cam.id
    camera_code = cam.camera_id
    cam_name = cam.name
    cam_loc = cam.location

    # Expire cam from session to avoid conflict with raw SQL execution
    db.expunge(cam)

    from database.connection import engine
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("DELETE FROM zone_rules WHERE zone_id IN (SELECT id FROM camera_zones WHERE camera_id = :cid OR camera_id = :ccode)"), {"cid": cam_id, "ccode": camera_code})
        for tbl in ["camera_zones", "camera_health", "detections", "tracks", "face_detections", "behavior_events", "anpr_results", "evidence", "alerts", "incidents", "events"]:
            conn.execute(text(f"DELETE FROM {tbl} WHERE camera_id = :cid OR camera_id = :ccode"), {"cid": cam_id, "ccode": camera_code})
        conn.execute(text("DELETE FROM cameras WHERE id = :cid OR camera_id = :ccode"), {"cid": cam_id, "ccode": camera_code})
        conn.execute(text("PRAGMA foreign_keys = ON"))

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_CAMERA",
        resource="cameras",
        details={"camera_id": camera_code, "name": cam_name, "location": cam_loc}
    )
    db.add(audit)
    db.commit()

    return {"status": "success", "message": f"Camera {camera_id} deleted successfully."}

@router.post("/{camera_id}/subscribe")
def subscribe_camera(camera_id: str, client_id: Optional[str] = "ui_client"):
    from backend.main import manager as ws_manager
    from backend.stream_manager import stream_manager
    sub_id = f"{client_id}_{uuid.uuid4().hex[:4]}"
    stream_manager.subscribe(camera_id, sub_id, ws_manager)
    return {
        "status": "success",
        "camera_id": camera_id,
        "subscription_id": sub_id,
        "active_subscribers": stream_manager.get_subscriber_count(camera_id)
    }

@router.post("/{camera_id}/unsubscribe")
def unsubscribe_camera(camera_id: str, subscription_id: str):
    from backend.stream_manager import stream_manager
    stream_manager.unsubscribe(camera_id, subscription_id)
    return {
        "status": "success",
        "camera_id": camera_id,
        "subscription_id": subscription_id,
        "active_subscribers": stream_manager.get_subscriber_count(camera_id)
    }

@router.get("/{camera_id}/stream")
async def get_camera_stream(camera_id: str, db: Session = Depends(get_db)):
    """
    Streams real-time MJPEG video frames from active StreamWorker with automatic startup & subscription.
    """
    from backend.main import manager as ws_manager
    from backend.stream_manager import stream_manager

    # Resolve canonical camera ID
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    canonical_id = cam.camera_id if cam else camera_id
    sub_id = f"mjpeg_stream_{uuid.uuid4().hex[:6]}"

    # Automatically ensure stream worker is started if camera exists in DB and is not stopped
    if cam and cam.status != "STOPPED":
        stream_manager.start_stream(canonical_id, cam.protocol, cam.stream_url, ws_manager)

    stream_manager.subscribe(canonical_id, sub_id, ws_manager)

    async def frame_generator():
        try:
            while True:
                worker = stream_manager.get_worker(canonical_id)
                if worker and worker.is_running:
                    jpeg_bytes = worker.get_latest_jpeg()
                    if jpeg_bytes:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
                await asyncio.sleep(0.04)
        finally:
            stream_manager.unsubscribe(canonical_id, sub_id)

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")
