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
from ai_engine.anpr.anpr_engine import ANPREngine, save_anpr_evidence_snapshot, VEHICLE_TYPE_MAP, VEHICLE_CLASSES
from event_engine.risk.scorer import OperationalRiskScorer
from storage.evidence_manager import EvidenceManager
from database.connection import SessionLocal
from database.schema import (
    Camera, CameraZone, ZoneRule, Event, Alert, Incident, Evidence,
    FaceDetection, FaceWatchlist, ANPRResult, ANPRWatchlist, Detection, AuditBlock,
    WatchlistMovementChain, WatchlistMovementEvent
)
from backend.blockchain_audit import create_audit_block

from backend.config import (
    DETECTION_CONFIDENCE_THRESHOLD, LOITERING_THRESHOLD_SEC, ALERT_COOLDOWN_SEC, EVIDENCE_CAPTURE_INTERVAL_SEC,
    ANPR_DUPLICATE_COOLDOWN_SEC, UNKNOWN_PERSON_ALERT_REFIRE_SEC, WATCHLIST_FACE_ALERT_REFIRE_SEC,
    ZONE_INTRUSION_COOLDOWN_SEC, ZONE_LOITERING_COOLDOWN_SEC, ZONE_EXIT_DEBOUNCE_FRAMES, FACE_RECORD_COOLDOWN_SEC
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
    def __init__(self, camera_id: str, websocket_manager: Any):
        self.camera_id = camera_id
        self.ws_manager = websocket_manager
        self.detector = RealAIDetector(conf_threshold=DETECTION_CONFIDENCE_THRESHOLD)
        self.tracker = MultiObjectTracker(camera_id=self.camera_id)
        self.face_engine = RealFaceEngine()
        self.face_tracker = FaceTracker(camera_id=self.camera_id)
        self.anpr_engine = ANPREngine()
        self.scorer = OperationalRiskScorer()
        self.evidence_mgr = EvidenceManager()
        self._agent_executor: Optional[ThreadPoolExecutor] = None
        self._cached_cam_meta: Optional[Dict[str, Any]] = None
        self._cam_meta_time: float = 0.0
        self._cached_watchlist: List[Any] = []
        self._watchlist_cache_time: float = 0.0
        self.last_alert_times: Dict[str, float] = {}
        self.last_detection_snapshot_times: Dict[Tuple[str, int, str], float] = {}
        self.last_face_process_time = 0.0
        self.last_anpr_process_times: Dict[Tuple[str, int], float] = {}
        self.last_anpr_db_times: Dict[Tuple[str, str], float] = {}
        self._anpr_in_flight: set = set()
        self.vehicle_record_state: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.last_face_db_record_times: Dict[Tuple[str, int, str, str], float] = {}
        self.active_faces: List[Dict[str, Any]] = []
        self.active_anpr: List[Dict[str, Any]] = []
        self.track_zone_states: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        # active_alert_ids: one canonical alert per (camera, track, zone, event_type)
        # while the violation is ongoing. Cleared when the track exits the zone.
        # Prevents creating new Alert+Incident+Evidence on every cooldown tick.
        self.active_alert_ids: Dict[str, str] = {}
        # face_alert_state: per (camera, face_track_id, event_type) — tracks whether
        # an alert has already been raised for this face track and when it was raised.
        # Format: key -> {"alert_id": str, "created_at": float}
        self.face_alert_state: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        # Zone-level cooldown enforcement: (camera_id, zone_id, event_type) -> float timestamp
        self.zone_last_alert_times: Dict[Tuple[str, str, str], float] = {}
        # Consecutive outside frames for exit debouncing: (camera_id, track_id, zone_id) -> int count
        self.outside_frame_counts: Dict[Tuple[str, int, str], int] = {}
        # Suppression caches for operator-deleted items: key -> expiration timestamp
        self.suppressed_alert_keys: Dict[str, float] = {}
        self.suppressed_face_keys: Dict[Any, float] = {}
        # Database query caching to prevent SQLite overhead during live streaming
        self._cached_cam_meta: Optional[Dict[str, Any]] = None
        self._cam_meta_time: float = 0.0
        self._cached_watchlist: Optional[List[Any]] = None
        self._watchlist_cache_time: float = 0.0
        self._cached_zones: Optional[List[Tuple[Any, List[Any]]]] = None
        self._zones_cache_time: float = 0.0
        self._cached_anpr_watchlist: Optional[List[Any]] = None
        self._anpr_watchlist_cache_time: float = 0.0

    @property
    def agent_executor(self) -> ThreadPoolExecutor:
        if self._agent_executor is None or getattr(self._agent_executor, "_shutdown", False):
            self._agent_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"ai_{self.camera_id}")
        return self._agent_executor

    @agent_executor.setter
    def agent_executor(self, value: Optional[ThreadPoolExecutor]):
        self._agent_executor = value

    def _get_camera_meta(self, db) -> Dict[str, Any]:
        now = time.time()
        if self._cached_cam_meta and (now - self._cam_meta_time < 10.0):
            return self._cached_cam_meta
        cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
        self._cached_cam_meta = {
            "id": cam.id if cam else self.camera_id,
            "camera_id": cam.camera_id if cam else self.camera_id,
            "name": cam.name if (cam and cam.name) else f"Camera {self.camera_id}",
            "location": (cam.location.strip() if (cam and cam.location and cam.location.strip()) else "LOCATION NOT CONFIGURED"),
            "latitude": float(cam.latitude) if (cam and cam.latitude is not None) else None,
            "longitude": float(cam.longitude) if (cam and cam.longitude is not None) else None
        }
        self._cam_meta_time = now
        return self._cached_cam_meta

    def _get_watchlist_records(self, db) -> List[Any]:
        now = time.time()
        if self._cached_watchlist and (now - self._watchlist_cache_time < 5.0):
            return self._cached_watchlist
        records = db.query(FaceWatchlist).filter(FaceWatchlist.is_active == True).all()
        cached = []
        for r in records:
            _ = (r.id, r.name, r.person_id, r.category, r.embedding, r.is_active)
            try:
                db.expunge(r)
            except Exception:
                pass
            cached.append(r)
        self._cached_watchlist = cached
        self._watchlist_cache_time = now
        return self._cached_watchlist

    def _get_zones_and_rules(self, db) -> List[Tuple[Any, List[Any]]]:
        """
        Retrieves active CameraZones and their ZoneRules for this camera with a 30s in-memory cache.
        Eliminates repeated SQLite queries on every processed frame.
        """
        now = time.time()
        if self._cached_zones and (now - self._zones_cache_time < 30.0):
            return self._cached_zones

        cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
        if not cam:
            return []

        zones = db.query(CameraZone).filter(
            (CameraZone.camera_id == cam.id) | (CameraZone.camera_id == cam.camera_id) | (CameraZone.camera_id == self.camera_id),
            CameraZone.is_active == True
        ).all()

        cached_zones_with_rules = []
        for zone in zones:
            rules = db.query(ZoneRule).filter(ZoneRule.zone_id == zone.id, ZoneRule.enabled == True).all()
            for r in rules:
                try: db.expunge(r)
                except Exception: pass
            try: db.expunge(zone)
            except Exception: pass
            cached_zones_with_rules.append((zone, rules))

        self._cached_zones = cached_zones_with_rules
        self._zones_cache_time = now
        return self._cached_zones

    def _get_anpr_watchlist_records(self, db) -> List[Any]:
        """
        Retrieves active ANPRWatchlist records with a 10s in-memory cache.
        Eliminates repeated SQLite queries on every vehicle detection frame.
        """
        now = time.time()
        if self._cached_anpr_watchlist and (now - self._anpr_watchlist_cache_time < 10.0):
            return self._cached_anpr_watchlist
        records = db.query(ANPRWatchlist).filter(ANPRWatchlist.is_active == True).all()
        cached = []
        for r in records:
            try: db.expunge(r)
            except Exception: pass
            cached.append(r)
        self._cached_anpr_watchlist = cached
        self._anpr_watchlist_cache_time = now
        return self._cached_anpr_watchlist

    async def _record_watchlist_movement(
        self,
        db: Any,
        track: FaceTrack,
        cam_meta: Dict[str, Any],
        now_dt: datetime,
        evidence_id: Optional[str] = None,
        evidence_url: Optional[str] = None,
        crop_url: Optional[str] = None
    ) -> Optional[WatchlistMovementEvent]:
        """
        Records a confirmed Watchlist Person detection into their chronological movement chain.
        - Exactly one WatchlistMovementChain per watchlist_person_id (face_watchlist.id).
        - Aggregates multi-frame detections at a single camera into one observation session
          (first_seen_at to last_seen_at) rather than creating duplicate sequence nodes.
        - Creates a new WatchlistMovementEvent (incrementing sequence_number) only when transitioning
          to another camera or returning after a prolonged absence (> 120 seconds).
        - Broadcasts WATCHLIST_MOVEMENT_UPDATE via WebSocket with authoritative runtime data.
        """
        if not track.identity_id or track.recognition_status != "KNOWN":
            return None

        now_sec = time.time()
        person_db_id = track.identity_id
        person_name = track.identity_name or "WATCHLIST SUBJECT"
        person_id_badge = getattr(track, "person_id", None) or f"ID-{person_db_id[:8]}"
        person_cat = (getattr(track, "category", "") or "WATCHLIST").upper()

        cam_id = cam_meta["id"]
        cam_num = cam_meta["camera_id"]
        cam_name = cam_meta["name"]
        cam_loc = cam_meta.get("location") or "LOCATION NOT CONFIGURED"
        cam_lat = cam_meta.get("latitude")
        cam_lon = cam_meta.get("longitude")

        conf = float(track.recognition_confidence)
        similarity = float(getattr(track, "raw_similarity", track.recognition_confidence))

        # 1. Fetch or create WatchlistMovementChain for this person
        chain = db.query(WatchlistMovementChain).filter(
            WatchlistMovementChain.watchlist_person_id == person_db_id
        ).first()

        if not chain:
            chain = WatchlistMovementChain(
                id=str(uuid.uuid4()),
                watchlist_person_id=person_db_id,
                person_name=person_name,
                person_id=person_id_badge,
                category=person_cat,
                current_camera_id=cam_id,
                current_camera_number=cam_num,
                current_camera_name=cam_name,
                current_location=cam_loc,
                current_latitude=cam_lat,
                current_longitude=cam_lon,
                status="ACTIVE",
                first_detected_at=now_dt,
                last_detected_at=now_dt,
                total_detections=0,
                created_at=now_dt,
                updated_at=now_dt
            )
            db.add(chain)
            db.flush()

        # 2. Get latest event in this chain
        latest_event = db.query(WatchlistMovementEvent).filter(
            WatchlistMovementEvent.chain_id == chain.id
        ).order_by(WatchlistMovementEvent.sequence_number.desc()).first()

        event_to_broadcast = None
        is_new_node = False

        same_camera = (
            latest_event is not None and
            (latest_event.camera_id == cam_id or latest_event.camera_number == cam_num)
        )

        if same_camera:
            # Consolidate all continuous observations from the same camera into one visit session
            latest_event.last_seen_at = now_dt
            latest_event.confidence = max(latest_event.confidence, conf)
            latest_event.face_similarity = max(latest_event.face_similarity, similarity)
            if evidence_id:
                latest_event.evidence_id = evidence_id
            if evidence_url:
                latest_event.evidence_url = evidence_url
            if crop_url:
                latest_event.crop_url = crop_url

            chain.last_detected_at = now_dt
            chain.status = "ACTIVE"
            chain.total_detections += 1
            chain.updated_at = now_dt
            event_to_broadcast = latest_event
        else:
            # Create NEW sequence node only when transitioning to a different real camera
            next_seq = (latest_event.sequence_number + 1) if latest_event else 1
            new_event = WatchlistMovementEvent(
                id=str(uuid.uuid4()),
                chain_id=chain.id,
                sequence_number=next_seq,
                watchlist_person_id=person_db_id,
                watchlist_person_name=person_name,
                camera_id=cam_id,
                camera_number=cam_num,
                camera_name=cam_name,
                location=cam_loc,
                latitude=cam_lat,
                longitude=cam_lon,
                first_seen_at=now_dt,
                last_seen_at=now_dt,
                timestamp=now_dt,
                confidence=conf,
                face_similarity=similarity,
                track_id=track.track_id,
                evidence_id=evidence_id,
                evidence_url=evidence_url,
                crop_url=crop_url,
                created_at=now_dt
            )
            db.add(new_event)

            chain.current_camera_id = cam_id
            chain.current_camera_number = cam_num
            chain.current_camera_name = cam_name
            chain.current_location = cam_loc
            chain.current_latitude = cam_lat
            chain.current_longitude = cam_lon
            chain.last_detected_at = now_dt
            chain.status = "ACTIVE"
            chain.total_detections += 1
            chain.updated_at = now_dt

            event_to_broadcast = new_event
            is_new_node = True

        db.commit()

        # 3. Broadcast real-time update via WebSocket
        # Immediate broadcast if new node; throttled every 2s if same-camera session update
        last_bcast = getattr(self, "_last_movement_broadcast_times", {}).get(person_db_id, 0.0)
        if is_new_node or (now_sec - last_bcast >= 2.0):
            if not hasattr(self, "_last_movement_broadcast_times"):
                self._last_movement_broadcast_times = {}
            self._last_movement_broadcast_times[person_db_id] = now_sec

            payload = {
                "type": "WATCHLIST_MOVEMENT_UPDATE",
                "chain_id": chain.id,
                "watchlist_person_id": chain.watchlist_person_id,
                "person_name": chain.person_name,
                "person_id": chain.person_id,
                "category": chain.category,
                "status": chain.status,
                "current_camera_id": chain.current_camera_id,
                "current_camera_number": chain.current_camera_number,
                "current_camera_name": chain.current_camera_name,
                "current_location": chain.current_location or "LOCATION NOT CONFIGURED",
                "current_latitude": chain.current_latitude,
                "current_longitude": chain.current_longitude,
                "last_detected_at": chain.last_detected_at.isoformat() + "Z",
                "total_detections": chain.total_detections,
                "event": {
                    "id": event_to_broadcast.id,
                    "sequence_number": event_to_broadcast.sequence_number,
                    "watchlist_person_id": event_to_broadcast.watchlist_person_id,
                    "watchlist_person_name": event_to_broadcast.watchlist_person_name,
                    "camera_id": event_to_broadcast.camera_id,
                    "camera_number": event_to_broadcast.camera_number,
                    "camera_name": event_to_broadcast.camera_name,
                    "location": event_to_broadcast.location or "LOCATION NOT CONFIGURED",
                    "latitude": event_to_broadcast.latitude,
                    "longitude": event_to_broadcast.longitude,
                    "first_seen_at": event_to_broadcast.first_seen_at.isoformat() + "Z",
                    "last_seen_at": event_to_broadcast.last_seen_at.isoformat() + "Z",
                    "timestamp": event_to_broadcast.timestamp.isoformat() + "Z",
                    "date": event_to_broadcast.timestamp.strftime("%Y-%m-%d"),
                    "time": event_to_broadcast.timestamp.strftime("%H:%M:%S"),
                    "confidence": event_to_broadcast.confidence,
                    "face_similarity": event_to_broadcast.face_similarity,
                    "track_id": event_to_broadcast.track_id,
                    "evidence_id": event_to_broadcast.evidence_id,
                    "evidence_url": event_to_broadcast.evidence_url,
                    "crop_url": event_to_broadcast.crop_url
                }
            }
            if self.ws_manager:
                try:
                    await self.ws_manager.broadcast(payload)
                except Exception as ws_err:
                    logger.warning(f"[WATCHLIST_MOVEMENT] WebSocket broadcast error: {ws_err}")
            logger.info(
                f"📍 [WATCHLIST_MOVEMENT] person={chain.person_name} cam={cam_num} "
                f"seq={event_to_broadcast.sequence_number} is_new_node={is_new_node}"
            )

        return event_to_broadcast

    def cleanup_live_session(self):
        """
        Cleans up all temporary live-session data when camera stream stops or disconnects.
        Historical records in database remain intact.
        """
        self.active_faces = []
        self.active_anpr = []
        self.tracker.tracks.clear()
        self.tracker.disappeared.clear()
        self.tracker.class_votes.clear()
        self.tracker.recent_lost_tracks.clear()
        self.face_tracker.tracks.clear()
        self.face_alert_state.clear()
        self.track_zone_states.clear()
        self.active_alert_ids.clear()
        self.outside_frame_counts.clear()
        self.last_face_db_record_times.clear()
        self.last_detection_snapshot_times.clear()
        self.last_anpr_process_times.clear()
        self.last_anpr_db_times.clear()
        self._anpr_in_flight.clear()
        self.vehicle_record_state.clear()
        if hasattr(self.anpr_engine, 'tracker') and hasattr(self.anpr_engine.tracker, '_tracks'):
            with self.anpr_engine.tracker._lock:
                self.anpr_engine.tracker._tracks.clear()
        self.last_face_process_time = 0.0
        logger.info(f"[CAMERA_CLEANUP] Live surveillance, vehicle ANPR & face session reset for camera={self.camera_id}")

    def shutdown(self):
        """Safely terminates background execution and releases resources."""
        self.cleanup_live_session()
        try:
            if self._agent_executor is not None:
                self._agent_executor.shutdown(wait=False)
                self._agent_executor = None
        except Exception:
            self._agent_executor = None

    async def process_frame(self, frame: np.ndarray, loop_start_time: float, pre_frame: Optional[np.ndarray] = None) -> Tuple[List[TrackedObject], float, float, List[Dict[str, Any]], List[Dict[str, Any]]]:
        if frame is None or frame.size == 0:
            return [], 0.0, 0.0, [], []

        # 1. Run Real AI Model Inference (YOLOv8) asynchronously on dedicated camera executor
        loop = asyncio.get_running_loop()
        raw_detections = await loop.run_in_executor(
            self.agent_executor,
            self.detector.detect,
            frame,
            self.camera_id
        )

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
        End-to-end Face Intelligence Pipeline:
        LIVE FRAME → YuNet Face Detection → Landmark Alignment → Quality Filter
        → SFace 128-d Feature Embedding → Watchlist Verification (Cosine Similarity)
        → KNOWN / UNKNOWN / UNCERTAIN Classification → SQLite FaceDetection Persistence
        → Watchlist Alert Generation with Deduplication.
        """
        now_sec = time.time()
        # Sample face detection inference at ~5 Hz (every 200ms) to maintain optimal real-time performance
        if now_sec - self.last_face_process_time < 0.20 and self.active_faces:
            return self.active_faces

        self.last_face_process_time = now_sec
        logger.info(f"[FACE] inference started camera={self.camera_id}")

        # 1. YuNet Face Detection directly on the live video frame (independent of YOLO object boxes)
        loop = asyncio.get_event_loop()
        detected_faces: List[DetectedFace] = await loop.run_in_executor(
            self.agent_executor,
            lambda: self.face_engine.detect_faces(frame)
        )

        logger.info(f"[FACE] faces detected: {len(detected_faces)} camera={self.camera_id}")

        # 2. Multi-Frame Spatial Face Tracking
        confirmed_tracks: List[FaceTrack] = self.face_tracker.update(detected_faces)
        if not confirmed_tracks:
            self.active_faces = []
            return []

        db = SessionLocal()
        try:
            cam_meta = self._get_camera_meta(db)
            cam_id = cam_meta["id"]
            cam_num = cam_meta["camera_id"]
            cam_name = cam_meta["name"]
            cam_loc = cam_meta["location"]

            watchlist_records = self._get_watchlist_records(db)

            faces_payload = []
            for track in confirmed_tracks:
                logger.info(f"[FACE] face quality: {track.quality_score:.2f} track={track.track_id}")
                # 3. SFace Feature Extraction & Watchlist Comparison
                track = self.face_engine.evaluate_track_recognition(frame, track, watchlist_records)
                logger.info(f"[FACE] embedding generated track={track.track_id}")
                logger.info(f"[FACE] recognition result track={track.track_id} status={track.recognition_status} identity={track.identity_name or 'UNKNOWN'} similarity={track.recognition_confidence:.3f}")

                is_known = (track.recognition_status == "KNOWN" and track.identity_name is not None)
                p_badge = getattr(track, "person_id", None) or (f"ID-{track.track_id}")
                p_cat = (getattr(track, "category", "") or "UNKNOWN").upper()

                # Determine security category
                is_verified_student_staff = is_known and (p_cat in VERIFIED_CATEGORIES)
                is_threat_watchlist = is_known and (p_cat in THREAT_CATEGORIES)
                is_unknown_person = not is_known
                is_uncertain = not is_known and ((track.recognition_status == "UNCERTAIN") or (not getattr(track, "is_high_quality", True) and track.quality_score < 0.35))

                face_data = {
                    "track_id": track.track_id,
                    "bbox": track.bbox_norm,
                    "landmarks": track.landmarks,
                    "confidence": track.confidence,
                    "quality_score": track.quality_score,
                    "recognition_status": "VERIFIED" if is_verified_student_staff else "KNOWN" if is_threat_watchlist else "UNCERTAIN" if is_uncertain else "UNKNOWN",
                    "identity_id": track.identity_id,
                    "identity_name": track.identity_name if is_known else "UNKNOWN / VERIFICATION REQUIRED",
                    "person_id": p_badge if is_known else None,
                    "category": p_cat if is_known else "UNKNOWN",
                    "recognition_confidence": track.recognition_confidence,
                    "raw_similarity": getattr(track, "raw_similarity", 0.0)
                }
                faces_payload.append(face_data)

                # ── Per-track FaceDetection DB record throttle & deduplication ────────
                # Check suppression cache (if operator recently deleted detection for this specific track_id or specific identity)
                track_face_suppressed = (
                    self.suppressed_face_keys.get((self.camera_id, track.track_id), 0) > now_sec or
                    (is_known and track.identity_name and self.suppressed_face_keys.get((self.camera_id, track.identity_name), 0) > now_sec)
                )
                if track_face_suppressed:
                    continue

                track_key = (self.camera_id, track.track_id)
                prev_status = getattr(track, "_last_db_status", None)
                is_first_save = not getattr(track, "_has_db_record", False)
                status_changed = (prev_status is not None and prev_status != track.recognition_status)
                time_since_save = now_sec - self.last_face_db_record_times.get(track_key, 0)
                cooldown_passed = (time_since_save >= FACE_RECORD_COOLDOWN_SEC)

                # Persist new database record when:
                # 1. A new face track appears (first time seen)
                # 2. Recognition status changes (e.g. UNKNOWN -> KNOWN)
                # 3. Track returns after absence (new track_id)
                # 4. Configured cooldown interval (FACE_RECORD_COOLDOWN_SEC) has elapsed
                do_fd_record = is_first_save or status_changed or cooldown_passed
                if not do_fd_record and is_known:
                    last_mv_sec = getattr(self, "_last_movement_update_times", {}).get((self.camera_id, track.identity_id), 0.0)
                    if (now_sec - last_mv_sec) >= 2.0:
                        if not hasattr(self, "_last_movement_update_times"):
                            self._last_movement_update_times = {}
                        self._last_movement_update_times[(self.camera_id, track.identity_id)] = now_sec
                        await self._record_watchlist_movement(
                            db=db,
                            track=track,
                            cam_meta=cam_meta,
                            now_dt=datetime.utcnow(),
                            evidence_id=getattr(track, "_last_evidence_id", None),
                            evidence_url=getattr(track, "_last_snap_url", None),
                            crop_url=getattr(track, "_last_crop_url", None)
                        )

                if do_fd_record:
                    track._has_db_record = True
                    track._last_db_status = track.recognition_status
                    self.last_face_db_record_times[track_key] = now_sec

                    # Offload crop and snapshot saving to background thread
                    crop_saved = await loop.run_in_executor(
                        self.agent_executor,
                        lambda: self.face_engine.save_face_crop(frame.copy(), track.bbox_norm, f"{cam_num}_F{track.track_id}")
                    )
                    snap_saved = await loop.run_in_executor(
                        self.agent_executor,
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

                    track._last_snap_url = snap_url
                    track._last_crop_url = crop_url
                    track._last_snap_path = snap_path
                    track._last_snap_size = snap_size

                    now_dt = datetime.utcnow()
                    ts_str = f"{now_dt.isoformat()}Z"

                    logger.info(
                        f"[TRACK_UPDATED] camera={self.camera_id} face_track_id={track.track_id} "
                        f"status={track.recognition_status} quality={track.quality_score:.2f} "
                        f"conf={track.confidence:.2f} recog_conf={track.recognition_confidence:.3f}"
                    )

                    # 1. Insert FaceDetection log record (always, for AI Detection History)
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
                    logger.info(f"[FACE] database insert/update id={face_rec.id} camera={cam_num} track={track.track_id} status={face_rec.recognition_status}")

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
                        ev_evidence = None
                        if snap_saved:
                            ev_evidence = Evidence(
                                id=str(uuid.uuid4()),
                                camera_id=cam_id,
                                evidence_type="snapshot",
                                file_path=snap_path,
                                file_url=snap_url,
                                file_size_bytes=snap_size,
                                metadata_json={
                                    "person_name": track.identity_name,
                                    "person_id": p_badge,
                                    "category": p_cat,
                                    "timestamp": ts_str,
                                    "camera_number": cam_num,
                                    "face_detection_id": face_rec.id,
                                },
                                created_at=now_dt
                            )
                            db.add(ev_evidence)
                            db.commit()
                            track._last_evidence_id = ev_evidence.id

                        await self._record_watchlist_movement(
                            db=db,
                            track=track,
                            cam_meta=cam_meta,
                            now_dt=now_dt,
                            evidence_id=ev_evidence.id if ev_evidence else None,
                            evidence_url=snap_url,
                            crop_url=crop_url
                        )

                    # 3. Case B: Threat / Watchlist Match -> ONE CRITICAL Alert per track
                    elif is_threat_watchlist:
                        face_alert_key = (self.camera_id, track.track_id, "FACE_WATCHLIST_MATCH")
                        existing = self.face_alert_state.get(face_alert_key)
                        refire_due = existing and (now_sec - existing["created_at"] >= WATCHLIST_FACE_ALERT_REFIRE_SEC)

                        if not existing or refire_due:
                            logger.warning(
                                f"🚨 [WATCHLIST THREAT DETECTED] Subject: {track.identity_name} ({p_badge}) on {cam_num} "
                                f"similarity={track.recognition_confidence:.3f}"
                            )
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
                            db.flush()

                            al_threat = Alert(
                                id=str(uuid.uuid4()),
                                camera_id=cam_id,
                                event_id=ev_threat.id,
                                event_type="FACE_WATCHLIST_MATCH",
                                severity="CRITICAL",
                                risk_score=95.0,
                                confidence=track.recognition_confidence,
                                status="NEW",
                                evidence_url=snap_url,
                                timestamp=now_dt,
                                track_id=track.track_id,
                                location=cam_loc,
                                details={
                                    "person_name": track.identity_name,
                                    "person_id": p_badge,
                                    "category": p_cat,
                                    "camera_name": cam_name,
                                    "location": cam_loc,
                                    "timestamp": ts_str,
                                }
                            )
                            db.add(al_threat)
                            db.flush()

                            inc_num = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                            inc_threat = Incident(
                                id=str(uuid.uuid4()),
                                incident_number=inc_num,
                                camera_id=cam_id,
                                alert_id=al_threat.id,
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
                            db.flush()
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
                            self.face_alert_state[face_alert_key] = {"alert_id": al_threat.id, "created_at": now_sec}
                            logger.info(
                                f"[ALERT_CREATED] alert_id={al_threat.id} event=FACE_WATCHLIST_MATCH "
                                f"camera={cam_num} face_track_id={track.track_id} identity={track.identity_name}"
                            )

                            # Record Watchlist Movement with actual generated evidence
                            await self._record_watchlist_movement(
                                db=db,
                                track=track,
                                cam_meta=cam_meta,
                                now_dt=now_dt,
                                evidence_id=ev_evidence.id if snap_saved else None,
                                evidence_url=snap_url,
                                crop_url=crop_url
                            )

                            # ONE canonical ALERT_NEW broadcast (not 4)
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
                            })
                        else:
                            # Alert already active for this face track — deduplicate
                            logger.info(
                                f"[ALERT_DEDUPLICATED] camera={self.camera_id} face_track_id={track.track_id} "
                                f"event=FACE_WATCHLIST_MATCH existing_alert_id={existing['alert_id']} "
                                f"reason=track_still_active"
                            )
                            ev_evidence = None
                            if snap_saved:
                                ev_evidence = Evidence(
                                    id=str(uuid.uuid4()),
                                    camera_id=cam_id,
                                    evidence_type="snapshot",
                                    file_path=snap_path,
                                    file_url=snap_url,
                                    file_size_bytes=snap_size,
                                    metadata_json={
                                        "person_name": track.identity_name,
                                        "person_id": p_badge,
                                        "category": p_cat,
                                        "timestamp": ts_str,
                                        "camera_number": cam_num,
                                        "face_detection_id": face_rec.id,
                                    },
                                    created_at=now_dt
                                )
                                db.add(ev_evidence)
                                db.commit()
                                track._last_evidence_id = ev_evidence.id

                            await self._record_watchlist_movement(
                                db=db,
                                track=track,
                                cam_meta=cam_meta,
                                now_dt=now_dt,
                                evidence_id=ev_evidence.id if ev_evidence else getattr(track, "_last_evidence_id", None),
                                evidence_url=snap_url,
                                crop_url=crop_url
                            )

                    # 4. Case C: Uncertain / Low Quality Face -> Log only (NO Alarm, NO Watchlist Movement)
                    elif is_uncertain:
                        logger.info(f"ℹ️ [UNCERTAIN FACE QUALITY] Track #{track.track_id} on {cam_num} (Quality Score: {track.quality_score:.2f}) — Logged only, NO ALARM")
                        db.commit()

                    # 5. Case D: Other Known Watchlist Category -> Update Movement Chain
                    elif is_known:
                        ev_evidence = None
                        if snap_saved:
                            ev_evidence = Evidence(
                                id=str(uuid.uuid4()),
                                camera_id=cam_id,
                                evidence_type="snapshot",
                                file_path=snap_path,
                                file_url=snap_url,
                                file_size_bytes=snap_size,
                                metadata_json={
                                    "person_name": track.identity_name,
                                    "person_id": p_badge,
                                    "category": p_cat,
                                    "timestamp": ts_str,
                                    "camera_number": cam_num,
                                    "face_detection_id": face_rec.id,
                                },
                                created_at=now_dt
                            )
                            db.add(ev_evidence)
                            db.commit()
                            track._last_evidence_id = ev_evidence.id

                        await self._record_watchlist_movement(
                            db=db,
                            track=track,
                            cam_meta=cam_meta,
                            now_dt=now_dt,
                            evidence_id=ev_evidence.id if ev_evidence else getattr(track, "_last_evidence_id", None),
                            evidence_url=snap_url,
                            crop_url=crop_url
                        )

                    # 5. Case D: Unknown Person -> ONE Security Alert per track
                    else:
                        face_alert_key = (self.camera_id, track.track_id, "UNKNOWN_PERSON_DETECTED")
                        existing = self.face_alert_state.get(face_alert_key)
                        refire_due = existing and (now_sec - existing["created_at"] >= UNKNOWN_PERSON_ALERT_REFIRE_SEC)

                        if not existing or refire_due:
                            logger.info(
                                f"⚠️ [UNKNOWN PERSON DETECTED] Track #{track.track_id} on {cam_num} — "
                                f"Security Alert Generated (first_alert={existing is None})"
                            )
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
                            db.flush()

                            al_unknown = Alert(
                                id=str(uuid.uuid4()),
                                camera_id=cam_id,
                                event_id=ev_unknown.id,
                                event_type="UNKNOWN_PERSON_DETECTED",
                                severity="HIGH",
                                risk_score=75.0,
                                confidence=track.confidence,
                                status="NEW",
                                evidence_url=snap_url,
                                timestamp=now_dt,
                                track_id=track.track_id,
                                location=cam_loc,
                                details={
                                    "track_id": f"F-{track.track_id}",
                                    "camera_name": cam_name,
                                    "location": cam_loc,
                                    "timestamp": ts_str,
                                }
                            )
                            db.add(al_unknown)
                            db.flush()

                            inc_num_unk = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                            inc_unknown = Incident(
                                id=str(uuid.uuid4()),
                                incident_number=inc_num_unk,
                                camera_id=cam_id,
                                alert_id=al_unknown.id,
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
                            db.flush()
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
                            self.face_alert_state[face_alert_key] = {"alert_id": al_unknown.id, "created_at": now_sec}
                            logger.info(
                                f"[ALERT_CREATED] alert_id={al_unknown.id} event=UNKNOWN_PERSON_DETECTED "
                                f"camera={cam_num} face_track_id={track.track_id}"
                            )

                            # ONE ALERT_NEW broadcast
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
                        else:
                            # Alert already active for this face track — deduplicate
                            logger.info(
                                f"[ALERT_DEDUPLICATED] camera={self.camera_id} face_track_id={track.track_id} "
                                f"event=UNKNOWN_PERSON_DETECTED existing_alert_id={existing['alert_id']} "
                                f"reason=track_still_active"
                            )
                            db.commit()

                    # Broadcast FACE_DETECTION_UPDATE telemetry (always — feeds live canvas overlay)
                    if do_fd_record:
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
                            "recognition_status": "VERIFIED" if is_verified_student_staff else "KNOWN" if is_threat_watchlist else "UNCERTAIN" if is_uncertain else "UNKNOWN",
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
        Vehicle Intelligence & ANPR pipeline executed for confirmed vehicle tracks.
        1. Classifies vehicle into accurate standard vehicle type (CAR, MOTORCYCLE, BUS, TRUCK, VAN, BICYCLE, etc.).
        2. Detects license plate region & runs OCR via EasyOCR.
        3. Persists vehicle detection record in SQLite `anpr_results` linked with camera_id, location, timestamp, vehicle_type, detection_confidence, track_id, license_plate, ocr_confidence, and evidence snapshot.
        4. If plate is unreadable/uncertain, stores as "UNKNOWN / UNREADABLE" with ocr_confidence = 0.0 (never invent fake plates).
        5. Stabilizes results across frames: updates existing database record when higher confidence plate OCR arrives for the same track.
        """
        if frame is None or frame.size == 0:
            return

        fh, fw = frame.shape[:2]
        now_sec = time.time()
        loop = asyncio.get_event_loop()

        for obj in vehicle_objs:
            track_key = (self.camera_id, obj.track_id)
            if track_key in self._anpr_in_flight:
                continue

            # Throttle inference per track: 3.0s if plate already confirmed with high confidence, 0.5s otherwise
            # Avoids redundant heavy EasyOCR CPU inference on continuously visible identified vehicles
            is_already_confirmed = (track_key in self.vehicle_record_state and self.vehicle_record_state[track_key].get("ocr_confidence", 0.0) >= 0.70)
            ocr_throttle = 3.0 if is_already_confirmed else 0.50
            if now_sec - self.last_anpr_process_times.get(track_key, 0) < ocr_throttle:
                continue
            self.last_anpr_process_times[track_key] = now_sec

            # Check if track record already exists in database (even if not yet in in-memory state)
            existing_record = self.vehicle_record_state.get(track_key)
            if not existing_record:
                check_db = SessionLocal()
                try:
                    cam_meta = self._get_camera_meta(check_db)
                    cam_db_id = cam_meta["id"]
                    db_rec = check_db.query(ANPRResult).filter(
                        (ANPRResult.camera_id == cam_db_id) | (ANPRResult.camera_id == self.camera_id),
                        ANPRResult.vehicle_track_id == obj.track_id
                    ).order_by(desc(ANPRResult.timestamp)).first()
                    if db_rec:
                        existing_record = {
                            "record_id": db_rec.id,
                            "plate_number": db_rec.plate_number,
                            "ocr_confidence": db_rec.ocr_confidence or 0.0,
                            "vehicle_type": db_rec.vehicle_type,
                            "status": db_rec.status,
                            "snapshot_url": db_rec.snapshot_url,
                            "is_watchlist": db_rec.is_watchlist_match,
                            "last_updated": now_sec,
                        }
                        self.vehicle_record_state[track_key] = existing_record
                except Exception as e:
                    logger.debug(f"[ANPR] DB check error: {e}")
                finally:
                    check_db.close()

            # Enforce deduplication cooldown for new track observations before heavy OCR
            if not existing_record:
                cooldown_key = (self.camera_id, str(obj.track_id))
                if now_sec - self.last_anpr_db_times.get(cooldown_key, 0) < ANPR_DUPLICATE_COOLDOWN_SEC:
                    continue
                # Atomically reserve cooldown now to prevent concurrent frames from racing
                self.last_anpr_db_times[cooldown_key] = now_sec

            self._anpr_in_flight.add(track_key)
            db = None
            try:
                # Accurate vehicle classification from AI model with confidence check
                raw_class = (obj.class_name or "").lower().strip()
                if obj.confidence < 0.40:
                    vehicle_type = "UNKNOWN"
                else:
                    vehicle_type = VEHICLE_TYPE_MAP.get(raw_class, raw_class.upper() if raw_class in VEHICLE_CLASSES else "UNKNOWN")

                vx = max(0, int(obj.bbox[0] * fw))
                vy = max(0, int(obj.bbox[1] * fh))
                vw = max(1, int(obj.bbox[2] * fw))
                vh = max(1, int(obj.bbox[3] * fh))
                vehicle_crop = frame[vy:min(fh, vy + vh), vx:min(fw, vx + vw)].copy()

                if vehicle_crop.size == 0:
                    continue

                anpr_result = None
                try:
                    anpr_result = await loop.run_in_executor(
                        self.agent_executor,
                        lambda crop=vehicle_crop, tid=obj.track_id: self.anpr_engine.process_vehicle_crop(
                            crop, self.camera_id, tid
                        )
                    )
                except Exception as e:
                    logger.error(f"[ANPR] process_vehicle_crop error on {self.camera_id}: {e}")

                # Get best multi-frame stabilized OCR result from tracker
                plate_text, avg_conf, is_valid = self.anpr_engine.tracker.get_best_result(
                    self.camera_id, obj.track_id
                )

                # Determine plate string, confidence and status
                if plate_text and plate_text not in ["PLATE UNCERTAIN", "UNKNOWN / UNREADABLE", "PLATE UNREADABLE"] and avg_conf >= 0.40:
                    final_plate = plate_text
                    final_ocr_conf = avg_conf
                    status = "CONFIRMED"
                else:
                    final_plate = None
                    final_ocr_conf = 0.0
                    status = "UNCERTAIN"

                plate_bbox_in_vehicle = anpr_result.get("plate_bbox_norm") if anpr_result else None

                # Update live in-memory active ANPR state for UI HUD
                self.active_anpr = [a for a in self.active_anpr if a.get("track_id") != obj.track_id]
                self.active_anpr.append({
                    "track_id": obj.track_id,
                    "vehicle_type": vehicle_type,
                    "bbox": obj.bbox,
                    "plate_text": final_plate or "PLATE UNREADABLE",
                    "ocr_confidence": final_ocr_conf,
                    "status": status,
                })

                # If existing record exists and plate has NOT improved, skip redundant DB updates
                if existing_record:
                    prev_plate = existing_record.get("plate_number")
                    prev_conf = existing_record.get("ocr_confidence", 0.0)
                    # Check if we have a meaningful improvement:
                    # 1. Previous was unreadable (None) and now we have a recognized plate
                    # 2. Previous had lower OCR confidence and now confidence is higher by >= 0.05
                    is_improved = False
                    if prev_plate is None and final_plate is not None:
                        is_improved = True
                    elif final_plate is not None and final_ocr_conf > (prev_conf + 0.05):
                        is_improved = True

                    if not is_improved:
                        existing_record["last_updated"] = now_sec
                        continue

                # DB persistence logic (Insert new OR Update existing)
                db = SessionLocal()
                cam_meta = self._get_camera_meta(db)
                cam_id = cam_meta["id"]
                cam_num = cam_meta["camera_id"]
                cam_name = cam_meta["name"]
                cam_loc = cam_meta.get("location") or "LOCATION NOT CONFIGURED"

                # Check Watchlist match if plate is valid
                is_watchlist = False
                watchlist_entry = None
                if final_plate:
                    clean_search_plate = final_plate.upper().replace(" ", "").replace("-", "")
                    active_watchlists = self._get_anpr_watchlist_records(db)
                    for wl in active_watchlists:
                        wl_clean = (wl.plate_number or "").upper().replace(" ", "").replace("-", "")
                        if wl_clean and (wl_clean == clean_search_plate or wl_clean in clean_search_plate):
                            is_watchlist = True
                            watchlist_entry = wl
                            break

                final_status = "WATCHLIST_MATCH" if is_watchlist else status

                # Generate tactical evidence snapshot
                saved = await loop.run_in_executor(
                    self.agent_executor,
                    lambda: save_anpr_evidence_snapshot(
                        frame=frame.copy(),
                        vehicle_bbox=obj.bbox,
                        plate_bbox_in_vehicle=plate_bbox_in_vehicle,
                        plate_text=final_plate,
                        vehicle_type=vehicle_type,
                        ocr_confidence=final_ocr_conf,
                        detection_confidence=obj.confidence,
                        camera_id=cam_num,
                        camera_name=cam_name,
                        camera_location=cam_loc,
                        track_id=obj.track_id,
                        status=final_status,
                    )
                )
                snap_path, snap_url, snap_size = saved if saved else (None, None, 0)

                if existing_record:
                    # UPDATE EXISTING RECORD IN-PLACE
                    rec_id = existing_record["record_id"]
                    anpr_rec = db.query(ANPRResult).filter(ANPRResult.id == rec_id).first()
                    if anpr_rec:
                        anpr_rec.plate_number = final_plate
                        anpr_rec.vehicle_type = vehicle_type
                        anpr_rec.detection_confidence = round(obj.confidence, 3)
                        anpr_rec.ocr_confidence = round(final_ocr_conf, 3)
                        anpr_rec.status = final_status
                        anpr_rec.is_watchlist_match = is_watchlist
                        if plate_bbox_in_vehicle:
                            anpr_rec.plate_bbox = plate_bbox_in_vehicle
                        if snap_url:
                            anpr_rec.snapshot_url = snap_url
                        db.commit()
                        logger.info(f"[ANPR] Updated existing vehicle track record {rec_id}: plate={final_plate} vtype={vehicle_type} conf={final_ocr_conf:.2f}")
                    else:
                        anpr_rec = None
                else:
                    # INSERT NEW RECORD
                    anpr_rec = ANPRResult(
                        id=str(uuid.uuid4()),
                        camera_id=cam_id,
                        plate_number=final_plate,
                        vehicle_type=vehicle_type,
                        vehicle_track_id=obj.track_id,
                        camera_name=cam_name,
                        camera_location=cam_loc,
                        detection_confidence=round(obj.confidence, 3),
                        ocr_confidence=round(final_ocr_conf, 3),
                        plate_bbox=plate_bbox_in_vehicle,
                        vehicle_bbox=obj.bbox,
                        snapshot_url=snap_url,
                        crop_url=None,
                        status=final_status,
                        is_watchlist_match=is_watchlist,
                        timestamp=datetime.utcnow(),
                        created_at=datetime.utcnow(),
                    )
                    db.add(anpr_rec)
                    db.commit()
                    logger.info(f"[ANPR] Created vehicle detection record {anpr_rec.id}: plate={final_plate} vtype={vehicle_type} det_conf={obj.confidence:.2f}")

                if anpr_rec:
                    # Cache vehicle record state for multi-frame deduplication and progressive updates
                    self.vehicle_record_state[track_key] = {
                        "record_id": anpr_rec.id,
                        "plate_number": final_plate,
                        "ocr_confidence": final_ocr_conf,
                        "vehicle_type": vehicle_type,
                        "status": final_status,
                        "snapshot_url": snap_url or anpr_rec.snapshot_url,
                        "is_watchlist": is_watchlist,
                        "last_updated": now_sec,
                    }

                    # Broadcast real-time ANPR_DETECTION WebSocket event
                    await self.ws_manager.broadcast({
                        "type": "ANPR_DETECTION",
                        "anpr_id": anpr_rec.id,
                        "id": anpr_rec.id,
                        "camera_id": cam_id,
                        "camera_number": cam_num,
                        "camera_name": cam_name,
                        "location": cam_loc,
                        "plate_number": final_plate,
                        "vehicle_type": vehicle_type,
                        "vehicle_track_id": obj.track_id,
                        "detection_confidence": round(obj.confidence, 3),
                        "ocr_confidence": round(final_ocr_conf, 3),
                        "status": anpr_rec.status,
                        "is_watchlist_match": is_watchlist,
                        "snapshot_url": snap_url or anpr_rec.snapshot_url,
                        "evidence_url": snap_url or anpr_rec.snapshot_url,
                        "timestamp": anpr_rec.timestamp.isoformat(),
                    })

                    # If Watchlist match detected on this frame (and not previously alerted for this track)
                    already_alerted = existing_record.get("is_watchlist", False) if existing_record else False
                    if is_watchlist and watchlist_entry and not already_alerted:
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
                            confidence=final_ocr_conf,
                            details={
                                "plate_number": final_plate,
                                "vehicle_type": vehicle_type,
                                "track_id": f"V-{obj.track_id}",
                                "reason": watchlist_entry.reason or "Vehicle on security watchlist",
                                "camera_name": cam_name,
                                "camera_location": cam_loc,
                                "ocr_confidence": final_ocr_conf,
                                "timestamp": ts_str,
                            },
                            timestamp=now_dt,
                            track_id=obj.track_id,
                        )
                        db.add(ev)
                        db.flush()

                        al = Alert(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_id=ev.id,
                            event_type="ANPR_WATCHLIST_MATCH",
                            severity=severity,
                            risk_score=risk_score,
                            confidence=final_ocr_conf,
                            status="NEW",
                            evidence_url=snap_url,
                            timestamp=now_dt,
                            track_id=obj.track_id,
                            location=cam_loc,
                            details={
                                "plate_number": final_plate,
                                "vehicle_type": vehicle_type,
                                "track_id": f"V-{obj.track_id}",
                                "reason": watchlist_entry.reason or "Vehicle on security watchlist",
                                "camera_name": cam_name,
                                "location": cam_loc,
                                "timestamp": ts_str,
                            }
                        )
                        db.add(al)
                        db.flush()

                        inc_num = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                        inc_anpr = Incident(
                            id=str(uuid.uuid4()),
                            incident_number=inc_num,
                            camera_id=cam_id,
                            alert_id=al.id,
                            title=f"{severity} WATCHLIST VEHICLE — {final_plate}",
                            description=f"Blacklisted vehicle with license plate '{final_plate}' ({vehicle_type}) detected at {cam_name}. Reason: {watchlist_entry.reason or 'Security Watchlist'}",
                            severity=severity,
                            risk_score=risk_score,
                            status="NEW",
                            related_event_ids=[ev.id],
                            start_time=now_dt,
                            created_at=now_dt,
                        )
                        db.add(inc_anpr)
                        db.flush()
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
                                    "plate_number": final_plate,
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
                            "confidence": final_ocr_conf,
                            "event_type": "ANPR_WATCHLIST_MATCH",
                            "alert_title": f"🚨 WATCHLIST VEHICLE — {final_plate}",
                            "plate_number": final_plate,
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
                                "plate_number": final_plate,
                                "vehicle_type": vehicle_type,
                                "event_type": "ANPR_WATCHLIST_MATCH",
                                "alert_title": f"🚨 WATCHLIST VEHICLE — {final_plate}",
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
                if db is not None:
                    try: db.rollback()
                    except Exception: pass
            finally:
                if db is not None:
                    try: db.close()
                    except Exception: pass
                self._anpr_in_flight.discard(track_key)

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
                self.agent_executor,
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

            zone_rule_pairs = self._get_zones_and_rules(db)
            if not zone_rule_pairs:
                return

            now_sec = time.time()
            hour_now = datetime.utcnow().hour
            is_night = (hour_now >= 18 or hour_now < 6)

            for zone, cached_rules in zone_rule_pairs:
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
                    inside = False
                    for pt in test_points:
                        if point_in_polygon(pt, polygon):
                            inside = True
                            break

                    logger.debug(f"[ZONE CHECK] camera={self.camera_id} track_id={obj.track_id} zone='{zone.name}' inside={inside}")

                    state_key = (self.camera_id, obj.track_id, zone.id)
                    state = self.track_zone_states.setdefault(state_key, {
                        "is_inside": False,
                        "entry_time": 0.0,
                        "intrusion_event_generated": False,
                        "loitering_event_generated": False
                    })

                    # OUTSIDE -> INSIDE
                    if inside:
                        self.outside_frame_counts[state_key] = 0
                        if not state["is_inside"]:
                            state["is_inside"] = True
                            state["entry_time"] = now_sec
                            state["intrusion_event_generated"] = False
                            state["loitering_event_generated"] = False

                    # INSIDE -> OUTSIDE with hysteresis debouncing
                    elif not inside and state["is_inside"]:
                        self.outside_frame_counts[state_key] = self.outside_frame_counts.get(state_key, 0) + 1
                        if self.outside_frame_counts[state_key] >= ZONE_EXIT_DEBOUNCE_FRAMES:
                            state["is_inside"] = False
                            state["intrusion_event_generated"] = False
                            state["loitering_event_generated"] = False
                            # Clear active alert keys so re-entry after verified exit triggers a fresh alert
                            ev_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_RESTRICTED_ZONE_INTRUSION"
                            loit_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_ZONE_LOITERING"
                            cleared_alert = self.active_alert_ids.pop(ev_key, None)
                            self.active_alert_ids.pop(loit_key, None)
                            logger.info(
                                f"[VIOLATION_CLEARED] camera={self.camera_id} track_id={obj.track_id} "
                                f"zone='{zone.name}' cleared_alert_id={cleared_alert}"
                            )

                    if not state["is_inside"]:
                        continue

                    rules = cached_rules
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

                        loitering_thresh = rule.loitering_threshold_sec if (rule.loitering_threshold_sec and rule.loitering_threshold_sec > 0) else LOITERING_THRESHOLD_SEC
                        dwell_inside_sec = now_sec - state["entry_time"]

                        # ── Check 1: Restricted Zone Intrusion ────────────────────────────────
                        event_type = "RESTRICTED_ZONE_INTRUSION"
                        active_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_{event_type}"
                        zone_alert_key = (self.camera_id, str(zone.id), event_type)

                        # Check suppression cache (if alert was deleted by operator)
                        is_suppressed = (
                            self.suppressed_alert_keys.get(active_key, 0) > now_sec or
                            self.suppressed_alert_keys.get(f"{self.camera_id}_{zone.id}_{event_type}", 0) > now_sec
                        )
                        if is_suppressed:
                            continue

                        # Check zone-level cooldown to prevent multi-alert spam from track switches
                        time_since_zone_alert = now_sec - self.zone_last_alert_times.get(zone_alert_key, 0.0)
                        zone_cooldown_ok = (time_since_zone_alert >= ZONE_INTRUSION_COOLDOWN_SEC)

                        if not state["intrusion_event_generated"]:
                            if zone_cooldown_ok:
                                state["intrusion_event_generated"] = True
                                self.last_alert_times[active_key] = now_sec
                                self.zone_last_alert_times[zone_alert_key] = now_sec
                                logger.info(
                                    f"[TRACK_UPDATED] camera={self.camera_id} track_id={obj.track_id} "
                                    f"class={obj.class_name} conf={obj.confidence:.2f} zone='{zone.name}' "
                                    f"event=ZONE_ENTRY"
                                )
                                new_alert_id = await self._create_and_broadcast_alert(
                                    db, cam, zone, obj, event_type, is_night, is_loitering=False,
                                    frame=frame, pre_frame=pre_frame
                                )
                                if new_alert_id:
                                    self.active_alert_ids[active_key] = new_alert_id
                            else:
                                logger.info(
                                    f"[ALERT_DEDUPLICATED] camera={self.camera_id} track_id={obj.track_id} "
                                    f"zone='{zone.name}' reason=zone_cooldown_active "
                                    f"cooldown_remaining={ZONE_INTRUSION_COOLDOWN_SEC - time_since_zone_alert:.1f}s"
                                )
                        else:
                            # ── STILL INSIDE: Deduplicate — do NOT create a new alert ────────
                            existing_alert_id = self.active_alert_ids.get(active_key, "unknown")
                            logger.debug(
                                f"[ALERT_DEDUPLICATED] camera={self.camera_id} track_id={obj.track_id} "
                                f"zone='{zone.name}' existing_alert_id={existing_alert_id} "
                                f"reason=track_still_inside dwell={dwell_inside_sec:.1f}s"
                            )

                        # ── Check 2: Zone Loitering ───────────────────────────────────────────
                        if dwell_inside_sec >= loitering_thresh and not state["loitering_event_generated"]:
                            event_type = "ZONE_LOITERING"
                            loiter_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_{event_type}"
                            zone_loiter_key = (self.camera_id, str(zone.id), event_type)
                            time_since_loiter = now_sec - self.zone_last_alert_times.get(zone_loiter_key, 0.0)

                            if not self.active_alert_ids.get(loiter_key) and time_since_loiter >= ZONE_LOITERING_COOLDOWN_SEC:
                                state["loitering_event_generated"] = True
                                self.last_alert_times[loiter_key] = now_sec
                                self.zone_last_alert_times[zone_loiter_key] = now_sec
                                logger.info(
                                    f"[TRACK_UPDATED] camera={self.camera_id} track_id={obj.track_id} "
                                    f"class={obj.class_name} dwell={dwell_inside_sec:.1f}s zone='{zone.name}' "
                                    f"event=LOITERING_THRESHOLD_EXCEEDED"
                                )
                                new_loiter_alert_id = await self._create_and_broadcast_alert(
                                    db, cam, zone, obj, event_type, is_night, is_loitering=True,
                                    frame=frame, pre_frame=pre_frame
                                )
                                if new_loiter_alert_id:
                                    self.active_alert_ids[loiter_key] = new_loiter_alert_id

        except Exception as ex:
            logger.error(f"Error in rule processing on {self.camera_id}: {ex}")
        finally:
            db.close()

    async def _create_and_broadcast_alert(
        self, db: Any, cam: Any, zone: Any, obj: TrackedObject,
        event_type: str, is_night: bool, is_loitering: bool,
        frame: Optional[np.ndarray] = None,
        pre_frame: Optional[np.ndarray] = None
    ) -> Optional[str]:
        """Create one alert+incident+evidence and broadcast WebSocket. Returns alert_id."""
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
        db.flush()

        al = Alert(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            event_id=ev.id,          # Direct FK — no timestamp matching needed
            event_type=event_type,
            severity=severity,
            risk_score=risk_score,
            confidence=obj.confidence,
            status="NEW",
            timestamp=now_dt,
            # Denormalized for fast REST retrieval without JOIN
            track_id=obj.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            location=cam.location or "Border Perimeter",
            details={
                "track_id": obj.track_id,
                "class_name": obj.class_name,
                "zone_id": zone_id,
                "zone_name": zone_name,
                "location": cam.location or "Border Perimeter",
                "camera_name": cam.name,
                "camera_number": cam.camera_id,
                "timestamp": ts_str,
            }
        )
        db.add(al)
        db.flush()  # Ensures ev and al exist in SQLite before linking Incident

        inc_id = None
        inc = None  # Always initialize — prevents UnboundLocalError when risk_score < 70
        if risk_score >= 70.0:
            # Check for existing active incident on this camera and zone for this event_type
            active_inc = db.query(Incident).filter(
                Incident.camera_id == cam.id,
                Incident.status.in_(["NEW", "ACKNOWLEDGED", "INVESTIGATING"]),
                Incident.title.like(f"%{event_type}%")
            ).order_by(Incident.created_at.desc()).first()

            if active_inc:
                inc = active_inc
                inc_id = active_inc.id
                al.incident_id = active_inc.id
                rel_events = list(active_inc.related_event_ids or [])
                if ev.id not in rel_events:
                    rel_events.append(ev.id)
                    active_inc.related_event_ids = rel_events
                active_inc.updated_at = now_dt
                logger.info(f"[INCIDENT_CORRELATED] camera={cam.camera_id} incident_id={inc.id} alert_id={al.id}")
            else:
                inc_num = f"INC-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
                inc = Incident(
                    id=str(uuid.uuid4()),
                    incident_number=inc_num,
                    camera_id=cam.id,
                    alert_id=al.id,      # Direct alert→incident link
                    title=f"{severity} {event_type} in {zone_name}",
                    description=f"Track #{obj.track_id} ({obj.class_name}) triggered {event_type} in {zone_name} ({cam.name})",
                    severity=severity,
                    risk_score=risk_score,
                    status="NEW",
                    related_event_ids=[ev.id],
                    start_time=now_dt,
                    created_at=now_dt
                )
                db.add(inc)
                db.flush()  # Ensures inc exists before updating al.incident_id
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
                self.agent_executor,
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

        # ── Blockchain Audit Trail ──────────────────────────────────────────────
        # Append a tamper-evident block for the alert (and incident if created).
        # Uses a separate DB session so a blockchain failure never disrupts the
        # main surveillance pipeline.
        try:
            from database.connection import SessionLocal as BlockchainSession
            bc_db = BlockchainSession()
            try:
                alert_block_data = {
                    "alert_id": al.id,
                    "event_id": ev.id,
                    "camera_id": cam.id,
                    "camera_number": cam.camera_id,
                    "event_type": event_type,
                    "severity": severity,
                    "risk_score": float(risk_score),
                    "track_id": obj.track_id,
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "timestamp": ts_str,
                }
                create_audit_block(
                    bc_db,
                    event_type="ALERT_CREATED",
                    event_id=al.id,
                    event_data=alert_block_data,
                    camera_id=cam.id,
                )
                if inc_id and inc:
                    inc_block_data = {
                        "incident_id": inc.id,
                        "incident_number": inc.incident_number,
                        "alert_id": al.id,
                        "event_id": ev.id,
                        "camera_id": cam.id,
                        "event_type": event_type,
                        "severity": severity,
                        "risk_score": float(risk_score),
                        "timestamp": ts_str,
                    }
                    create_audit_block(
                        bc_db,
                        event_type="INCIDENT_CREATED",
                        event_id=inc.id,
                        event_data=inc_block_data,
                        camera_id=cam.id,
                    )
                bc_db.commit()
            except Exception as bc_ex:
                logger.error(f"[BLOCKCHAIN_AUDIT_ERROR] {bc_ex}")
                try: bc_db.rollback()
                except Exception: pass
            finally:
                bc_db.close()
        except Exception as bc_import_ex:
            logger.error(f"[BLOCKCHAIN_IMPORT_ERROR] {bc_import_ex}")

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

        logger.info(f"[ALERT_CREATED] alert_id={al.id} event={event_type} camera={cam.camera_id} track={obj.track_id} zone='{zone_name}' risk_score={risk_score}")
        logger.info(f"[SECURITY_EVENT_CREATED] event_id={ev.id} type={event_type} camera={cam.camera_id} track_id={obj.track_id}")
        logger.info(f"[WEBSOCKET BROADCAST] type=ALERT_NEW alert_id={al.id} camera={cam.camera_id} event={event_type}")
        return al.id

    def suppress_alert(self, alert_id: Optional[str] = None, track_id: Optional[int] = None, zone_id: Optional[str] = None, duration_sec: float = 120.0):
        """Temporarily suppresses recreation of an alert deleted by operator."""
        now_sec = time.time()
        until = now_sec + duration_sec
        if alert_id:
            self.suppressed_alert_keys[str(alert_id)] = until
        if track_id is not None and zone_id is not None:
            self.suppressed_alert_keys[f"{self.camera_id}_{track_id}_{zone_id}_RESTRICTED_ZONE_INTRUSION"] = until
            self.suppressed_alert_keys[f"{self.camera_id}_{track_id}_{zone_id}_ZONE_LOITERING"] = until
        if zone_id is not None:
            self.suppressed_alert_keys[f"{self.camera_id}_{zone_id}_RESTRICTED_ZONE_INTRUSION"] = until
            self.suppressed_alert_keys[f"{self.camera_id}_{zone_id}_ZONE_LOITERING"] = until
            self.zone_last_alert_times[(self.camera_id, str(zone_id), "RESTRICTED_ZONE_INTRUSION")] = until
            self.zone_last_alert_times[(self.camera_id, str(zone_id), "ZONE_LOITERING")] = until

    def suppress_face(self, track_id: Optional[int] = None, identity_name: Optional[str] = None, duration_sec: float = 120.0):
        """Temporarily suppresses recreation of a face detection deleted by operator."""
        now_sec = time.time()
        until = now_sec + duration_sec
        if track_id is not None:
            self.suppressed_face_keys[(self.camera_id, track_id)] = until
        if identity_name:
            self.suppressed_face_keys[(self.camera_id, identity_name)] = until
        self.suppressed_face_keys[(self.camera_id, "UNKNOWN")] = until

