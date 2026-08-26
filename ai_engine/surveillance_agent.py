import time
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from ai_engine.detection.real_ai_detector import RealAIDetector
from ai_engine.tracking.tracker import MultiObjectTracker, TrackedObject
from event_engine.risk.scorer import OperationalRiskScorer
from storage.evidence_manager import EvidenceManager
from database.connection import SessionLocal
from database.schema import Camera, CameraZone, ZoneRule, Event, Alert, Incident, Evidence

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
    def __init__(self, camera_id: str, websocket_manager: Any):
        self.camera_id = camera_id
        self.ws_manager = websocket_manager
        self.detector = RealAIDetector(conf_threshold=DETECTION_CONFIDENCE_THRESHOLD)
        self.tracker = MultiObjectTracker()
        self.scorer = OperationalRiskScorer()
        self.evidence_mgr = EvidenceManager()
        self.last_alert_times: Dict[str, float] = {}
        self.track_zone_states: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        self.mode_label = "REAL AI | INFERENCE RUNNING"

    async def process_frame(self, frame: np.ndarray, loop_start_time: float) -> Tuple[List[TrackedObject], float, float]:
        # 1. Validate Frame
        if frame is None or frame.size == 0:
            return [], 0.0, 0.0

        # 2. Run Real AI Model Inference
        raw_detections = self.detector.detect(frame, self.camera_id)

        # 3. Filter Detections (Min confidence threshold)
        filtered_detections = [d for d in raw_detections if d.confidence >= DETECTION_CONFIDENCE_THRESHOLD]

        # 4. Multi-Object Tracking & Temporal Confirmation
        tracked_objects = self.tracker.update(self.camera_id, filtered_detections)

        latency_ms = round((time.time() - loop_start_time) * 1000, 1)

        # 5. Evaluate Zones, Behavior, Risk & Generate Real Alerts for confirmed tracks ONLY
        confirmed_objs = [obj for obj in tracked_objects if obj.is_confirmed]
        if confirmed_objs:
            await self._evaluate_surveillance_rules(confirmed_objs, frame)

        return tracked_objects, latency_ms, self.detector.conf_threshold

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

        # Save Evidence Snapshot directly from actual camera frame matrix
        file_path, file_url = None, None
        if frame is not None:
            saved = self.evidence_mgr.save_annotated_snapshot(
                frame=frame,
                camera_id=cam.camera_id,
                bbox=obj.bbox,
                label=obj.class_name,
                track_id=obj.track_id,
                confidence=obj.confidence,
                event_type=event_type
            )
            if saved:
                file_path, file_url = saved
                al.evidence_url = file_url

                # Save Evidence Record in DB
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
                    "event_id": ev.id
                }
                ev_record = Evidence(
                    id=str(uuid.uuid4()),
                    incident_id=inc_id,
                    camera_id=cam.id,
                    evidence_type="snapshot",
                    file_path=file_path,
                    file_url=file_url,
                    metadata_json=ev_meta,
                    created_at=datetime.utcnow()
                )
                db.add(ev_record)

        # Single DB commit per state-transition event
        db.commit()

        # Broadcast Real Alert over WebSocket with rich metadata
        ws_payload = {
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
            "evidence_url": file_url,
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
                "evidence_url": file_url,
                "timestamp": al.timestamp.isoformat()
            }
        }
        await self.ws_manager.broadcast(ws_payload)
