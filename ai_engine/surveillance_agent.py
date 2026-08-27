import time
import uuid
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from ai_engine.detection.real_ai_detector import RealAIDetector
from ai_engine.tracking.tracker import MultiObjectTracker, TrackedObject
from ai_engine.face.real_face_engine import RealFaceEngine, FaceTracker, FaceTrack, DetectedFace
from event_engine.risk.scorer import OperationalRiskScorer
from storage.evidence_manager import EvidenceManager
from database.connection import SessionLocal
from database.schema import Camera, CameraZone, ZoneRule, Event, Alert, Incident, Evidence, FaceDetection, FaceWatchlist

from backend.config import (
    DETECTION_CONFIDENCE_THRESHOLD, LOITERING_THRESHOLD_SEC, ALERT_COOLDOWN_SEC
)

logger = logging.getLogger(__name__)

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
    Executes the 14-stage end-to-end intelligent surveillance processing pipeline on actual camera frames:
      1. Frame validation
      2. Real AI model inference
      3. Confidence filtering
      4. Multi-object tracking (ByteTrack/Sort tracking)
      5. State maintenance & temporal stability confirmation
      6. Virtual Fence polygon evaluation
      7. Dwell time & movement calculation
      8. Explainable Risk Scoring Engine evaluation
      9. Event creation & DB persistence
      10. Alert generation for high/critical rule violations (Person walking normally = NO alert)
      11. WebSocket telemetry publishing
    """
    # Shared thread pool for JPEG encode + disk write — prevents event loop blocking
    _io_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evidence_io")

    def __init__(self, camera_id: str, websocket_manager: Any):
        self.camera_id = camera_id
        self.ws_manager = websocket_manager
        self.detector = RealAIDetector(conf_threshold=DETECTION_CONFIDENCE_THRESHOLD)
        self.tracker = MultiObjectTracker()
        self.face_engine = RealFaceEngine()
        self.face_tracker = FaceTracker()
        self.scorer = OperationalRiskScorer()
        self.evidence_mgr = EvidenceManager()
        self.last_alert_times: Dict[str, float] = {}
        self.last_detection_snapshot_times: Dict[Tuple[str, int], float] = {}
        self.last_face_process_time = 0.0
        self.last_face_db_record_times: Dict[Tuple[str, int], float] = {}
        self.active_faces: List[Dict[str, Any]] = []
        self.track_zone_states: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        self.mode_label = "REAL AI | INFERENCE RUNNING"

    async def process_frame(self, frame: np.ndarray, loop_start_time: float) -> Tuple[List[TrackedObject], float, float, List[Dict[str, Any]]]:
        # 1. Validate Frame
        if frame is None or frame.size == 0:
            return [], 0.0, 0.0, []

        # 2. Run Real AI Model Inference
        raw_detections = self.detector.detect(frame, self.camera_id)

        # 3. Filter Detections (Min confidence threshold)
        filtered_detections = [d for d in raw_detections if d.confidence >= DETECTION_CONFIDENCE_THRESHOLD]

        # 4. Multi-Object Tracking & Temporal Confirmation
        tracked_objects = self.tracker.update(self.camera_id, filtered_detections)

        latency_ms = round((time.time() - loop_start_time) * 1000, 1)

        # 5. Confirmed tracks ONLY trigger security rules & alerts (Intrusions, Loitering, Incursions)
        confirmed_objs = [obj for obj in tracked_objects if obj.is_confirmed]
        if confirmed_objs:
            # Process Category B: Security Rules & Alerts (Event-driven evidence capture)
            await self._evaluate_surveillance_rules(confirmed_objs, frame)

        # 6. Face Detection & Recognition Pipeline
        active_faces = await self._process_face_intelligence(frame, confirmed_objs)

        return tracked_objects, latency_ms, self.detector.conf_threshold, active_faces

    async def _process_face_intelligence(self, frame: np.ndarray, confirmed_objs: List[TrackedObject]) -> List[Dict[str, Any]]:
        """
        Executes the real Face Detection, Quality Filter, SFace Feature Embedding,
        Watchlist Comparison, and Evidence Storage Pipeline.
        """
        now_sec = time.time()
        # Throttled face detection rate (~5 Hz) to maintain high video FPS
        if now_sec - self.last_face_process_time < 0.20 and self.active_faces:
            return self.active_faces

        self.last_face_process_time = now_sec

        # Detect faces using YuNet in background thread
        loop = asyncio.get_event_loop()
        detected_faces: List[DetectedFace] = await loop.run_in_executor(
            self._io_executor,
            lambda: self.face_engine.detect_faces(frame)
        )
        # Update face tracks through multi-frame temporal tracker (confirmation frames: 3)
        confirmed_tracks: List[FaceTrack] = self.face_tracker.update(detected_faces)

        if not confirmed_tracks:
            self.active_faces = []
            return []

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            cam_id = cam.id if cam else self.camera_id
            cam_num = cam.camera_id if cam else self.camera_id
            cam_name = cam.name if cam else "Border Surveillance Camera"
            cam_loc = cam.location or "Sector 4 Border Outpost" if cam else "Sector 4 Border Outpost"

            watchlist_records = db.query(FaceWatchlist).filter(FaceWatchlist.is_active == True).all()

            faces_payload = []
            for track in confirmed_tracks:
                # Recognition with 2.0s interval caching
                track = self.face_engine.evaluate_track_recognition(frame, track, watchlist_records)

                face_data = {
                    "track_id": track.track_id,
                    "bbox": track.bbox_norm,
                    "landmarks": track.landmarks,
                    "confidence": track.confidence,
                    "quality_score": track.quality_score,
                    "recognition_status": track.recognition_status,
                    "identity_id": track.identity_id,
                    "identity_name": track.identity_name,
                    "recognition_confidence": track.recognition_confidence
                }
                faces_payload.append(face_data)

                # Event-driven persistence & Evidence Capture (Throttled per track)
                track_key = (self.camera_id, track.track_id)
                is_known_match = (track.recognition_status == "KNOWN")
                cooldown_sec = 20.0 if is_known_match else 30.0

                if now_sec - self.last_face_db_record_times.get(track_key, 0) >= cooldown_sec:
                    self.last_face_db_record_times[track_key] = now_sec

                    # Offload crop & annotated snapshot saving to thread pool
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
                            event_type="WATCHLIST MATCH" if is_known_match else "FACE DETECTION"
                        )
                    )

                    crop_url = crop_saved[1] if crop_saved else None
                    snap_url = snap_saved[1] if snap_saved else None

                    # Insert FaceDetection record in database
                    face_rec = FaceDetection(
                        id=str(uuid.uuid4()),
                        camera_id=cam_id,
                        track_id=track.track_id,
                        identity_id=track.identity_id,
                        identity_name=track.identity_name,
                        recognition_status=track.recognition_status,
                        detection_confidence=track.confidence,
                        recognition_confidence=track.recognition_confidence,
                        bbox=track.bbox_norm,
                        landmarks=track.landmarks,
                        crop_url=crop_url,
                        snapshot_url=snap_url,
                        quality_score=track.quality_score,
                        timestamp=datetime.utcnow()
                    )
                    db.add(face_rec)
                    db.commit()

                    # Broadcast FACE_DETECTION_UPDATE
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
                        "recognition_status": track.recognition_status,
                        "detection_confidence": track.confidence,
                        "recognition_confidence": track.recognition_confidence,
                        "crop_url": crop_url,
                        "snapshot_url": snap_url,
                        "quality_score": track.quality_score,
                        "timestamp": face_rec.timestamp.isoformat()
                    })

                    # If Watchlist match detected, generate real security Alert & trigger Alarm
                    if is_known_match:
                        logger.warning(f"[WATCHLIST ALERT] Enrolled Subject matched: {track.identity_name} on {cam_num} ({track.recognition_confidence * 100:.1f}%)")
                        ev_wl = Event(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type=f"WATCHLIST MATCH: {track.identity_name}",
                            severity="CRITICAL",
                            risk_score=92.0,
                            confidence=track.recognition_confidence,
                            details={"person": track.identity_name, "track_id": track.track_id, "confidence": track.recognition_confidence},
                            timestamp=datetime.utcnow(),
                            track_id=track.track_id
                        )
                        db.add(ev_wl)
                        al_wl = Alert(
                            id=str(uuid.uuid4()),
                            camera_id=cam_id,
                            event_type=f"WATCHLIST MATCH: {track.identity_name}",
                            severity="CRITICAL",
                            risk_score=92.0,
                            confidence=track.recognition_confidence,
                            status="NEW",
                            evidence_url=snap_url,
                            timestamp=datetime.utcnow()
                        )
                        db.add(al_wl)
                        db.commit()

                        # Broadcast ALERT_NEW and FACE_WATCHLIST_MATCH
                        await self.ws_manager.broadcast({
                            "type": "ALERT_NEW",
                            "alert_id": al_wl.id,
                            "event_id": ev_wl.id,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "camera_name": cam_name,
                            "location": cam_loc,
                            "object_class": "person",
                            "track_id": f"F-{track.track_id}",
                            "confidence": track.recognition_confidence,
                            "event_type": f"WATCHLIST MATCH: {track.identity_name}",
                            "risk_score": 92.0,
                            "severity": "CRITICAL",
                            "timestamp": al_wl.timestamp.isoformat(),
                            "evidence_url": snap_url,
                            "alert": {
                                "id": al_wl.id,
                                "camera_id": cam_id,
                                "camera_number": cam_num,
                                "camera_name": cam_name,
                                "location": cam_loc,
                                "object_class": "person",
                                "track_id": f"F-{track.track_id}",
                                "confidence": track.recognition_confidence,
                                "event_type": f"WATCHLIST MATCH: {track.identity_name}",
                                "severity": "CRITICAL",
                                "risk_score": 92.0,
                                "evidence_url": snap_url,
                                "timestamp": al_wl.timestamp.isoformat()
                            }
                        })
                        await self.ws_manager.broadcast({
                            "type": "FACE_WATCHLIST_MATCH",
                            "alert_id": al_wl.id,
                            "camera_id": cam_id,
                            "camera_number": cam_num,
                            "person_name": track.identity_name,
                            "track_id": track.track_id,
                            "similarity": track.recognition_confidence,
                            "snapshot_url": snap_url,
                            "location": cam_loc
                        })

            self.active_faces = faces_payload
            return faces_payload
        except Exception as ex:
            logger.error(f"Error processing face intelligence: {ex}", exc_info=True)
            db.rollback()
            return []
        finally:
            db.close()

    async def _create_and_broadcast_detection_evidence(self, obj: TrackedObject, frame: np.ndarray):
        if frame is None or frame.size == 0:
            logger.warning("[EVIDENCE ERROR] Frame matrix is empty or None — skipping detection snapshot")
            return

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            cam_id = cam.id if cam else self.camera_id
            cam_num = cam.camera_id if cam else self.camera_id
            cam_name = cam.name if cam else "Border Surveillance Camera"
            cam_loc = cam.location or "Sector 4 Border Outpost" if cam else "Sector 4 Border Outpost"

            # ---- Offload JPEG encode + disk write to thread pool (non-blocking) ----
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
                    event_type="DETECTION"
                )
            )

            if not saved:
                logger.error("[EVIDENCE ERROR] save_annotated_snapshot returned None — snapshot not saved")
                return

            file_path, file_url, file_size = saved
            logger.info(f"[EVIDENCE] Snapshot saved: {file_path} ({round(file_size/1024,1)} KB)")

            ev_meta = {
                "camera_id": cam_id,
                "camera_number": cam_num,
                "camera_name": cam_name,
                "location": cam_loc,
                "object_class": obj.class_name,
                "confidence": obj.confidence,
                "track_id": f"P-{obj.track_id}",
                "event_type": "DETECTION",
                "risk_score": 0.0,
                "severity": "INFO",
                "captured_at": datetime.utcnow().isoformat(),
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
                created_at=datetime.utcnow()
            )
            db.add(ev_record)
            db.commit()
            logger.info(f"[EVIDENCE] Database record created: ID={ev_record.id}")

            image_api_url = f"/api/evidence/{ev_record.id}/image"
            logger.info(f"[EVIDENCE] Snapshot URL: {image_api_url}")

            # Broadcast EVIDENCE_NEW via WebSocket — prepends to AI Detection History
            ev_dict = {
                "id": ev_record.id,
                "camera_id": cam_id,
                "camera_number": cam_num,
                "camera_name": cam_name,
                "location": cam_loc,
                "object_class": obj.class_name,
                "track_id": f"P-{obj.track_id}",
                "confidence": obj.confidence,
                "event_type": "DETECTION",
                "risk_score": 0.0,
                "severity": "INFO",
                "captured_at": ev_record.created_at.isoformat(),
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
                "object_class": obj.class_name,
                "track_id": f"P-{obj.track_id}",
                "confidence": obj.confidence,
                "event_type": "DETECTION",
                "risk_score": 0.0,
                "severity": "INFO",
                "timestamp": ev_record.created_at.isoformat(),
                "file_url": image_api_url,
                "evidence": ev_dict,
            })
            logger.info("[EVIDENCE] EVIDENCE_NEW broadcast sent via WebSocket")

        except Exception as ex:
            logger.error(f"[EVIDENCE ERROR] Failed to record detection evidence: {ex}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    async def _evaluate_surveillance_rules(self, confirmed_objs: List[TrackedObject], frame: Optional[np.ndarray] = None):
        if not confirmed_objs:
            return

        active_track_ids = set(obj.track_id for obj in confirmed_objs)

        # Clean up expired track states
        stale_keys = [k for k in self.track_zone_states.keys() if k[0] == self.camera_id and k[1] not in active_track_ids]
        for sk in stale_keys:
            del self.track_zone_states[sk]

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter(Camera.camera_id == self.camera_id).first()
            if not cam:
                return

            zones = db.query(CameraZone).filter(CameraZone.camera_id == cam.id, CameraZone.is_active == True).all()
            if not zones:
                return

            now_sec = time.time()
            hour_now = datetime.utcnow().hour
            is_night = (hour_now >= 18 or hour_now < 6)

            for zone in zones:
                coords = zone.coordinates  # Polygon [[x,y], ...]
                if not coords or len(coords) < 3:
                    continue

                polygon = [(p[0], p[1]) for p in coords]

                for obj in confirmed_objs:
                    nx, ny, nw, nh = obj.bbox
                    # Bottom-center point (feet position)
                    foot_point = (nx + nw / 2.0, ny + nh)
                    inside = point_in_polygon(foot_point, polygon)

                    state_key = (self.camera_id, obj.track_id, zone.id)
                    if state_key not in self.track_zone_states:
                        self.track_zone_states[state_key] = {
                            "is_inside": False,
                            "entry_time": 0.0,
                            "intrusion_event_generated": False,
                            "loitering_event_generated": False
                        }
                    state = self.track_zone_states[state_key]

                    # State Transition: OUTSIDE -> INSIDE
                    if inside and not state["is_inside"]:
                        state["is_inside"] = True
                        state["entry_time"] = now_sec
                        state["intrusion_event_generated"] = False
                        state["loitering_event_generated"] = False

                    # State Transition: INSIDE -> OUTSIDE
                    elif not inside and state["is_inside"]:
                        state["is_inside"] = False
                        state["intrusion_event_generated"] = False
                        state["loitering_event_generated"] = False

                    if not state["is_inside"]:
                        continue

                    # Evaluate enabled rules for this zone
                    rules = db.query(ZoneRule).filter(ZoneRule.zone_id == zone.id, ZoneRule.enabled == True).all()
                    for rule in rules:
                        if rule.object_type != "all" and rule.object_type != obj.class_name:
                            continue
                        if obj.confidence < rule.min_confidence:
                            continue

                        cooldown_window = rule.cooldown_sec if (rule.cooldown_sec and rule.cooldown_sec > 0) else ALERT_COOLDOWN_SEC
                        loitering_thresh = rule.loitering_threshold_sec if (rule.loitering_threshold_sec and rule.loitering_threshold_sec > 0) else LOITERING_THRESHOLD_SEC
                        dwell_inside_sec = now_sec - state["entry_time"]

                        # Check 1: Restricted Zone Intrusion (Triggers EXACTLY ONCE on OUTSIDE -> INSIDE)
                        if not state["intrusion_event_generated"]:
                            event_type = "RESTRICTED ZONE INTRUSION"
                            dedup_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_{event_type}"
                            if now_sec - self.last_alert_times.get(dedup_key, 0) >= cooldown_window:
                                self.last_alert_times[dedup_key] = now_sec
                                state["intrusion_event_generated"] = True
                                await self._create_and_broadcast_alert(
                                    db, cam, zone, obj, event_type, is_night, is_loitering=False, frame=frame
                                )

                        # Check 2: Zone Loitering (Triggers EXACTLY ONCE when dwell_time >= loitering_thresh)
                        if dwell_inside_sec >= loitering_thresh and not state["loitering_event_generated"]:
                            event_type = "ZONE LOITERING DETECTED"
                            dedup_key = f"{self.camera_id}_{obj.track_id}_{zone.id}_{event_type}"
                            if now_sec - self.last_alert_times.get(dedup_key, 0) >= cooldown_window:
                                self.last_alert_times[dedup_key] = now_sec
                                state["loitering_event_generated"] = True
                                await self._create_and_broadcast_alert(
                                    db, cam, zone, obj, event_type, is_night, is_loitering=True, frame=frame
                                )

        except Exception as ex:
            logger.error(f"Error in AISurveillanceAgent rule processing: {ex}")
        finally:
            db.close()

    async def _create_and_broadcast_alert(
        self, db: Any, cam: Any, zone: Any, obj: TrackedObject,
        event_type: str, is_night: bool, is_loitering: bool,
        frame: Optional[np.ndarray] = None
    ):
        conditions = {
            "night_mode": is_night,
            "restricted_zone": True,
            "fence_crossing": True,
            "loitering": is_loitering
        }
        res = self.scorer.calculate_score(conditions)
        risk_score = res["risk_score"]
        severity = res["severity"]

        # Create Event in DB
        ev = Event(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            zone_id=zone.id,
            event_type=event_type,
            severity=severity,
            risk_score=risk_score,
            confidence=obj.confidence,
            details={"conditions": conditions, "breakdown": res["breakdown"], "track_id": obj.track_id},
            timestamp=datetime.utcnow(),
            track_id=obj.track_id
        )
        db.add(ev)

        # Create Real Alert in DB
        al = Alert(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            event_type=event_type,
            severity=severity,
            risk_score=risk_score,
            confidence=obj.confidence,
            status="NEW",
            timestamp=datetime.utcnow()
        )
        db.add(al)

        # Create Incident if high risk score
        inc_id = None
        if risk_score >= 70.0:
            inc_num = f"INC-{int(time.time())}"
            inc = Incident(
                id=str(uuid.uuid4()),
                incident_number=inc_num,
                camera_id=cam.id,
                title=f"{severity} {event_type} at {cam.name}",
                description=f"Track #{obj.track_id} ({obj.class_name}) triggered {event_type} in {zone.name}",
                severity=severity,
                risk_score=risk_score,
                status="NEW",
                start_time=datetime.utcnow()
            )
            db.add(inc)
            inc_id = inc.id

        # Save Security Event Evidence Snapshot — offloaded to thread pool so event loop is never blocked
        file_path, file_url, file_size = None, None, 0
        ev_record = None
        if frame is not None:
            logger.info(f"[EVIDENCE] Capturing security event snapshot: {event_type} | track P-{obj.track_id} | camera {cam.camera_id}")
            loop = asyncio.get_event_loop()
            saved = await loop.run_in_executor(
                self._io_executor,
                lambda: self.evidence_mgr.save_annotated_snapshot(
                    frame=frame.copy(),
                    camera_id=cam.camera_id,
                    bbox=obj.bbox,
                    label=obj.class_name,
                    track_id=obj.track_id,
                    confidence=obj.confidence,
                    event_type=event_type
                )
            )
            if saved:
                file_path, file_url, file_size = saved
                logger.info(f"[EVIDENCE] Snapshot saved: {file_path} ({round(file_size/1024,1)} KB)")
                al.evidence_url = file_url

                # Build Evidence DB record
                ev_meta = {
                    "camera_id": cam.id,
                    "camera_number": cam.camera_id,
                    "camera_name": cam.name,
                    "location": cam.location or "Sector 4 Border Outpost",
                    "object_class": obj.class_name,
                    "confidence": obj.confidence,
                    "track_id": f"P-{obj.track_id}",
                    "event_type": event_type,
                    "risk_score": risk_score,
                    "severity": severity,
                    "captured_at": datetime.utcnow().isoformat(),
                    "bbox": obj.bbox,
                    "alert_id": al.id,
                    "event_id": ev.id,
                    "file_path": file_path,
                    "file_url": file_url,
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
                    created_at=datetime.utcnow(),
                )
                db.add(ev_record)
            else:
                logger.error(f"[EVIDENCE ERROR] save_annotated_snapshot failed for {event_type} on camera {cam.camera_id}")

        # Single DB commit per state-transition event (Event + Alert + Incident + Evidence)
        db.commit()
        logger.info(f"[EVIDENCE] DB committed — Event={ev.id[:8]} Alert={al.id[:8]}" + (f" Evidence={ev_record.id[:8]}" if ev_record else " (no snapshot)"))

        if ev_record:
            image_api_url = f"/api/evidence/{ev_record.id}/image"
            logger.info(f"[EVIDENCE] Security evidence record created: {ev_record.id}")
            logger.info(f"[EVIDENCE] Evidence URL: {image_api_url}")

            # Broadcast EVIDENCE_NEW — AI Detection History page prepends this instantly
            ev_dict = {
                "id": ev_record.id,
                "camera_id": cam.id,
                "camera_number": cam.camera_id,
                "camera_name": cam.name,
                "location": cam.location or "Sector 4 Border Outpost",
                "object_class": obj.class_name,
                "track_id": f"P-{obj.track_id}",
                "confidence": obj.confidence,
                "event_type": event_type,
                "risk_score": risk_score,
                "severity": severity,
                "captured_at": ev_record.created_at.isoformat(),
                "file_url": image_api_url,
                "evidence_url": image_api_url,
            }
            await self.ws_manager.broadcast({
                "type": "EVIDENCE_NEW",
                "evidence_id": ev_record.id,
                "camera_id": cam.id,
                "camera_number": cam.camera_id,
                "camera_name": cam.name,
                "location": cam.location or "Sector 4 Border Outpost",
                "object_class": obj.class_name,
                "track_id": f"P-{obj.track_id}",
                "confidence": obj.confidence,
                "event_type": event_type,
                "risk_score": risk_score,
                "severity": severity,
                "timestamp": ev_record.created_at.isoformat(),
                "file_url": image_api_url,
                "evidence": ev_dict,
            })
            logger.info("[EVIDENCE] EVIDENCE_NEW broadcast sent via WebSocket")

        # Broadcast ALERT_NEW — triggers alarm sound on frontend (alert_id enables deduplication)
        await self.ws_manager.broadcast({
            "type": "ALERT_NEW",
            "alert_id": al.id,
            "event_id": ev.id,
            "camera_id": cam.id,
            "camera_number": cam.camera_id,
            "camera_name": cam.name,
            "location": cam.location or "Sector 4 Border Outpost",
            "object_class": obj.class_name,
            "track_id": f"P-{obj.track_id}",
            "confidence": obj.confidence,
            "event_type": event_type,
            "risk_score": risk_score,
            "severity": severity,
            "timestamp": al.timestamp.isoformat(),
            "evidence_url": f"/api/evidence/{ev_record.id}/image" if ev_record else file_url,
            "alert": {
                "id": al.id,
                "camera_id": self.camera_id,
                "camera_number": cam.camera_id,
                "camera_name": cam.name,
                "location": cam.location or "Sector 4 Border Outpost",
                "object_class": obj.class_name,
                "track_id": f"P-{obj.track_id}",
                "confidence": obj.confidence,
                "event_type": event_type,
                "severity": severity,
                "risk_score": risk_score,
                "evidence_url": f"/api/evidence/{ev_record.id}/image" if ev_record else file_url,
                "timestamp": al.timestamp.isoformat(),
            },
        })
        logger.info(f"[EVIDENCE] ALERT_NEW broadcast sent — alert_id={al.id[:8]} severity={severity}")
