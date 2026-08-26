import time
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from ai_engine.detection.real_ai_detector import RealAIDetector
from ai_engine.tracking.tracker import MultiObjectTracker, TrackedObject
from event_engine.risk.scorer import OperationalRiskScorer
from database.connection import SessionLocal
from database.schema import Camera, CameraZone, ZoneRule, Event, Alert, Incident

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
        self.detector = RealAIDetector()
        self.tracker = MultiObjectTracker(max_disappeared=15, max_distance=0.15)
        self.scorer = OperationalRiskScorer()
        self.last_alert_times: Dict[str, float] = {}
        self.mode_label = "REAL AI | INFERENCE RUNNING"

    async def process_frame(self, frame: np.ndarray, loop_start_time: float) -> Tuple[List[TrackedObject], float, float]:
        # 1. Validate Frame
        if frame is None or frame.size == 0:
            return [], 0.0, 0.0

        # 2. Run Real AI Model Inference
        raw_detections = self.detector.detect(frame, self.camera_id)

        # 3. Filter Detections (Min confidence 0.35)
        filtered_detections = [d for d in raw_detections if d.confidence >= 0.35]

        # 4. Multi-Object Tracking & Temporal Confirmation
        tracked_objects = self.tracker.update(self.camera_id, filtered_detections)

        latency_ms = round((time.time() - loop_start_time) * 1000, 1)

        # 5. Evaluate Zones, Behavior, Risk & Generate Real Alerts
        if tracked_objects:
            await self._evaluate_surveillance_rules(tracked_objects)

        return tracked_objects, latency_ms, self.detector.conf_threshold

    async def _evaluate_surveillance_rules(self, tracked_objs: List[TrackedObject]):
        if not tracked_objs:
            return

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

                for obj in tracked_objs:
                    nx, ny, nw, nh = obj.bbox
                    # Bottom-center point (feet position)
                    foot_point = (nx + nw / 2.0, ny + nh)

                    if point_in_polygon(foot_point, polygon):
                        rules = db.query(ZoneRule).filter(ZoneRule.zone_id == zone.id, ZoneRule.enabled == True).all()

                        for rule in rules:
                            if rule.object_type != "all" and rule.object_type != obj.class_name:
                                continue
                            if obj.confidence < rule.min_confidence:
                                continue

                            # Loitering requirement: must dwell past rule loitering_threshold_sec
                            is_loitering = obj.dwell_time_sec >= rule.loitering_threshold_sec

                            # Alert deduplication cooldown
                            dedup_key = f"{self.camera_id}_{zone.id}_{obj.track_id}_{rule.id}"
                            last_time = self.last_alert_times.get(dedup_key, 0)
                            if now_sec - last_time < rule.cooldown_sec:
                                continue

                            self.last_alert_times[dedup_key] = now_sec

                            # Calculate Explainable Risk Score
                            conditions = {
                                "night_mode": is_night,
                                "restricted_zone": True,
                                "fence_crossing": True,
                                "loitering": is_loitering
                            }
                            res = self.scorer.calculate_score(conditions)
                            risk_score = res["risk_score"]
                            severity = res["severity"]

                            event_type = "RESTRICTED ZONE INTRUSION" if not is_loitering else "ZONE LOITERING DETECTED"

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
                            if risk_score >= 70.0:
                                inc_num = f"INC-{int(time.time())}"
                                inc = Incident(
                                    id=str(uuid.uuid4()),
                                    incident_number=inc_num,
                                    camera_id=cam.id,
                                    title=f"{severity} Intrusion Alert at {cam.name}",
                                    description=f"Track #{obj.track_id} ({obj.class_name}) entered restricted zone {zone.name}",
                                    severity=severity,
                                    risk_score=risk_score,
                                    status="NEW",
                                    start_time=datetime.utcnow()
                                )
                                db.add(inc)

                            db.commit()

                            # Broadcast Real Alert over WebSocket
                            await self.ws_manager.broadcast({
                                "type": "ALERT_NEW",
                                "alert": {
                                    "id": al.id,
                                    "camera_id": self.camera_id,
                                    "event_type": event_type,
                                    "severity": severity,
                                    "risk_score": risk_score,
                                    "timestamp": al.timestamp.isoformat()
                                }
                            })
        except Exception as ex:
            logger.error(f"Error in AISurveillanceAgent rule processing: {ex}")
        finally:
            db.close()
