import time
import uuid
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from ai_engine.detection.real_ai_detector import (
    RealAIDetector, get_display_label, get_track_prefix, VEHICLE_CLASSES, PERSON_CLASSES, DRONE_CLASSES
)
from ai_engine.tracking.tracker import MultiObjectTracker, TrackedObject
from ai_engine.face.real_face_engine import RealFaceEngine, FaceTracker, FaceTrack, DetectedFace
from ai_engine.anpr.anpr_engine import ANPREngine, save_anpr_evidence_snapshot
from event_engine.risk.scorer import OperationalRiskScorer
from storage.evidence_manager import EvidenceManager
from database.connection import SessionLocal
from database.schema import Camera, CameraZone, ZoneRule, Event, Alert, Incident, Evidence, FaceDetection, FaceWatchlist, ANPRResult, ANPRWatchlist, Detection

from backend.config import (
    DETECTION_CONFIDENCE_THRESHOLD, LOITERING_THRESHOLD_SEC, ALERT_COOLDOWN_SEC, EVIDENCE_CAPTURE_INTERVAL_SEC,
    ANPR_DUPLICATE_COOLDOWN_SEC
)

logger = logging.getLogger(__name__)

VERIFIED_CATEGORIES = {
    "STUDENT", "STAFF", "FACULTY", "STUDENT_VERIFIED", "VIP", "AUTHORIZED",
    "SECURITY", "GUARD", "EMPLOYEE", "ADMIN", "ADMINISTRATOR", "PERSONNEL", "OFFICER"
}
THREAT_CATEGORIES = {
    "WATCHLIST", "BANNED", "PERSON_OF_INTEREST", "SUSPECT", "RESTRICTED",
    "BLACK_LIST", "THREAT", "CRIMINAL", "BLACKLIST"
}

def point_in_polygon(point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
    x, y = point
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

class AISurveillanceAgent:
    """
    Central AI Surveillance Agent.
    Executes the intelligent surveillance processing pipeline on actual camera frames:
      1. Frame validation
      2. Real AI model inference (YOLOv8)
      3. Multi-object tracking (ByteTrack)
      4. Face detection (YuNet) & Recognition (SFace) with College Security Policy:
         - Verified student/staff -> Entry log only, NO alarm
         - Unknown person -> Verification Required security alert -> Alarm
         - Watchlist threat -> Critical alert -> Immediate alarm
      5. Restricted Zone & Virtual Fence polygon rule evaluation
      6. Deduplication & cooldown enforcement
      7. Non-blocking WebSocket telemetry & Alert dispatch
    """
    _io_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evidence_io")

    def __init__(self, camera_id: str, websocket_manager: Any):
        self.camera_id = camera_id
        self.ws_manager = websocket_manager
        self.detector = RealAIDetector(conf_threshold=DETECTION_CONFIDENCE_THRESHOLD)
        self.tracker = MultiObjectTracker()
        self.face_engine = RealFaceEngine()
        self.face_tracker = FaceTracker()
        self.anpr_engine = ANPREngine()
        self.scorer = OperationalRiskScorer()
        self.evidence_mgr = EvidenceManager()
        self.last_alert_times: Dict[str, float] = {}
        self.last_detection_snapshot_times: Dict[Tuple[str, int, str], float] = {}
        self.last_face_process_time = 0.0
        self.last_anpr_process_times: Dict[Tuple[str, int], float] = {}
        self.last_anpr_db_times: Dict[Tuple[str, str], float] = {}
        self.last_face_db_record_times: Dict[Tuple[str, int, str, str], float] = {}
        self.active_faces: List[Dict[str, Any]] = []
        self.active_anpr: List[Dict[str, Any]] = []
        self.track_zone_states: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        self.mode_label = "REAL AI | INFERENCE RUNNING"

    async def process_frame(self, frame: np.ndarray, loop_start_time: float, pre_frame: Optional[np.ndarray] = None) -> Tuple[List[TrackedObject], float, float, List[Dict[str, Any]], List[Dict[str, Any]]]:
        if frame is None or frame.size == 0:
            return [], 0.0, 0.0, [], []

        # 1. Run Real AI Model Inference (YOLOv8)
        raw_detections = self.detector.detect(frame, self.camera_id)

        # 2. Filter Detections
        filtered_detections = [d for d in raw_detections if d.confidence >= DETECTION_CONFIDENCE_THRESHOLD]

        # 3. Multi-Object Tracking & Confirmation
        tracked_objects = self.tracker.update(self.camera_id, filtered_detections)

        latency_ms = round((time.time() - loop_start_time) * 1000, 1)

        if raw_detections:
            logger.info(f"[AI INFERENCE] camera={self.camera_id} detections={len(raw_detections)} latency={latency_ms}ms")
            for det in raw_detections:
                if det.class_name.lower() == "person":
                    logger.info(f"[PERSON DETECTED] camera={self.camera_id} confidence={det.confidence:.2f} bbox={[round(v, 2) for v in det.bbox]}")
                elif det.class_name.lower() in VEHICLE_CLASSES:
                    logger.info(f"[VEHICLE DETECTED] camera={self.camera_id} class={det.class_name} confidence={det.confidence:.2f} bbox={[round(v, 2) for v in det.bbox]}")

        # 4. Confirmed tracks trigger evidence capture + security rules
        confirmed_objs = [obj for obj in tracked_objects if obj.is_confirmed]
        if confirmed_objs:
            now_sec = time.time()
            for obj in confirmed_objs:
                track_key = (self.camera_id, obj.track_id, obj.class_name)
                if now_sec - self.last_detection_snapshot_times.get(track_key, 0) >= EVIDENCE_CAPTURE_INTERVAL_SEC:
                    self.last_detection_snapshot_times[track_key] = now_sec
                    asyncio.create_task(self._create_and_broadcast_detection_evidence(obj, frame))

            # Evaluate Zone & Intrusion Rules
            await self._evaluate_surveillance_rules(confirmed_objs, frame, pre_frame=pre_frame)

        # 5. Face Detection & Verification Pipeline
        active_faces = await self._process_face_intelligence(frame, confirmed_objs)

        # 6. ANPR Pipeline for Vehicles
        vehicle_objs = [obj for obj in confirmed_objs if obj.class_name.lower() in VEHICLE_CLASSES]
        if vehicle_objs:
            asyncio.create_task(self._process_anpr_intelligence(frame, vehicle_objs))

        return tracked_objects, latency_ms, self.detector.conf_threshold, active_faces, self.active_anpr

    async def _process_face_intelligence(self, frame: np.ndarray, confirmed_objs: List[TrackedObject]) -> List[Dict[str, Any]]:
        """
        Face Detection, Quality Filter, SFace Feature Embedding,
        Watchlist Comparison, and College Security Verification Policy:
          - VERIFIED (Student/Staff): Entry log created, NO ALARM.
          - UNKNOWN (Unverified person): Security Alert created -> Alarm.
          - WATCHLIST (Threat/Banned): Critical Alert created -> Immediate Alarm.
        """
        person_objs = [obj for obj in confirmed_objs if obj.class_name.lower() == "person"]
        if not person_objs:
            self.active_faces = []
            return []

        now_sec = time.time()
        if now_sec - self.last_face_process_time < 0.20 and self.active_faces:
            return self.active_faces

        self.last_face_process_time = now_sec

        # Detect faces using YuNet in background thread
        loop = asyncio.get_event_loop()
        detected_faces: List[DetectedFace] = await loop.run_in_executor(
            self._io_executor,
            lambda: self.face_engine.detect_faces(frame)
        )

        # Spatial Filter: Correlate faces with detected person bounding boxes
        valid_faces = []
        for face in detected_faces:
            fx, fy, fw, fh = face.bbox_norm
            fcx = fx + fw / 2.0
            fcy = fy + fh / 2.0
            for p in person_objs:
                px, py, pw, ph = p.bbox
                margin_x = pw * 0.20
                margin_y = ph * 0.20
                if (px - margin_x <= fcx <= px + pw + margin_x) and (py - margin_y <= fcy <= py + ph * 0.70):
                    valid_faces.append(face)
                    break

        confirmed_tracks: List[FaceTrack] = self.face_tracker.update(valid_faces)
        if not confirmed_tracks:
            self.active_faces = []
            return []

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            cam_id = cam.id if cam else self.camera_id
            cam_num = cam.camera_id if cam else self.camera_id
            cam_name = cam.name if cam else "Campus Security Camera"
            cam_loc = cam.location or "Campus Main Gate" if cam else "Campus Main Gate"

            watchlist_records = db.query(FaceWatchlist).filter(FaceWatchlist.is_active == True).all()

            faces_payload = []
            for track in confirmed_tracks:
                track = self.face_engine.evaluate_track_recognition(frame, track, watchlist_records)

                is_known = (track.recognition_status == "KNOWN" and track.identity_name is not None)
                p_badge = getattr(track, "person_id", None) or (f"ID-{track.track_id}")
                p_cat = (getattr(track, "category", "") or "UNKNOWN").upper()

                # Determine security category
                is_verified_student_staff = is_known and (p_cat in VERIFIED_CATEGORIES)
                is_threat_watchlist = is_known and (p_cat in THREAT_CATEGORIES)
                is_unknown_person = not is_known

                face_data = {
                    "track_id": track.track_id,
                    "bbox": track.bbox_norm,
                    "landmarks": track.landmarks,
                    "confidence": track.confidence,
                    "quality_score": track.quality_score,
                    "recognition_status": "VERIFIED" if is_verified_student_staff else "KNOWN" if is_threat_watchlist else "UNKNOWN",
                    "identity_id": track.identity_id,
                    "identity_name": track.identity_name if is_known else "UNKNOWN / VERIFICATION REQUIRED",
                    "person_id": p_badge if is_known else None,
                    "category": p_cat if is_known else "UNKNOWN",
                    "recognition_confidence": track.recognition_confidence,
                    "raw_similarity": getattr(track, "raw_similarity", 0.0)
                }
                faces_payload.append(face_data)

                is_uncertain = (track.recognition_status == "UNCERTAIN") or (not getattr(track, "is_high_quality", True) and track.quality_score < 0.35)

                # Deduplication logic
                if is_verified_student_staff:
                    event_type = "STUDENT_VERIFIED"
                    dedup_key = (self.camera_id, track.track_id, str(p_badge), event_type)
                    cooldown_sec = 60.0
                elif is_threat_watchlist:
                    event_type = "FACE_WATCHLIST_MATCH"
                    dedup_key = (self.camera_id, track.track_id, str(p_badge), event_type)
                    cooldown_sec = 30.0
                elif is_uncertain:
                    event_type = "UNCERTAIN_FACE"
                    dedup_key = (self.camera_id, track.track_id, "UNCERTAIN", event_type)
                    cooldown_sec = 60.0
                else:
                    event_type = "UNKNOWN_PERSON_DETECTED"
                    dedup_key = (self.camera_id, track.track_id, "UNKNOWN", event_type)
                    cooldown_sec = 45.0

                if now_sec - self.last_face_db_record_times.get(dedup_key, 0) >= cooldown_sec:
                    self.last_face_db_record_times[dedup_key] = now_sec

                    # Offload crop and snapshot saving to background thread
                    crop_saved = await loop.run_in_executor(
                        self._io_executor,
                        lambda: self.face_engine.save_face_crop(frame.copy(), track.bbox_norm, f"{cam_num}_F{track.track_id}")
                    )
                    snap_saved = await loop.run_in_executor(
                        self._io_executor,
                        lambda: self.face_engine.save_annotated_face_snapshot(
                            frame=frame.copy(),
                            camera_id=cam_num,
                            camera_name=cam_name,
                            camera_location=cam_loc,
                            track=track,
                            event_type="🚨 WATCHLIST THREAT" if is_threat_watchlist else "VERIFIED STUDENT" if is_verified_student_staff else "UNCERTAIN FACE" if is_uncertain else "UNKNOWN PERSON"
                        )
                    )

                    crop_url = crop_saved[1] if crop_saved else None
                    snap_url = snap_saved[1] if snap_saved else None
                    snap_path = snap_saved[0] if snap_saved else ""
                    snap_size = snap_saved[2] if snap_saved else 0

                    now_dt = datetime.utcnow()
                    ts_str = f"{now_dt.isoformat()}Z"

                    # 1. Insert FaceDetection log record
                    face_rec = FaceDetection(
                        id=str(uuid.uuid4()),
                        camera_id=cam_id,
                        track_id=track.track_id,
                        identity_id=track.identity_id,
                        identity_name=track.identity_name if is_known else None,
                        recognition_status="KNOWN" if is_known else ("UNCERTAIN" if is_uncertain else "UNKNOWN"),
                        detection_confidence=track.confidence,
                        recognition_confidence=track.recognition_confidence,
                        bbox=track.bbox_norm,
                        landmarks=track.landmarks,
                        crop_url=crop_url,
                        snapshot_url=snap_url,
                        quality_score=track.quality_score,
                        timestamp=now_dt
                    )
                    db.add(face_rec)

                    # 2. Case A: Verified Student/Staff -> Entry Log ONLY (NO Security Alarm)
                    if is_verified_student_staff:
                        logger.info(f"🎓 [STUDENT/STAFF VERIFIED] {track.identity_name} (ID: {p_badge}) at {cam_num} — NO ALARM TRIGGERED")
                        ev_student = Event(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type="STUDENT_VERIFIED",
                            severity="INFO",
                            risk_score=10.0,
                            confidence=track.recognition_confidence,
                            details={
                                "person_name": track.identity_name,
                                "person_id": p_badge,
                                "category": p_cat,
                                "verification_status": "VERIFIED",
                                "camera_name": cam_name,
                                "camera_location": cam_loc,
                                "timestamp": ts_str,
                            },
                            timestamp=now_dt,
                            track_id=track.track_id
                        )
                        db.add(ev_student)
                        db.commit()

                    # 3. Case B: Threat / Watchlist Match -> CRITICAL Security Alert + Incident + Immediate Alarm
                    elif is_threat_watchlist:
                        logger.warning(f"🚨 [WATCHLIST THREAT DETECTED] Subject: {track.identity_name} ({p_badge}) on {cam_num}")
                        ev_threat = Event(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type="FACE_WATCHLIST_MATCH",
                            severity="CRITICAL",
                            risk_score=95.0,
                            confidence=track.recognition_confidence,
                            details={
                                "person_name": track.identity_name,
                                "person_id": p_badge,
                                "category": p_cat,
                                "verification_status": "WATCHLIST_MATCH",
                                "camera_name": cam_name,
                                "camera_location": cam_loc,
                                "timestamp": ts_str,
                            },
                            timestamp=now_dt,
                            track_id=track.track_id
                        )
                        db.add(ev_threat)

                        al_threat = Alert(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type="FACE_WATCHLIST_MATCH",
                            severity="CRITICAL",
                            risk_score=95.0,
                            confidence=track.recognition_confidence,
                            status="NEW",
                            evidence_url=snap_url,
                            timestamp=now_dt
                        )
                        db.add(al_threat)

                        inc_num = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                        inc_threat = Incident(
                            id=str(uuid.uuid4()),
                            incident_number=inc_num,
                            camera_id=cam_id,
                            title=f"CRITICAL WATCHLIST THREAT — {track.identity_name.upper()}",
                            description=f"Watchlist subject '{track.identity_name}' (ID: {p_badge}, Category: {p_cat}) detected at {cam_name} with {int(track.recognition_confidence * 100)}% match similarity.",
                            severity="CRITICAL",
                            risk_score=95.0,
                            status="NEW",
                            related_event_ids=[ev_threat.id],
                            start_time=now_dt,
                            created_at=now_dt
                        )
                        db.add(inc_threat)
                        al_threat.incident_id = inc_threat.id

                        if snap_saved:
                            ev_evidence = Evidence(
                                id=str(uuid.uuid4()),
                                incident_id=inc_threat.id,
                                camera_id=cam_id,
                                evidence_type="snapshot",
                                file_path=snap_path,
                                file_url=snap_url,
                                file_size_bytes=snap_size,
                                metadata_json={
                                    "alert_id": al_threat.id,
                                    "event_id": ev_threat.id,
                                    "person_name": track.identity_name,
                                    "person_id": p_badge,
                                    "category": p_cat,
                                    "timestamp": ts_str,
                                },
                                created_at=now_dt
                            )
                            db.add(ev_evidence)

                        db.commit()

                        # Broadcast WebSocket ALERT_NEW
                        await self.ws_manager.broadcast({
                            "type": "ALERT_NEW",
                            "alert_id": al_threat.id,
                            "event_id": ev_threat.id,
                            "incident_id": inc_threat.id,
                            "incident_number": inc_threat.incident_number,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "object_class": "person",
                            "track_id": f"F-{track.track_id}",
                            "confidence": track.recognition_confidence,
                            "event_type": "FACE_WATCHLIST_MATCH",
                            "alert_title": f"🚨 WATCHLIST THREAT — {track.identity_name.upper()}",
                            "person_name": track.identity_name,
                            "person_id": p_badge,
                            "category": p_cat,
                            "similarity": track.recognition_confidence,
                            "risk_score": 95.0,
                            "severity": "CRITICAL",
                            "timestamp": ts_str,
                            "evidence_url": snap_url,
                            "alert": {
                                "id": al_threat.id,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "location": cam_loc,
                                "object_class": "person",
                                "track_id": f"F-{track.track_id}",
                                "confidence": track.recognition_confidence,
                                "event_type": "FACE_WATCHLIST_MATCH",
                                "alert_title": f"🚨 WATCHLIST THREAT — {track.identity_name.upper()}",
                                "person_name": track.identity_name,
                                "person_id": p_badge,
                                "severity": "CRITICAL",
                                "risk_score": 95.0,
                                "evidence_url": snap_url,
                                "timestamp": ts_str,
                            }
                        })

                        # Broadcast WebSocket INCIDENT_NEW
                        await self.ws_manager.broadcast({
                            "type": "INCIDENT_NEW",
                            "incident_id": inc_threat.id,
                            "incident_number": inc_threat.incident_number,
                            "event_id": ev_threat.id,
                            "alert_id": al_threat.id,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "title": inc_threat.title,
                            "description": inc_threat.description,
                            "severity": "CRITICAL",
                            "risk_score": 95.0,
                            "status": inc_threat.status,
                            "timestamp": ts_str,
                            "created_at": ts_str,
                            "evidence_url": snap_url,
                            "incident": {
                                "id": inc_threat.id,
                                "incident_number": inc_threat.incident_number,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "title": inc_threat.title,
                                "description": inc_threat.description,
                                "severity": "CRITICAL",
                                "risk_score": 95.0,
                                "status": inc_threat.status,
                                "start_time": ts_str,
                                "created_at": ts_str,
                            }
                        })

                        await self.ws_manager.broadcast({
                            "type": "FACE_WATCHLIST_MATCH",
                            "alert_id": al_threat.id,
                            "event_id": ev_threat.id,
                            "incident_id": inc_threat.id,
                            "incident_number": inc_threat.incident_number,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "event_type": "FACE_WATCHLIST_MATCH",
                            "alert_title": f"🚨 WATCHLIST THREAT — {track.identity_name.upper()}",
                            "person_name": track.identity_name,
                            "person_id": p_badge,
                            "category": p_cat,
                            "track_id": f"F-{track.track_id}",
                            "similarity": track.recognition_confidence,
                            "severity": "CRITICAL",
                            "risk_score": 95.0,
                            "evidence_url": snap_url,
                            "snapshot_url": snap_url,
                            "crop_url": crop_url,
                            "timestamp": ts_str,
                            "alert": {
                                "id": al_threat.id,
                                "alert_id": al_threat.id,
                                "event_id": ev_threat.id,
                                "incident_id": inc_threat.id,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "location": cam_loc,
                                "event_type": "FACE_WATCHLIST_MATCH",
                                "alert_title": f"🚨 WATCHLIST THREAT — {track.identity_name.upper()}",
                                "person_name": track.identity_name,
                                "person_id": p_badge,
                                "category": p_cat,
                                "severity": "CRITICAL",
                                "risk_score": 95.0,
                                "evidence_url": snap_url,
                                "timestamp": ts_str,
                            }
                        })

                        await self.ws_manager.broadcast({
                            "type": "ALERT_NEW",
                            "alert_id": al_threat.id,
                            "event_id": ev_threat.id,
                            "incident_id": inc_threat.id,
                            "incident_number": inc_threat.incident_number,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "event_type": "FACE_WATCHLIST_MATCH",
                            "alert_title": f"🚨 WATCHLIST THREAT — {track.identity_name.upper()}",
                            "person_name": track.identity_name,
                            "person_id": p_badge,
                            "category": p_cat,
                            "track_id": f"F-{track.track_id}",
                            "similarity": track.recognition_confidence,
                            "severity": "CRITICAL",
                            "risk_score": 95.0,
                            "evidence_url": snap_url,
                            "timestamp": ts_str,
                            "alert": {
                                "id": al_threat.id,
                                "alert_id": al_threat.id,
                                "event_id": ev_threat.id,
                                "incident_id": inc_threat.id,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "location": cam_loc,
                                "event_type": "FACE_WATCHLIST_MATCH",
                                "alert_title": f"🚨 WATCHLIST THREAT — {track.identity_name.upper()}",
                                "person_name": track.identity_name,
                                "person_id": p_badge,
                                "category": p_cat,
                                "severity": "CRITICAL",
                                "risk_score": 95.0,
                                "evidence_url": snap_url,
                                "timestamp": ts_str,
                            }
                        })

                    # 4. Case C: Uncertain / Low Quality Face -> Log only (NO Alarm)
                    elif is_uncertain:
                        logger.info(f"ℹ️ [UNCERTAIN FACE QUALITY] Track #{track.track_id} on {cam_num} (Quality Score: {track.quality_score:.2f}) — Logged only, NO ALARM")
                        db.commit()

                    # 5. Case D: Unknown Person -> Security Alert (Verification Required) + Incident + Alarm
                    else:
                        logger.info(f"⚠️ [UNKNOWN PERSON DETECTED] Track #{track.track_id} on {cam_num} — Security Alert Generated")
                        ev_unknown = Event(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type="UNKNOWN_PERSON_DETECTED",
                            severity="HIGH",
                            risk_score=75.0,
                            confidence=track.confidence,
                            details={
                                "person_name": "UNKNOWN PERSON",
                                "verification_status": "UNKNOWN",
                                "track_id": f"F-{track.track_id}",
                                "camera_name": cam_name,
                                "camera_location": cam_loc,
                                "timestamp": ts_str,
                            },
                            timestamp=now_dt,
                            track_id=track.track_id
                        )
                        db.add(ev_unknown)

                        al_unknown = Alert(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type="UNKNOWN_PERSON_DETECTED",
                            severity="HIGH",
                            risk_score=75.0,
                            confidence=track.confidence,
                            status="NEW",
                            evidence_url=snap_url,
                            timestamp=now_dt
                        )
                        db.add(al_unknown)

                        inc_num_unk = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                        inc_unknown = Incident(
                            id=str(uuid.uuid4()),
                            incident_number=inc_num_unk,
                            camera_id=cam_id,
                            title=f"HIGH UNKNOWN PERSON DETECTED — {cam_name}",
                            description=f"Unrecognized subject (Track #F-{track.track_id}) detected at {cam_name}. Operator identity verification required.",
                            severity="HIGH",
                            risk_score=75.0,
                            status="NEW",
                            related_event_ids=[ev_unknown.id],
                            start_time=now_dt,
                            created_at=now_dt
                        )
                        db.add(inc_unknown)
                        al_unknown.incident_id = inc_unknown.id

                        if snap_saved:
                            ev_evidence_unk = Evidence(
                                id=str(uuid.uuid4()),
                                incident_id=inc_unknown.id,
                                camera_id=cam_id,
                                evidence_type="snapshot",
                                file_path=snap_path,
                                file_url=snap_url,
                                file_size_bytes=snap_size,
                                metadata_json={
                                    "alert_id": al_unknown.id,
                                    "event_id": ev_unknown.id,
                                    "track_id": f"F-{track.track_id}",
                                    "timestamp": ts_str,
                                },
                                created_at=now_dt
                            )
                            db.add(ev_evidence_unk)

                        db.commit()

                        # Broadcast WebSocket ALERT_NEW
                        await self.ws_manager.broadcast({
                            "type": "ALERT_NEW",
                            "alert_id": al_unknown.id,
                            "event_id": ev_unknown.id,
                            "incident_id": inc_unknown.id,
                            "incident_number": inc_unknown.incident_number,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "object_class": "person",
                            "track_id": f"F-{track.track_id}",
                            "confidence": track.confidence,
                            "event_type": "UNKNOWN_PERSON_DETECTED",
                            "alert_title": "⚠️ UNKNOWN PERSON — VERIFICATION REQUIRED",
                            "person_name": "UNKNOWN PERSON",
                            "category": "UNKNOWN",
                            "risk_score": 75.0,
                            "severity": "HIGH",
                            "timestamp": ts_str,
                            "evidence_url": snap_url,
                            "alert": {
                                "id": al_unknown.id,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "location": cam_loc,
                                "object_class": "person",
                                "track_id": f"F-{track.track_id}",
                                "confidence": track.confidence,
                                "event_type": "UNKNOWN_PERSON_DETECTED",
                                "alert_title": "⚠️ UNKNOWN PERSON — VERIFICATION REQUIRED",
                                "person_name": "UNKNOWN PERSON",
                                "category": "UNKNOWN",
                                "severity": "HIGH",
                                "risk_score": 75.0,
                                "evidence_url": snap_url,
                                "timestamp": ts_str,
                            }
                        })

                        # Broadcast WebSocket INCIDENT_NEW
                        await self.ws_manager.broadcast({
                            "type": "INCIDENT_NEW",
                            "incident_id": inc_unknown.id,
                            "incident_number": inc_unknown.incident_number,
                            "event_id": ev_unknown.id,
                            "alert_id": al_unknown.id,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "title": inc_unknown.title,
                            "description": inc_unknown.description,
                            "severity": "HIGH",
                            "risk_score": 75.0,
                            "status": inc_unknown.status,
                            "timestamp": ts_str,
                            "created_at": ts_str,
                            "evidence_url": snap_url,
                            "incident": {
                                "id": inc_unknown.id,
                                "incident_number": inc_unknown.incident_number,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "title": inc_unknown.title,
                                "description": inc_unknown.description,
                                "severity": "HIGH",
                                "risk_score": 75.0,
                                "status": inc_unknown.status,
                                "start_time": ts_str,
                                "created_at": ts_str,
                            }
                        })

                    # Broadcast FACE_DETECTION_UPDATE telemetry
                    await self.ws_manager.broadcast({
                        "type": "FACE_DETECTION_UPDATE",
                        "face_id": face_rec.id,
                        "camera_id": cam_id,
                        "camera_number": cam_num,
                        "camera_name": cam_name,
                        "location": cam_loc,
                        "track_id": track.track_id,
                        "bbox": track.bbox_norm,
                        "identity_id": track.identity_id,
                        "identity_name": track.identity_name,
                        "person_id": p_badge if is_known else None,
                        "category": p_cat if is_known else "UNKNOWN",
                        "recognition_status": "VERIFIED" if is_verified_student_staff else "KNOWN" if is_threat_watchlist else "UNKNOWN",
                        "detection_confidence": track.confidence,
                        "recognition_confidence": track.recognition_confidence,
                        "crop_url": crop_url,
                        "snapshot_url": snap_url,
                        "quality_score": track.quality_score,
                        "timestamp": face_rec.timestamp.isoformat()
                    })

            self.active_faces = faces_payload
            return faces_payload
        except Exception as ex:
            logger.error(f"Error processing face intelligence on {self.camera_id}: {ex}", exc_info=True)
            try: db.rollback()
            except Exception: pass
            return []
        finally:
            db.close()

    async def _process_anpr_intelligence(self, frame: np.ndarray, vehicle_objs: List[TrackedObject]) -> None:
        """
        ANPR pipeline executed for confirmed vehicle tracks.
        """
        if frame is None or frame.size == 0:
            return

        fh, fw = frame.shape[:2]
        now_sec = time.time()
        loop = asyncio.get_event_loop()

        for obj in vehicle_objs:
            track_key = (self.camera_id, obj.track_id)
            if now_sec - self.last_anpr_process_times.get(track_key, 0) < 1.0:
                continue
            self.last_anpr_process_times[track_key] = now_sec

            vx = max(0, int(obj.bbox[0] * fw))
            vy = max(0, int(obj.bbox[1] * fh))
            vw = max(1, int(obj.bbox[2] * fw))
            vh = max(1, int(obj.bbox[3] * fh))
            vehicle_crop = frame[vy:min(fh, vy + vh), vx:min(fw, vx + vw)].copy()

            if vehicle_crop.size == 0:
                continue

            try:
                anpr_result = await loop.run_in_executor(
                    self._io_executor,
                    lambda crop=vehicle_crop, tid=obj.track_id: self.anpr_engine.process_vehicle_crop(
                        crop, self.camera_id, tid
                    )
                )
            except Exception as e:
                logger.error(f"[ANPR] process_vehicle_crop error on {self.camera_id}: {e}")
                continue

            if not anpr_result:
                continue

            ocr_text = anpr_result["ocr_text"]
            ocr_conf = anpr_result["ocr_confidence"]

            self.active_anpr = [a for a in self.active_anpr if a.get("track_id") != obj.track_id]
            self.active_anpr.append({
                "track_id": obj.track_id,
                "vehicle_type": obj.class_name.upper(),
                "bbox": obj.bbox,
                "plate_text": ocr_text,
                "ocr_confidence": ocr_conf,
                "status": "READING",
            })

            if not anpr_result.get("just_confirmed"):
                continue

            plate_text, avg_conf, is_valid = self.anpr_engine.tracker.get_best_result(
                self.camera_id, obj.track_id
            )
            status = "CONFIRMED" if (plate_text != "PLATE UNCERTAIN" and avg_conf >= 0.60) else "UNCERTAIN"

            dedup_key = (self.camera_id, plate_text)
            if now_sec - self.last_anpr_db_times.get(dedup_key, 0) < ANPR_DUPLICATE_COOLDOWN_SEC:
                continue
            self.last_anpr_db_times[dedup_key] = now_sec
            self.anpr_engine.tracker.reset_confirmed(self.camera_id, obj.track_id)

            db = SessionLocal()
            try:
                cam = db.query(Camera).filter(
                    (Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)
                ).first()
                cam_id = cam.id if cam else self.camera_id
                cam_num = cam.camera_id if cam else self.camera_id
                cam_name = cam.name if cam else "Campus Surveillance Camera"
                cam_loc = cam.location or "Gate 1 Main Entry" if cam else "Gate 1 Main Entry"
                vehicle_type = obj.class_name.upper()

                plate_bbox_in_vehicle = anpr_result.get("plate_bbox_norm")
                saved = await loop.run_in_executor(
                    self._io_executor,
                    lambda: save_anpr_evidence_snapshot(
                        frame=frame.copy(),
                        vehicle_bbox=obj.bbox,
                        plate_bbox_in_vehicle=plate_bbox_in_vehicle,
                        plate_text=plate_text,
                        vehicle_type=vehicle_type,
                        ocr_confidence=avg_conf,
                        detection_confidence=obj.confidence,
                        camera_id=cam_num,
                        camera_name=cam_name,
                        camera_location=cam_loc,
                        track_id=obj.track_id,
                        status=status,
                    )
                )

                snap_path, snap_url, snap_size = saved if saved else (None, None, 0)

                is_watchlist = False
                watchlist_entry = None
                if plate_text != "PLATE UNCERTAIN":
                    watchlist_entry = db.query(ANPRWatchlist).filter(
                        ANPRWatchlist.plate_number == plate_text,
                        ANPRWatchlist.is_active == True
                    ).first()
                    is_watchlist = watchlist_entry is not None

                anpr_rec = ANPRResult(
                    id=str(uuid.uuid4()),
                    camera_id=cam_id,
                    plate_number=plate_text,
                    vehicle_type=vehicle_type,
                    vehicle_track_id=obj.track_id,
                    camera_name=cam_name,
                    camera_location=cam_loc,
                    detection_confidence=round(obj.confidence, 3),
                    ocr_confidence=round(avg_conf, 3),
                    plate_bbox=plate_bbox_in_vehicle,
                    vehicle_bbox=obj.bbox,
                    snapshot_url=snap_url,
                    crop_url=None,
                    status="WATCHLIST_MATCH" if is_watchlist else status,
                    is_watchlist_match=is_watchlist,
                    timestamp=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                )
                db.add(anpr_rec)
                db.commit()

                await self.ws_manager.broadcast({
                    "type": "ANPR_DETECTION",
                    "anpr_id": anpr_rec.id,
                    "camera_id": cam_id,
                    "camera_number": cam_num,
                    "camera_name": cam_name,
                    "location": cam_loc,
                    "plate_number": plate_text,
                    "vehicle_type": vehicle_type,
                    "vehicle_track_id": obj.track_id,
                    "detection_confidence": round(obj.confidence, 3),
                    "ocr_confidence": round(avg_conf, 3),
                    "status": anpr_rec.status,
                    "is_watchlist_match": is_watchlist,
                    "snapshot_url": snap_url,
                    "evidence_url": snap_url,
                    "timestamp": anpr_rec.timestamp.isoformat(),
                })

                if is_watchlist and watchlist_entry:
                    severity = watchlist_entry.severity or "HIGH"
                    risk_score = 95.0 if severity == "CRITICAL" else 80.0
                    now_dt = datetime.utcnow()
                    ts_str = f"{now_dt.isoformat()}Z"

                    ev = Event(
                        id=str(uuid.uuid4()),
                        camera_id=cam_id,
                        event_type="ANPR_WATCHLIST_MATCH",
                        severity=severity,
                        risk_score=risk_score,
                        confidence=avg_conf,
                        details={
                            "plate_number": plate_text,
                            "vehicle_type": vehicle_type,
                            "track_id": f"V-{obj.track_id}",
                            "reason": watchlist_entry.reason or "Vehicle on security watchlist",
                            "camera_name": cam_name,
                            "camera_location": cam_loc,
                            "ocr_confidence": avg_conf,
                            "timestamp": ts_str,
                        },
                        timestamp=now_dt,
                        track_id=obj.track_id,
                    )
                    db.add(ev)

                    al = Alert(
                        id=str(uuid.uuid4()),
                        camera_id=cam_id,
                        event_type="ANPR_WATCHLIST_MATCH",
                        severity=severity,
                        risk_score=risk_score,
                        confidence=avg_conf,
                        status="NEW",
                        evidence_url=snap_url,
                        timestamp=now_dt,
                    )
                    db.add(al)

                    inc_num = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                    inc_anpr = Incident(
                        id=str(uuid.uuid4()),
                        incident_number=inc_num,
                        camera_id=cam_id,
                        title=f"{severity} WATCHLIST VEHICLE — {plate_text}",
                        description=f"Blacklisted vehicle with license plate '{plate_text}' ({vehicle_type}) detected at {cam_name}. Reason: {watchlist_entry.reason or 'Security Watchlist'}",
                        severity=severity,
                        risk_score=risk_score,
                        status="NEW",
                        related_event_ids=[ev.id],
                        start_time=now_dt,
                        created_at=now_dt,
                    )
                    db.add(inc_anpr)
                    al.incident_id = inc_anpr.id

                    if snap_path:
                        ev_evidence_anpr = Evidence(
                            id=str(uuid.uuid4()),
                            incident_id=inc_anpr.id,
                            camera_id=cam_id,
                            evidence_type="snapshot",
                            file_path=snap_path,
                            file_url=snap_url,
                            file_size_bytes=snap_size,
                            metadata_json={
                                "alert_id": al.id,
                                "event_id": ev.id,
                                "plate_number": plate_text,
                                "timestamp": ts_str,
                            },
                            created_at=now_dt,
                        )
                        db.add(ev_evidence_anpr)

                    db.commit()

                    await self.ws_manager.broadcast({
                        "type": "ALERT_NEW",
                        "alert_id": al.id,
                        "event_id": ev.id,
                        "incident_id": inc_anpr.id,
                        "incident_number": inc_anpr.incident_number,
                        "camera_id": cam_id,
                        "camera_number": cam_num,
                        "camera_name": cam_name,
                        "location": cam_loc,
                        "object_class": "vehicle",
                        "track_id": f"V-{obj.track_id}",
                        "confidence": avg_conf,
                        "event_type": "ANPR_WATCHLIST_MATCH",
                        "alert_title": f"🚨 WATCHLIST VEHICLE — {plate_text}",
                        "plate_number": plate_text,
                        "vehicle_type": vehicle_type,
                        "severity": severity,
                        "risk_score": risk_score,
                        "evidence_url": snap_url,
                        "timestamp": ts_str,
                        "alert": {
                            "id": al.id,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "plate_number": plate_text,
                            "vehicle_type": vehicle_type,
                            "event_type": "ANPR_WATCHLIST_MATCH",
                            "alert_title": f"🚨 WATCHLIST VEHICLE — {plate_text}",
                            "severity": severity,
                            "risk_score": risk_score,
                            "evidence_url": snap_url,
                            "timestamp": ts_str,
                        }
                    })

                    await self.ws_manager.broadcast({
                        "type": "INCIDENT_NEW",
                        "incident_id": inc_anpr.id,
                        "incident_number": inc_anpr.incident_number,
                        "event_id": ev.id,
                        "alert_id": al.id,
                        "camera_id": cam_id,
                        "camera_number": cam_num,
                        "camera_name": cam_name,
                        "location": cam_loc,
                        "title": inc_anpr.title,
                        "description": inc_anpr.description,
                        "severity": severity,
                        "risk_score": risk_score,
                        "status": inc_anpr.status,
                        "timestamp": ts_str,
                        "created_at": ts_str,
                        "evidence_url": snap_url,
                        "incident": {
                            "id": inc_anpr.id,
                            "incident_number": inc_anpr.incident_number,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "title": inc_anpr.title,
                            "description": inc_anpr.description,
                            "severity": severity,
                            "risk_score": risk_score,
                            "status": inc_anpr.status,
                            "start_time": ts_str,
                            "created_at": ts_str,
                        }
                    })

            except Exception as ex:
                logger.error(f"[ANPR] Pipeline error on {self.camera_id}: {ex}", exc_info=True)
                try: db.rollback()
                except Exception: pass
            finally:
                db.close()

    async def _create_and_broadcast_detection_evidence(self, obj: TrackedObject, frame: np.ndarray):
        if frame is None or frame.size == 0:
            return

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            cam_id = cam.id if cam else self.camera_id
            cam_num = cam.camera_id if cam else self.camera_id
            cam_name = cam.name if cam else "Surveillance Camera"
            cam_loc = cam.location or "Sector 4 BOP" if cam else "Sector 4 BOP"
            cam_lat = float(cam.latitude) if cam and cam.latitude is not None else 26.9124
            cam_lng = float(cam.longitude) if cam and cam.longitude is not None else 70.9025

            now_dt = datetime.utcnow()
            date_str = now_dt.strftime("%Y-%m-%d")
            time_str = now_dt.strftime("%H:%M:%S")
            ts_str = now_dt.isoformat()

            track_prefix = get_track_prefix(obj.class_name)
            track_str = f"{track_prefix}-{obj.track_id}"
            display_label = get_display_label(obj.class_name)

            det_record = Detection(
                id=str(uuid.uuid4()),
                camera_id=cam_id,
                class_name=obj.class_name,
                confidence=float(obj.confidence),
                bbox=obj.bbox,
                track_id=obj.track_id,
                location=cam_loc,
                latitude=cam_lat,
                longitude=cam_lng,
                timestamp=now_dt
            )
            db.add(det_record)

            loop = asyncio.get_event_loop()
            saved = await loop.run_in_executor(
                self._io_executor,
                lambda: self.evidence_mgr.save_annotated_snapshot(
                    frame=frame.copy(),
                    camera_id=cam_num,
                    bbox=obj.bbox,
                    label=obj.class_name,
                    track_id=obj.track_id,
                    confidence=obj.confidence,
                    event_type="NORMAL DETECTION",
                    camera_name=cam_name,
                    camera_location=cam_loc
                )
            )

            if not saved:
                db.commit()
                return

            file_path, file_url, file_size = saved

            ev_meta = {
                "detection_id": det_record.id,
                "camera_id": cam_id,
                "camera_number": cam_num,
                "camera_name": cam_name,
                "location": cam_loc,
                "latitude": cam_lat,
                "longitude": cam_lng,
                "object_class": obj.class_name,
                "display_label": display_label,
                "confidence": float(obj.confidence),
                "track_id": track_str,
                "event_type": "NORMAL DETECTION",
                "risk_score": 0.0,
                "severity": "INFO",
                "date": date_str,
                "time": time_str,
                "timestamp": ts_str,
                "captured_at": ts_str,
                "bbox": obj.bbox,
                "file_path": file_path,
                "file_url": file_url
            }

            ev_record = Evidence(
                id=str(uuid.uuid4()),
                camera_id=cam_id,
                evidence_type="snapshot",
                file_path=file_path,
                file_url=file_url,
                file_size_bytes=file_size,
                metadata_json=ev_meta,
                created_at=now_dt
            )
            db.add(ev_record)
            db.commit()

            image_api_url = f"/api/evidence/{ev_record.id}/image"
            ev_dict = {
                "id": ev_record.id,
                "detection_id": det_record.id,
                "camera_id": cam_id,
                "camera_number": cam_num,
                "camera_name": cam_name,
                "location": cam_loc,
                "latitude": cam_lat,
                "longitude": cam_lng,
                "object_class": obj.class_name,
                "display_label": display_label,
                "track_id": track_str,
                "confidence": float(obj.confidence),
                "event_type": "NORMAL DETECTION",
                "risk_score": 0.0,
                "severity": "INFO",
                "date": date_str,
                "time": time_str,
                "timestamp": ts_str,
                "file_url": image_api_url,
                "evidence_url": image_api_url,
            }
            await self.ws_manager.broadcast({
                "type": "EVIDENCE_NEW",
                "evidence_id": ev_record.id,
                "camera_id": cam_id,
                "camera_number": cam_num,
                "camera_name": cam_name,
                "location": cam_loc,
                "latitude": cam_lat,
                "longitude": cam_lng,
                "object_class": obj.class_name,
                "display_label": display_label,
                "track_id": track_str,
                "confidence": float(obj.confidence),
                "event_type": "NORMAL DETECTION",
                "risk_score": 0.0,
                "severity": "INFO",
                "date": date_str,
                "time": time_str,
                "timestamp": ts_str,
                "file_url": image_api_url,
                "evidence": ev_dict,
            })
        except Exception as ex:
            logger.error(f"[EVIDENCE ERROR] on {self.camera_id}: {ex}")
            try: db.rollback()
            except Exception: pass
        finally:
            db.close()

    async def _evaluate_surveillance_rules(self, confirmed_objs: List[TrackedObject], frame: Optional[np.ndarray] = None, pre_frame: Optional[np.ndarray] = None):
        if not confirmed_objs:
            return

        active_track_ids = set(obj.track_id for obj in confirmed_objs)
        stale_keys = [k for k in self.track_zone_states.keys() if k[0] == self.camera_id and k[1] not in active_track_ids]
        for sk in stale_keys:
            del self.track_zone_states[sk]

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            if not cam:
                return

            zones = db.query(CameraZone).filter(
                (CameraZone.camera_id == cam.id) | (CameraZone.camera_id == cam.camera_id) | (CameraZone.camera_id == self.camera_id),
                CameraZone.is_active == True
            ).all()
            if not zones:
                return

            now_sec = time.time()
            hour_now = datetime.utcnow().hour
            is_night = (hour_now >= 18 or hour_now < 6)

            for zone in zones:
                coords = zone.coordinates
                if not coords or len(coords) < 3:
                    continue

                polygon = [(p[0], p[1]) for p in coords]

                for obj in confirmed_objs:
                    nx, ny, nw, nh = obj.bbox
                    test_points = [
                        (nx + nw / 2.0, ny + nh),        # Bottom-center foot point
                        (nx + nw / 2.0, ny + nh / 2.0),  # Centroid
                        (nx + nw / 2.0, ny),             # Top-center head point
                        (nx, ny),                        # Top-left
                        (nx + nw, ny),                   # Top-right
                        (nx, ny + nh),                   # Bottom-left
                        (nx + nw, ny + nh)               # Bottom-right
                    ]
                    inside = any(point_in_polygon(pt, polygon) for pt in test_points) or any(
                        nx <= vx <= nx + nw and ny <= vy <= ny + nh for vx, vy in polygon
                    )
                    logger.debug(f"[ZONE CHECK] camera={self.camera_id} track_id={obj.track_id} zone='{zone.name}' inside={inside}")

                    state_key = (self.camera_id, obj.track_id, zone.id)
                    if state_key not in self.track_zone_states:
                        self.track_zone_states[state_key] = {
                            "is_inside": False,
                            "entry_time": 0.0,
                            "intrusion_event_generated": False,
                            "loitering_event_generated": False
                        }
                    state = self.track_zone_states[state_key]

                    # OUTSIDE -> INSIDE
                    if inside and not state["is_inside"]:
                        state["is_inside"] = True
                        state["entry_time"] = now_sec
                        state["intrusion_event_generated"] = False
                        state["loitering_event_generated"] = False

                    # INSIDE -> OUTSIDE
                    elif not inside and state["is_inside"]:
                        state["is_inside"] = False
                        state["intrusion_event_generated"] = False
                        state["loitering_event_generated"] = False

                    if not state["is_inside"]:
                        continue

                    rules = db.query(ZoneRule).filter(ZoneRule.zone_id == zone.id, ZoneRule.enabled == True).all()
                    if not rules:
                        class FallbackRule:
                            object_type = "all"
                            min_confidence = 0.20
                            cooldown_sec = 5
                            loitering_threshold_sec = 10
                            severity = "HIGH"
                        rules = [FallbackRule()]

                    for rule in rules:
                        if rule.object_type != "all" and rule.object_type != obj.class_name:
                            continue
                        if obj.confidence < rule.min_confidence:
                            continue

                        cooldown_window = rule.cooldown_sec if (rule.cooldown_sec and rule.cooldown_sec > 0) else ALERT_COOLDOWN_SEC
                        loitering_thresh = rule.loitering_threshold_sec if (rule.loitering_threshold_sec and rule.loitering_threshold_sec > 0) else LOITERING_THRESHOLD_SEC
                        dwell_inside_sec = now_sec - state["entry_time"]

                        # Check 1: Restricted Zone Intrusion
                        # - On FIRST ENTRY: fire immediately (intrusion_event_generated == False)
                        # - CONTINUOUSLY INSIDE: re-fire after every cooldown window
                        #   (no movement_state guard — the object IS in a restricted zone, alert regardless)
                        event_type = "RESTRICTED_ZONE_INTRUSION"
                        dedup_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_{event_type}"
                        time_since_last_alert = now_sec - self.last_alert_times.get(dedup_key, 0)

                        if time_since_last_alert >= cooldown_window:
                            self.last_alert_times[dedup_key] = now_sec
                            state["intrusion_event_generated"] = True
                            await self._create_and_broadcast_alert(
                                db, cam, zone, obj, event_type, is_night, is_loitering=False, frame=frame, pre_frame=pre_frame
                            )

                        # Check 2: Zone Loitering
                        if dwell_inside_sec >= loitering_thresh and not state["loitering_event_generated"]:
                            event_type = "ZONE_LOITERING"
                            dedup_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_{event_type}"
                            if now_sec - self.last_alert_times.get(dedup_key, 0) >= cooldown_window:
                                self.last_alert_times[dedup_key] = now_sec
                                state["loitering_event_generated"] = True
                                await self._create_and_broadcast_alert(
                                    db, cam, zone, obj, event_type, is_night, is_loitering=True, frame=frame, pre_frame=pre_frame
                                )

        except Exception as ex:
            logger.error(f"Error in rule processing on {self.camera_id}: {ex}")
        finally:
            db.close()

    async def _create_and_broadcast_alert(
        self, db: Any, cam: Any, zone: Any, obj: TrackedObject,
        event_type: str, is_night: bool, is_loitering: bool,
        frame: Optional[np.ndarray] = None,
        pre_frame: Optional[np.ndarray] = None
    ):
        conditions = {
            "night_mode": is_night,
            "restricted_zone": True,
            "fence_crossing": True,
            "loitering": is_loitering
        }
        res = self.scorer.calculate_score(conditions)
        risk_score = max(75.0, res["risk_score"])
        severity = "CRITICAL" if risk_score >= 85.0 else "HIGH"

        zone_id = zone.id if zone else None
        zone_name = zone.name if zone else "Perimeter Boundary"

        # Record cooldown timestamp for deduplication
        dedup_key = f"{self.camera_id}_{obj.track_id}_{zone_id}_{event_type}"
        self.last_alert_times[dedup_key] = time.time()

        now_dt = datetime.utcnow()
        date_str = now_dt.strftime("%Y-%m-%d")
        time_str = now_dt.strftime("%H:%M:%S")
        ts_str = f"{now_dt.isoformat()}Z"

        ev = Event(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            zone_id=zone_id,
            event_type=event_type,
            severity=severity,
            risk_score=risk_score,
            confidence=obj.confidence,
            details={
                "conditions": conditions,
                "breakdown": res["breakdown"],
                "track_id": obj.track_id,
                "zone_id": zone_id,
                "zone_name": zone_name,
                "camera_name": cam.name,
                "camera_number": cam.camera_id,
                "location": cam.location or "Campus Perimeter",
                "timestamp": ts_str,
            },
            timestamp=now_dt,
            track_id=obj.track_id
        )
        db.add(ev)

        al = Alert(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            event_type=event_type,
            severity=severity,
            risk_score=risk_score,
            confidence=obj.confidence,
            status="NEW",
            timestamp=now_dt
        )
        db.add(al)

        inc_id = None
        if risk_score >= 70.0:
            inc_num = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
            inc = Incident(
                id=str(uuid.uuid4()),
                incident_number=inc_num,
                camera_id=cam.id,
                title=f"{severity} {event_type} in {zone_name}",
                description=f"Track #{obj.track_id} ({obj.class_name}) triggered {event_type} in {zone_name} ({cam.name})",
                severity=severity,
                risk_score=risk_score,
                status="NEW",
                start_time=now_dt,
                created_at=now_dt
            )
            db.add(inc)
            inc_id = inc.id
            al.incident_id = inc.id

        file_path, file_url, file_size = None, None, 0
        ev_record = None
        track_prefix = get_track_prefix(obj.class_name)
        track_str = f"{track_prefix}-{obj.track_id}"
        display_label = get_display_label(obj.class_name)
        cam_lat = float(cam.latitude) if cam.latitude is not None else 26.9124
        cam_lng = float(cam.longitude) if cam.longitude is not None else 70.9025
        cam_loc = cam.location or "Campus Perimeter"

        det_record = Detection(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            class_name=obj.class_name,
            confidence=float(obj.confidence),
            bbox=obj.bbox,
            track_id=obj.track_id,
            location=cam_loc,
            latitude=cam_lat,
            longitude=cam_lng,
            timestamp=now_dt
        )
        db.add(det_record)

        if frame is not None:
            loop = asyncio.get_event_loop()
            saved_seq = await loop.run_in_executor(
                self._io_executor,
                lambda: self.evidence_mgr.save_evidence_sequence(
                    event_frame=frame.copy(),
                    camera_id=cam.camera_id,
                    bbox=obj.bbox,
                    label=obj.class_name,
                    track_id=obj.track_id,
                    confidence=obj.confidence,
                    event_type=f"{event_type} ({zone_name})",
                    camera_name=cam.name,
                    camera_location=cam_loc,
                    pre_frame=pre_frame
                )
            )
            if saved_seq:
                file_path = saved_seq["file_path"]
                file_url = saved_seq["file_url"]
                file_size = saved_seq["file_size"]
                sequence_urls = saved_seq.get("sequence_urls", [file_url])
                al.evidence_url = file_url

                ev_meta = {
                    "detection_id": det_record.id,
                    "camera_id": cam.id,
                    "camera_number": cam.camera_id,
                    "camera_name": cam.name,
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "location": cam_loc,
                    "latitude": cam_lat,
                    "longitude": cam_lng,
                    "object_class": obj.class_name,
                    "display_label": display_label,
                    "confidence": float(obj.confidence),
                    "track_id": track_str,
                    "event_type": event_type,
                    "risk_score": float(risk_score),
                    "severity": severity,
                    "date": date_str,
                    "time": time_str,
                    "timestamp": ts_str,
                    "captured_at": ts_str,
                    "bbox": obj.bbox,
                    "alert_id": al.id,
                    "event_id": ev.id,
                    "file_path": file_path,
                    "file_url": file_url,
                    "sequence_urls": sequence_urls,
                }
                ev_record = Evidence(
                    id=str(uuid.uuid4()),
                    incident_id=inc_id,
                    camera_id=cam.id,
                    evidence_type="snapshot",
                    file_path=file_path,
                    file_url=file_url,
                    file_size_bytes=file_size,
                    metadata_json=ev_meta,
                    created_at=now_dt,
                )
                db.add(ev_record)
                logger.info(f"[EVIDENCE_SAVED] camera={cam.camera_id} alert_id={al.id} url={file_url} size={file_size}")

        db.commit()
        logger.info(f"[SECURITY_EVENT_CREATED] camera={cam.camera_id} event_id={ev.id} type={event_type} track_id={track_str} risk={risk_score}")
        logger.info(f"[ALERT_CREATED] camera={cam.camera_id} alert_id={al.id} event_id={ev.id} severity={severity}")
        if inc_id:
            logger.info(f"[INCIDENT_CREATED] camera={cam.camera_id} incident_id={inc_id} alert_id={al.id}")

        # Broadcast ALERT_NEW (triggers alarm sound & updates live dashboard)
        alert_title = f"🚨 {event_type.replace('_', ' ')} — {zone_name} ({cam.name})"
        evidence_api_url = f"/api/evidence/{ev_record.id}/image" if ev_record else file_url
        await self.ws_manager.broadcast({
            "type": "ALERT_NEW",
            "alert_id": al.id,
            "event_id": ev.id,
            "incident_id": inc_id,
            "incident_number": inc.incident_number if (inc_id and inc) else None,
            "camera_id": cam.id,
            "camera_number": cam.camera_id,
            "camera_name": cam.name,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "location": cam_loc,
            "latitude": cam_lat,
            "longitude": cam_lng,
            "object_class": obj.class_name,
            "track_id": track_str,
            "confidence": obj.confidence,
            "event_type": event_type,
            "alert_title": alert_title,
            "risk_score": risk_score,
            "severity": severity,
            "timestamp": ts_str,
            "evidence_url": evidence_api_url,
            "alert": {
                "id": al.id,
                "camera_id": cam.id,
                "camera_number": cam.camera_id,
                "camera_name": cam.name,
                "zone_id": zone_id,
                "zone_name": zone_name,
                "location": cam_loc,
                "latitude": cam_lat,
                "longitude": cam_lng,
                "object_class": obj.class_name,
                "track_id": track_str,
                "confidence": obj.confidence,
                "event_type": event_type,
                "alert_title": alert_title,
                "severity": severity,
                "risk_score": risk_score,
                "evidence_url": evidence_api_url,
                "timestamp": ts_str,
            },
        })

        if inc_id and inc:
            await self.ws_manager.broadcast({
                "type": "INCIDENT_NEW",
                "incident_id": inc.id,
                "incident_number": inc.incident_number,
                "event_id": ev.id,
                "alert_id": al.id,
                "camera_id": cam.id,
                "camera_number": cam.camera_id,
                "camera_name": cam.name,
                "location": cam_loc,
                "title": inc.title,
                "description": inc.description,
                "severity": severity,
                "risk_score": risk_score,
                "status": inc.status,
                "timestamp": ts_str,
                "created_at": ts_str,
                "evidence_url": evidence_api_url,
                "incident": {
                    "id": inc.id,
                    "incident_number": inc.incident_number,
                    "camera_id": cam.id,
                    "camera_number": cam.camera_id,
                    "camera_name": cam.name,
                    "title": inc.title,
                    "description": inc.description,
                    "severity": severity,
                    "risk_score": risk_score,
                    "status": inc.status,
                    "start_time": ts_str,
                    "created_at": ts_str,
                }
            })

        logger.info(f"[ALERT CREATED] alert_id={al.id} event={event_type} camera={cam.camera_id} track={obj.track_id} zone='{zone_name}' risk_score={risk_score}")
        logger.info(f"[WEBSOCKET BROADCAST] type=ALERT_NEW alert_id={al.id} camera={cam.camera_id} event={event_type}")

