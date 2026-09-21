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
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status, Request, File, UploadFile
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
    # Strip enclosing single/double quotes (e.g. if user copied path from terminal or file manager)
    if (url.startswith("'") and url.endswith("'")) or (url.startswith('"') and url.endswith('"')):
        url = url[1:-1].strip()

    proto = protocol.upper().strip()

    if url.startswith("htpp://"): url = "http://" + url[7:]
    elif url.startswith("htp://"): url = "http://" + url[6:]

    if proto in ["WEBCAM", "BROWSER", "BROWSER_WEBCAM"]:
        if url.isdigit():
            return (str(int(url)), "webcam")
        # Non-digit URL is an independent browser MediaDevice deviceId or browser push stream
        return (url, "browser_webcam")

    if url.isdigit():
        return (str(int(url)), "webcam")

    # MP4 / Local Video Files Check: MUST check before prepending http:// to relative paths!
    url_lower = url.lower()
    if proto == "MP4" or any(url_lower.endswith(ext) for ext in [".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm"]):
        return (url, "mp4")

    # If user entered bare IP:port or hostname:port without scheme (e.g. 192.168.1.50:8080 or 10.179.43.18:8080/video)
    if not url.startswith(("http://", "https://", "rtsp://", "rtsps://", "/")):
        if proto == "RTSP" and not any(p in url for p in [":8080", ":4747", ":8081"]):
            url = f"rtsp://{url}"
        else:
            url = f"http://{url}"

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

        # Preserve custom URL paths. Only append /video if user provided bare URL with no path
        parsed_p = urllib.parse.urlparse(url)
        if not parsed_p.path or parsed_p.path == "/":
            url = url.rstrip("/") + "/video"
        return (url, "http_mjpeg")

    if proto == "RTSP":
        return (url, "rtsp")

    return (url, "mp4" if proto == "MP4" else "http_mjpeg")

def diagnose_stream_connection(url: str, host: str, port: int, err_code: int = 0, http_code: Optional[int] = None) -> tuple[str, str]:
    """
    Analyzes network parameters and socket/HTTP return codes to produce
    a precise error_type and user-actionable diagnostic message.
    """
    local_ip = get_local_server_ip()
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    error_type = "STREAM_UNAVAILABLE"
    parts = []

    # Check port range
    if port < 1 or port > 65535:
        return ("INVALID_PORT", f"Invalid port number: {port}. Port must be between 1 and 65535.")

    # Check IPv4 format
    if host:
        ip_parts = host.split(".")
        if len(ip_parts) == 4:
            for p in ip_parts:
                if not p.isdigit() or not (0 <= int(p) <= 255):
                    return ("INVALID_IP", f"Invalid IP address format: {host}. Must be a valid IPv4 address.")

    # HTTP Status Code Checks
    if http_code in [401, 403]:
        return (
            "AUTH_FAILED",
            f"Authentication failed (HTTP {http_code}). The camera at {host}:{port} requires authentication. "
            f"Please enter credentials in the URL (e.g. {scheme}://username:password@{host}:{port}{parsed.path})."
        )
    elif http_code == 404:
        return (
            "STREAM_NOT_FOUND",
            f"Stream path not found (HTTP 404). Host {host}:{port} answered, but the endpoint '{parsed.path or '/'}' does not exist. "
            f"Verify the exact stream path required by your camera app (e.g. /video, /videofeed, /mjpegfeed, /live)."
        )
    elif http_code and http_code >= 500:
        return (
            "SERVER_ERROR",
            f"Camera server error (HTTP {http_code}). The streaming server on {host}:{port} encountered an internal error."
        )

    # Socket Error Code Checks
    if err_code in [65, 113]:  # EHOSTUNREACH (macOS 65, Linux 113: No route to host)
        error_type = "HOST_UNREACHABLE"
        local_sub = ".".join(local_ip.split(".")[:3]) if (local_ip and "." in local_ip) else ""
        host_sub = ".".join(host.split(".")[:3]) if (host and "." in host) else ""

        if local_sub and host_sub and local_sub == host_sub:
            parts.append(
                f"No route to host ({host}). Server IP: {local_ip}, Camera IP: {host} (Same Subnet: {local_sub}.x).\n"
                f"The host is on the same local subnet but did not answer ARP requests. Common causes:\n"
                f"1. Router AP/Client Isolation is ENABLED (the Wi-Fi access point blocks wireless clients from communicating directly with each other).\n"
                f"2. Phone screen is locked/sleeping, causing the mobile OS to suspend the Wi-Fi radio or IP Webcam server.\n"
                f"3. Phone disconnected from Wi-Fi or DHCP assigned a different IP address.\n\n"
                f"Recommended Solution: Turn ON your phone's Mobile Hotspot, connect this computer directly to the phone's Wi-Fi hotspot, and enter the updated IP shown in your IP Webcam app."
            )
        else:
            parts.append(
                f"No route to host ({host}). Network Subnet Mismatch: Server is on '{local_ip}' (subnet {local_sub}.x), "
                f"while camera is on '{host}' (subnet {host_sub}.x).\n"
                f"Both devices must be connected to the same Wi-Fi/LAN network, or turn on Mobile Hotspot on the phone."
            )
    elif err_code in [61, 111]:  # ECONNREFUSED (macOS 61, Linux 111: Connection refused)
        error_type = "CONNECTION_REFUSED"
        parts.append(
            f"Connection refused: Host {host} is reachable on the network, but port {port} is closed. "
            f"The phone camera application (IP Webcam / DroidCam) is not running, or 'Start Server' has not been tapped in the app."
        )
    elif err_code in [60, 110, 35]:  # ETIMEDOUT / EAGAIN
        error_type = "CONNECTION_TIMEOUT"
        parts.append(
            f"Connection timed out: Host {host}:{port} did not respond within 2.0s. "
            f"Packets may be dropped by a firewall, or the phone is in low-power sleep mode."
        )
    else:
        error_type = "NETWORK_ERROR"
        parts.append(f"Cannot connect to stream host {host}:{port} (socket error code: {err_code}).")

    if scheme == "https":
        parts.append("Note: Most phone IP camera apps stream unencrypted over 'http://', NOT 'https://'.")

    return (error_type, " ".join(parts))

def diagnose_stream_connection_error(url: str, host: str, port: int, err_code: int = 0, http_code: Optional[int] = None) -> str:
    _, msg = diagnose_stream_connection(url, host, port, err_code, http_code)
    return msg

def validate_stream_url(url: str, protocol: str) -> tuple[bool, Optional[str]]:
    """
    Validates stream URL format.
    Returns (is_valid, error_message).
    """
    protocol = protocol.upper().strip()
    url = url.strip()
    if (url.startswith("'") and url.endswith("'")) or (url.startswith('"') and url.endswith('"')):
        url = url[1:-1].strip()

    if protocol in ["WEBCAM", "BROWSER", "BROWSER_WEBCAM"]:
        if url and (url.isdigit() or len(url.strip()) > 0):
            return True, None
        return False, "Invalid camera URL. For WEBCAM, select a valid camera hardware device."

    if protocol == "MP4":
        if not url:
            return False, "Invalid video path. Please select or enter an MP4 video file path."
        url_lower = url.lower()
        if any(url_lower.endswith(ext) for ext in [".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm"]) or "/" in url or "\\" in url or url.startswith("http"):
            return True, None
        return False, "Invalid video path. MP4 source must be a valid video file (.mp4)."

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
    rotation: Optional[int] = 0  # 0, 90, 180, 270
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
    rotation: Optional[int] = 0
    is_demo: Optional[bool] = False

class CameraRotationRequest(BaseModel):
    rotation: int  # 0, 90, 180, 270

class CameraHardwareUpdateRequest(BaseModel):
    device_id: str
    hardware_label: Optional[str] = None

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
    error_type: Optional[str] = None
    server_ip: Optional[str] = None
    camera_ip: Optional[str] = None
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

    has_primary = db.query(Camera).filter(Camera.role == "primary").first() is not None
    assigned_role = payload.role or ("secondary" if has_primary else "primary")

    # Ensure protocol accurately reflects resolved stream type
    actual_proto = payload.protocol.upper()
    if resolved_type == "http_mjpeg" and actual_proto == "RTSP":
        actual_proto = "HTTP_MJPEG"
    elif resolved_type == "rtsp" and actual_proto in ["HTTP", "MJPEG", "HTTP_MJPEG"]:
        actual_proto = "RTSP"

    existing = db.query(Camera).filter(Camera.camera_id == payload.camera_id).first()
    if existing:
        existing.name = payload.name
        existing.description = payload.description
        existing.location = payload.location
        existing.latitude = payload.latitude
        existing.longitude = payload.longitude
        existing.stream_url = normalized_url
        existing.protocol = actual_proto
        if payload.role:
            if payload.role == "primary":
                db.query(Camera).filter(Camera.id != existing.id).update({Camera.role: "secondary"})
            existing.role = payload.role
        existing.rotation = payload.rotation if payload.rotation is not None else existing.rotation
        existing.is_demo = payload.is_demo
        if actual_proto == "MP4":
            existing.status = "READY"
            if existing.health:
                existing.health.status = "READY"
                existing.health.processing_status = "READY"
                existing.health.fps = 0.0
        db.commit()
        db.refresh(existing)
        return existing

    if assigned_role == "primary":
        db.query(Camera).update({Camera.role: "secondary"})

    init_status = "READY" if actual_proto == "MP4" else "OFFLINE"
    cam = Camera(
        id=str(uuid.uuid4()),
        camera_id=payload.camera_id,
        name=payload.name,
        description=payload.description,
        location=payload.location,
        latitude=payload.latitude,
        longitude=payload.longitude,
        stream_url=normalized_url,
        protocol=actual_proto,
        role=assigned_role,
        rotation=payload.rotation or 0,
        status=init_status,
        is_demo=payload.is_demo
    )
    db.add(cam)

    health = CameraHealth(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        status=init_status,
        fps=0.0,
        latency_ms=0.0,
        processing_status="READY" if actual_proto == "MP4" else "IDLE"
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

@router.post("/upload-mp4", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
async def upload_mp4_file(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    """
    Uploads an actual .mp4 video file from the administrator's computer.
    Saves to storage/mp4_videos/ and verifies the file with cv2.VideoCapture.
    Returns real video metadata (resolution, fps, duration, frame count).
    """
    if not file.filename.lower().endswith((".mp4", ".m4v", ".mov", ".avi", ".mkv")):
        raise HTTPException(
            status_code=400,
            detail="FILE ERROR: Only MP4 video files (.mp4) are supported."
        )

    upload_dir = "storage/mp4_videos"
    os.makedirs(upload_dir, exist_ok=True)

    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.filename)
    safe_name = f"{uuid.uuid4().hex[:6]}_{clean_name}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    if not content or len(content) == 0:
        raise HTTPException(status_code=400, detail="FILE ERROR: Uploaded video file is empty.")

    with open(file_path, "wb") as f:
        f.write(content)

    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=400,
            detail="FILE ERROR: Uploaded file cannot be decoded as an MP4 video. The file may be corrupted."
        )

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = round(total_frames / max(1.0, fps), 1) if total_frames > 0 else 0.0
    cap.release()

    return {
        "status": "success",
        "file_path": file_path,
        "filename": file.filename,
        "size_bytes": len(content),
        "width": width,
        "height": height,
        "fps": round(fps, 1),
        "total_frames": total_frames,
        "duration_sec": duration_sec,
        "message": f"MP4 video file '{file.filename}' uploaded and verified ({width}x{height} @ {fps:.1f} FPS)."
    }

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
            "error_type": "INVALID_URL",
            "message": err_str
        }

    start_t = time.time()
    local_ip = get_local_server_ip()

    # Early return for browser webcam streams tested client-side
    if payload.protocol.upper() in ["WEBCAM", "BROWSER"] and not normalized_url.isdigit():
        return {
            "connected": True,
            "status": "SUCCESS",
            "source_type": "browser_webcam",
            "url": masked_url,
            "fps": 25.0,
            "width": 1280,
            "height": 720,
            "latency_ms": 1.0,
            "error": None,
            "error_type": None,
            "server_ip": local_ip,
            "camera_ip": "localhost",
            "message": "Browser webcam hardware source verified."
        }

    # MP4 Video Source Verification (NEVER run TCP/network checks on MP4)
    if payload.protocol.upper() == "MP4" or source_type == "mp4":
        target_path = normalized_url
        if not os.path.exists(target_path) and not os.path.isabs(target_path):
            alt_path = os.path.join(os.getcwd(), target_path)
            if os.path.exists(alt_path):
                target_path = alt_path

        if not os.path.exists(target_path) and not target_path.startswith("http"):
            latency = round((time.time() - start_t) * 1000, 1)
            err_msg = f"FILE ERROR: Video file '{normalized_url}' does not exist on the server."
            return {
                "connected": False,
                "status": "FAILED",
                "source_type": "mp4",
                "url": masked_url,
                "fps": 0.0,
                "width": 0,
                "height": 0,
                "latency_ms": latency,
                "error": err_msg,
                "error_type": "FILE_ERROR",
                "server_ip": local_ip,
                "camera_ip": "LOCAL_FILE",
                "message": err_msg
            }

        cap = cv2.VideoCapture(target_path)
        if not cap.isOpened():
            latency = round((time.time() - start_t) * 1000, 1)
            err_msg = f"FILE ERROR: Video file '{normalized_url}' cannot be opened or decoded. File may be corrupted or unsupported."
            return {
                "connected": False,
                "status": "FAILED",
                "source_type": "mp4",
                "url": masked_url,
                "fps": 0.0,
                "width": 0,
                "height": 0,
                "latency_ms": latency,
                "error": err_msg,
                "error_type": "FILE_ERROR",
                "server_ip": local_ip,
                "camera_ip": "LOCAL_FILE",
                "message": err_msg
            }

        ret, test_frame = cap.read()
        if not ret or test_frame is None:
            cap.release()
            latency = round((time.time() - start_t) * 1000, 1)
            err_msg = f"FILE ERROR: Video file '{normalized_url}' contains no decodable frames."
            return {
                "connected": False,
                "status": "FAILED",
                "source_type": "mp4",
                "url": masked_url,
                "fps": 0.0,
                "width": 0,
                "height": 0,
                "latency_ms": latency,
                "error": err_msg,
                "error_type": "FILE_ERROR",
                "server_ip": local_ip,
                "camera_ip": "LOCAL_FILE",
                "message": err_msg
            }

        h, w = test_frame.shape[:2]
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        latency = round((time.time() - start_t) * 1000, 1)

        return {
            "connected": True,
            "status": "SUCCESS",
            "source_type": "mp4",
            "url": masked_url,
            "fps": round(fps, 1),
            "width": int(w),
            "height": int(h),
            "latency_ms": latency,
            "error": None,
            "error_type": None,
            "server_ip": local_ip,
            "camera_ip": "LOCAL_FILE",
            "message": f"MP4 video file verified successfully. Resolution: {w}x{h} @ {fps:.1f} FPS ({total_frames} frames)."
        }

    # Step 2: TCP Reachability Pre-check for Network Streams (HTTP / RTSP)
    if normalized_url.startswith("http://") or normalized_url.startswith("https://") or normalized_url.startswith("rtsp://"):
        try:
            parsed = urllib.parse.urlparse(normalized_url)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else 554)
            if host:
                af = socket.AF_INET6 if ":" in host else socket.AF_INET
                s = socket.socket(af, socket.SOCK_STREAM)
                s.settimeout(2.0)
                res = s.connect_ex((host, port))
                s.close()
                if res != 0:
                    err_type, err_msg = diagnose_stream_connection(normalized_url, host, port, err_code=res)
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
                        "error_type": err_type,
                        "server_ip": local_ip,
                        "camera_ip": host,
                        "message": err_msg
                    }

                # Step 2b: HTTP Status Probe for HTTP/MJPEG streams
                if normalized_url.startswith("http://") or normalized_url.startswith("https://"):
                    try:
                        probe_req = urllib.request.Request(
                            normalized_url,
                            headers={"User-Agent": "IBVAP-Surveillance-Engine/1.0"}
                        )
                        with urllib.request.urlopen(probe_req, timeout=2.0) as probe_resp:
                            probe_code = probe_resp.getcode()
                            if probe_code >= 400:
                                err_type, err_msg = diagnose_stream_connection(normalized_url, host, port, http_code=probe_code)
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
                                    "error_type": err_type,
                                    "server_ip": local_ip,
                                    "camera_ip": host,
                                    "message": err_msg
                                }
                    except urllib.error.HTTPError as he:
                        err_type, err_msg = diagnose_stream_connection(normalized_url, host, port, http_code=he.code)
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
                            "error_type": err_type,
                            "server_ip": local_ip,
                            "camera_ip": host,
                            "message": err_msg
                        }
                    except Exception:
                        pass
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

    parsed_final = urllib.parse.urlparse(normalized_url)
    final_cam_host = parsed_final.hostname or ""

    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            fut = executor.submit(_attempt_frame_read)
            ok, width, height, fps, read_err = fut.result(timeout=3.5)

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
                "error_type": None,
                "server_ip": local_ip,
                "camera_ip": final_cam_host,
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
                "error_type": "NO_FRAMES_RECEIVED",
                "server_ip": local_ip,
                "camera_ip": final_cam_host,
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
            "error_type": "TIMEOUT",
            "server_ip": local_ip,
            "camera_ip": final_cam_host,
            "message": err_msg
        }

@router.post("/{camera_id}/start", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
async def start_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    from backend.main import manager as ws_manager
    from backend.stream_manager import stream_manager

    url = cam.stream_url.strip()
    if (url.startswith("'") and url.endswith("'")) or (url.startswith('"') and url.endswith('"')):
        url = url[1:-1].strip()

    is_mp4 = (cam.protocol == "MP4") or any(url.lower().endswith(ext) for ext in [".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm"])
    is_network_stream = (not is_mp4) and (url.startswith("http://") or url.startswith("https://") or url.startswith("rtsp://"))
    unreachable_reason = None
    local_ip = get_local_server_ip()
    cam_host = ""

    if is_mp4:
        # Check local MP4 file existence
        target_path = url
        if not os.path.exists(target_path) and not os.path.isabs(target_path):
            alt_path = os.path.join(os.getcwd(), target_path)
            if os.path.exists(alt_path):
                target_path = alt_path

        if not os.path.exists(target_path) and not target_path.startswith("http"):
            stream_manager.stop_stream(cam.camera_id)
            cam.status = "FILE ERROR"
            cam.fps = 0.0
            if cam.health:
                cam.health.status = "FILE ERROR"
                cam.health.fps = 0.0
                cam.health.processing_status = "IDLE"
            db.commit()
            return {
                "status": "error",
                "message": f"FILE ERROR: Video file '{url}' does not exist on the server.",
                "camera_id": cam.camera_id,
                "error": "FILE ERROR"
            }

        # Verify file can be opened by OpenCV
        test_cap = cv2.VideoCapture(target_path)
        if not test_cap.isOpened():
            test_cap.release()
            stream_manager.stop_stream(cam.camera_id)
            cam.status = "FILE ERROR"
            cam.fps = 0.0
            if cam.health:
                cam.health.status = "FILE ERROR"
                cam.health.fps = 0.0
                cam.health.processing_status = "IDLE"
            db.commit()
            return {
                "status": "error",
                "message": f"FILE ERROR: Video file '{url}' cannot be opened or decoded.",
                "camera_id": cam.camera_id,
                "error": "FILE ERROR"
            }
        test_cap.release()

        # Stop existing worker for this camera if any
        stream_manager.stop_stream(cam.camera_id)

        # Set status to READY and start worker
        cam.status = "READY"
        if cam.health:
            cam.health.status = "READY"
            cam.health.processing_status = "PROCESSING"
        db.commit()

        stream_manager.start_stream(
            camera_id=cam.camera_id,
            source_type="MP4",
            source_path=target_path,
            websocket_manager=ws_manager
        )

        return {
            "status": "success",
            "message": f"MP4 video stream {cam.camera_id} started.",
            "camera_id": cam.camera_id
        }

    if is_network_stream:
        try:
            parsed = urllib.parse.urlparse(url)
            cam_host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else 554)
            if cam_host:
                def _probe_tcp():
                    try:
                        af = socket.AF_INET6 if ":" in cam_host else socket.AF_INET
                        s = socket.socket(af, socket.SOCK_STREAM)
                        s.settimeout(2.0)
                        r = s.connect_ex((cam_host, port))
                        s.close()
                        return r
                    except Exception:
                        return -1

                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(None, _probe_tcp)
                if res != 0:
                    unreachable_reason = diagnose_stream_connection_error(url, cam_host, port, err_code=res)
        except Exception as e:
            unreachable_reason = str(e)

    # Stop existing worker for this camera if any
    stream_manager.stop_stream(cam.camera_id)

    if unreachable_reason:
        # Camera is unreachable, but store configuration and start background retry worker without affecting other cameras
        cam.status = "UNREACHABLE"
        cam.fps = 0.0
        if cam.health:
            cam.health.status = "UNREACHABLE"
            cam.health.fps = 0.0
            cam.health.latency_ms = 0.0
            cam.health.processing_status = "IDLE"
        db.commit()

        # Start stream worker so it automatically retries in background
        stream_manager.start_stream(
            camera_id=cam.camera_id,
            source_type=cam.protocol,
            source_path=cam.stream_url,
            websocket_manager=ws_manager
        )

        return {
            "status": "unreachable",
            "message": f"Camera {cam.camera_id} is currently unreachable. Auto-reconnect active in background: {unreachable_reason}",
            "camera_id": cam.camera_id,
            "error": unreachable_reason,
            "server_ip": local_ip,
            "camera_ip": cam_host
        }

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
async def stop_camera(camera_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
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

@router.post("/{camera_id}/frame")
async def ingest_camera_frame(
    camera_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Ingests live image frames (raw JPEG binary) pushed from independent browser webcam sessions.
    Delivers frames directly to the dedicated StreamWorker for real AI surveillance processing.
    Eliminates per-frame database queries via in-memory canonical ID resolution.
    """
    from backend.stream_manager import stream_manager
    from backend.main import manager as ws_manager

    canonical_id = stream_manager.resolve_canonical_id_cached(camera_id)
    worker = stream_manager.get_worker(canonical_id)
    if not worker or not worker.is_running:
        cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
        if cam:
            canonical_id = cam.camera_id
            stream_manager.clear_id_cache(camera_id)
            if cam.status != "STOPPED":
                stream_manager.start_stream(canonical_id, cam.protocol, cam.stream_url, ws_manager)

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty frame body")

    try:
        arr = np.frombuffer(body, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Corrupted image frame: {e}")

    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image frame encoding")

    delivered = stream_manager.push_frame(canonical_id, frame)
    return {"status": "ok", "delivered": delivered, "camera_id": canonical_id}

@router.put("/{camera_id}/rotation", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def update_camera_rotation(camera_id: str, payload: CameraRotationRequest, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    rot = int(payload.rotation) % 360
    if rot not in [0, 90, 180, 270]:
        raise HTTPException(status_code=400, detail="Rotation angle must be 0, 90, 180, or 270 degrees.")

    cam.rotation = rot
    db.commit()
    db.refresh(cam)

    # Propagate immediately to running StreamWorker
    from backend.stream_manager import stream_manager
    worker = stream_manager.get_worker(cam.camera_id)
    if worker:
        worker.rotation = rot

    return {
        "status": "success",
        "camera_id": cam.camera_id,
        "rotation": cam.rotation,
        "message": f"Camera rotation updated to {cam.rotation}°"
    }

@router.put("/{camera_id}/hardware-info")
def update_camera_hardware_info(
    camera_id: str,
    payload: CameraHardwareUpdateRequest,
    db: Session = Depends(get_db)
):
    cam = db.query(Camera).filter((Camera.id == camera_id) | (Camera.camera_id == camera_id)).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    dev_id = payload.device_id.strip()
    if dev_id:
        cam.stream_url = dev_id
    if payload.hardware_label and (not cam.name or cam.name.startswith("Camera CAM-") or cam.name == "Built-in Webcam"):
        cam.name = payload.hardware_label.strip()

    db.commit()
    db.refresh(cam)
    return {
        "status": "success",
        "camera_id": cam.camera_id,
        "stream_url": cam.stream_url,
        "name": cam.name
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

    # Automatically ensure stream worker is started if camera exists in DB and is not stopped or completed
    if cam and cam.status not in ["STOPPED", "COMPLETED", "FILE ERROR"]:
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
