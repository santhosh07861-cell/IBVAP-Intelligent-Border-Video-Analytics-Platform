import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from database.connection import Base

def generate_uuid():
    return str(uuid.uuid4())

class Role(Base):
    __tablename__ = "roles"
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(50), unique=True, nullable=False)  # Administrator, Security Operator, Analyst, Viewer
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class Permission(Base):
    __tablename__ = "permissions"
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255))

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    role_id = Column(String, ForeignKey("roles.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    role = relationship("Role")

class Camera(Base):
    __tablename__ = "cameras"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    location = Column(String(200))
    latitude = Column(Float, default=26.9124)
    longitude = Column(Float, default=70.9025)
    stream_url = Column(String(500), nullable=False)
    protocol = Column(String(20), default="MP4")  # RTSP, WEBCAM, MP4, ONVIF
    role = Column(String(20), default="secondary")  # primary, secondary
    status = Column(String(20), default="OFFLINE")  # ONLINE, OFFLINE, CONNECTING, DEGRADED, ERROR
    fps = Column(Float, default=0.0)
    resolution = Column(String(20), default="1920x1080")
    analytics_enabled = Column(Boolean, default=True)
    is_demo = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    zones = relationship("CameraZone", back_populates="camera", cascade="all, delete-orphan")
    health = relationship("CameraHealth", back_populates="camera", uselist=False, cascade="all, delete-orphan")

class CameraHealth(Base):
    __tablename__ = "camera_health"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"), unique=True)
    status = Column(String(20), default="OFFLINE")
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    fps = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    dropped_frames = Column(Integer, default=0)
    reconnect_attempts = Column(Integer, default=0)
    processing_status = Column(String(50), default="IDLE")

    camera = relationship("Camera", back_populates="health")

class CameraZone(Base):
    __tablename__ = "camera_zones"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"))
    name = Column(String(100), nullable=False)
    zone_type = Column(String(50), default="RESTRICTED AREA")  # BOP PERIMETER, RESTRICTED AREA, NO ENTRY, BORDER FENCE, ROAD CROSSING, CUSTOM
    geometry_type = Column(String(20), default="polygon")  # polygon, line
    coordinates = Column(JSON, nullable=False)  # [[x1, y1], [x2, y2], ...] normalized (0-1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    camera = relationship("Camera", back_populates="zones")
    rules = relationship("ZoneRule", back_populates="zone", cascade="all, delete-orphan")

class ZoneRule(Base):
    __tablename__ = "zone_rules"
    id = Column(String, primary_key=True, default=generate_uuid)
    zone_id = Column(String, ForeignKey("camera_zones.id"))
    object_type = Column(String(50), default="person")  # person, vehicle, all
    direction = Column(String(50), default="ANY")  # IN, OUT, BOTH, CROSSING
    min_confidence = Column(Float, default=0.5)
    loitering_threshold_sec = Column(Integer, default=10)
    time_window_start = Column(String(10), default="00:00")
    time_window_end = Column(String(10), default="23:59")
    cooldown_sec = Column(Integer, default=15)
    severity = Column(String(20), default="HIGH")  # INFO, LOW, MEDIUM, HIGH, CRITICAL
    enabled = Column(Boolean, default=True)

    zone = relationship("CameraZone", back_populates="rules")

class Detection(Base):
    __tablename__ = "detections"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    class_name = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    bbox = Column(JSON, nullable=False)  # [x, y, w, h] normalized
    track_id = Column(Integer, nullable=True, index=True)
    is_fallback = Column(Boolean, default=False)

class Track(Base):
    __tablename__ = "tracks"
    id = Column(String, primary_key=True, default=generate_uuid)
    track_id = Column(Integer, nullable=False, index=True)
    camera_id = Column(String, ForeignKey("cameras.id"))
    class_name = Column(String(50), nullable=False)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    dwell_time_sec = Column(Float, default=0.0)
    trajectory = Column(JSON, default=list)  # list of [x, y, timestamp]

class Event(Base):
    __tablename__ = "events"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"), index=True)
    zone_id = Column(String, ForeignKey("camera_zones.id"), nullable=True)
    event_type = Column(String(100), nullable=False)  # INTRUSION, FENCE_CROSSING, LOITERING, NIGHT_MOVEMENT, ANPR, FACE, CROWD
    severity = Column(String(20), default="MEDIUM")
    risk_score = Column(Float, default=50.0)
    confidence = Column(Float, default=0.85)
    details = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    track_id = Column(Integer, nullable=True)

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=generate_uuid)
    incident_number = Column(String(50), unique=True, nullable=False)
    camera_id = Column(String, ForeignKey("cameras.id"))
    title = Column(String(200), nullable=False)
    description = Column(Text)
    severity = Column(String(20), default="HIGH")  # INFO, LOW, MEDIUM, HIGH, CRITICAL
    risk_score = Column(Float, default=75.0)
    status = Column(String(30), default="NEW")  # NEW, ACKNOWLEDGED, INVESTIGATING, RESOLVED, FALSE_POSITIVE
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    related_event_ids = Column(JSON, default=list)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    camera = relationship("Camera")
    notes = relationship("IncidentNote", back_populates="incident", cascade="all, delete-orphan")
    evidence = relationship("Evidence", back_populates="incident", cascade="all, delete-orphan")

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=True)
    camera_id = Column(String, ForeignKey("cameras.id"))
    event_type = Column(String(100), nullable=False)
    severity = Column(String(20), default="HIGH")
    risk_score = Column(Float, default=70.0)
    confidence = Column(Float, default=0.88)
    status = Column(String(30), default="NEW")
    evidence_url = Column(String(500), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class ANPRResult(Base):
    __tablename__ = "anpr_results"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"))
    plate_text = Column(String(30), nullable=False, index=True)
    plate_confidence = Column(Float, default=0.90)
    ocr_confidence = Column(Float, default=0.88)
    vehicle_type = Column(String(30), default="car")
    crop_url = Column(String(500))
    full_frame_url = Column(String(500))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class FaceDetection(Base):
    __tablename__ = "face_detections"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"))
    bbox = Column(JSON, nullable=False)
    confidence = Column(Float, default=0.92)
    crop_url = Column(String(500))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class BehaviorEvent(Base):
    __tablename__ = "behavior_events"
    id = Column(String, primary_key=True, default=generate_uuid)
    camera_id = Column(String, ForeignKey("cameras.id"))
    track_id = Column(Integer)
    behavior_type = Column(String(100))  # LOITERING, REPEATED_CROSSING, RESTRICTED_HOUR, VEHICLE_STOPPING, CROWD, SUDDEN_SPEED
    description = Column(Text)
    dwell_time = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"))
    camera_id = Column(String, ForeignKey("cameras.id"))
    evidence_type = Column(String(30), default="snapshot")  # snapshot, object_crop, video_clip
    file_path = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    duration_sec = Column(Float, default=0.0)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="evidence")

class IncidentNote(Base):
    __tablename__ = "incident_notes"
    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"))
    user_id = Column(String, ForeignKey("users.id"))
    author_name = Column(String(100), default="Operator")
    note_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="notes")

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True, default=generate_uuid)
    recipient_role = Column(String(50), default="Security Operator")
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, nullable=True)
    username = Column(String(50), default="system")
    action = Column(String(100), nullable=False)
    resource = Column(String(100))
    details = Column(JSON, default=dict)
    ip_address = Column(String(50), default="127.0.0.1")
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class ModelRegistry(Base):
    __tablename__ = "model_registry"
    id = Column(String, primary_key=True, default=generate_uuid)
    model_name = Column(String(100), nullable=False)
    model_type = Column(String(50), default="detector")  # detector, tracker, anpr, face
    version = Column(String(20), default="v1.0")
    framework = Column(String(50), default="OpenCV DNN / PyTorch")
    file_path = Column(String(500))
    metrics = Column(JSON, default=dict)  # mAP, precision, recall, latency_ms
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ModelVersion(Base):
    __tablename__ = "model_versions"
    id = Column(String, primary_key=True, default=generate_uuid)
    model_id = Column(String, ForeignKey("model_registry.id"))
    version_tag = Column(String(50), nullable=False)
    changelog = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemMetric(Base):
    __tablename__ = "system_metrics"
    id = Column(String, primary_key=True, default=generate_uuid)
    component = Column(String(50), nullable=False)  # API, DB, AI Engine, Video Engine, Storage
    cpu_percent = Column(Float, default=0.0)
    memory_percent = Column(Float, default=0.0)
    gpu_percent = Column(Float, default=0.0)
    fps = Column(Float, default=25.0)
    inference_latency_ms = Column(Float, default=15.0)
    active_connections = Column(Integer, default=1)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
