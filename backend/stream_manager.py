import os
import time
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List

from database.connection import SessionLocal
from database.schema import (
    Camera, CameraHealth, CameraZone, ZoneRule,
    Event, Alert, Incident, Detection
)
from video_engine.ingestion.source import VideoSource, MP4VideoSource, WebcamVideoSource, RTSPVideoSource
from ai_engine.detection.yolo_detector import YOLODetector
from ai_engine.detection.fallback_detector import FallbackDetector
from ai_engine.tracking.tracker import MultiObjectTracker
from event_engine.rules.virtual_fence import point_in_polygon
from event_engine.risk.scorer import OperationalRiskScorer

from ai_engine.surveillance_agent import AISurveillanceAgent

logger = logging.getLogger(__name__)

class StreamWorker:
    def __init__(self, camera_id: str, source_type: str, source_path: str, websocket_manager):
        self.camera_id = camera_id
        self.source_type = source_type.upper()
        self.source_path = source_path
        self.ws_manager = websocket_manager

        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.source: Optional[VideoSource] = None
        self.latest_jpeg: Optional[bytes] = None

        # Central Real AI Surveillance Agent (Real frame inference, 0 detections on empty scene)
        self.agent = AISurveillanceAgent(self.camera_id, self.ws_manager)

    def _create_source(self) -> VideoSource:
        if self.source_type == "WEBCAM":
            dev_idx = int(self.source_path) if str(self.source_path).isdigit() else 0
            return WebcamVideoSource(self.camera_id, dev_idx)
        elif self.source_type == "RTSP":
            return RTSPVideoSource(self.camera_id, self.source_path)
        else:
            return MP4VideoSource(self.camera_id, self.source_path)

    def get_latest_jpeg(self) -> Optional[bytes]:
        return self.latest_jpeg

    async def run(self):
        self.is_running = True
        logger.info(f"Starting Real AI StreamWorker for {self.camera_id} ({self.source_type}: {self.source_path})")

        self.source = self._create_source()
        frame_count = 0
        start_time = time.time()

        # Update DB Camera status to CONNECTING/ONLINE
        self._update_db_status("ONLINE", fps=0.0, latency_ms=0.0)

        while self.is_running:
            loop_start = time.time()
            ret, frame = self.source.read_frame()

            if not ret or frame is None:
                if self.source.status != "ONLINE":
                    self._update_db_status(self.source.status, fps=0.0, latency_ms=0.0)
                await asyncio.sleep(0.2)
                continue

            # Encode frame to JPEG for real-time video streaming
            import cv2
            ok_enc, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok_enc:
                self.latest_jpeg = buf.tobytes()

            frame_count += 1
            elapsed = time.time() - start_time
            current_fps = round(frame_count / max(1.0, elapsed), 1)

            # Process actual video frame through Real AI Surveillance Agent
            tracked_objs, latency_ms, conf_thresh = await self.agent.process_frame(frame, loop_start)
            mode_label = "REAL AI | INFERENCE RUNNING"

            # Telemetry Payload for WebSocket (Only real detections from actual frame)
            dets_payload = [
                {
                    "track_id": t.track_id,
                    "class_name": t.class_name,
                    "confidence": t.confidence,
                    "bbox": t.bbox,
                    "dwell_time_sec": t.dwell_time_sec,
                    "is_fallback": False
                } for t in tracked_objs
            ]

            self._update_db_status("ONLINE", fps=current_fps, latency_ms=latency_ms)

            ws_payload = {
                "type": "DETECTIONS_UPDATE",
                "camera_id": self.camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "inference_mode": mode_label,
                "detections": dets_payload,
                "fps": current_fps,
                "latency_ms": latency_ms
            }

            await self.ws_manager.broadcast(ws_payload)

            # Sleep to match camera FPS rate (~20-25 FPS)
            target_delay = max(0.01, (1.0 / 25.0) - (time.time() - loop_start))
            await asyncio.sleep(target_delay)

        # Cleanup on stop
        if self.source:
            self.source.release()
        self._update_db_status("OFFLINE", fps=0.0, latency_ms=0.0)
        logger.info(f"StreamWorker for {self.camera_id} stopped.")

    async def _process_zone_rules(self, tracked_objs):
        if not tracked_objs:
            return

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter(Camera.camera_id == self.camera_id).first()
            if not cam:
                return

            zones = db.query(CameraZone).filter(CameraZone.camera_id == cam.id, CameraZone.is_active == True).all()
            if not zones:
                # Auto-create default perimeter zone if none exists
                default_zone = CameraZone(
                    id=str(uuid.uuid4()),
                    camera_id=cam.id,
                    name=f"Perimeter Fence - {cam.name}",
                    zone_type="RESTRICTED AREA",
                    geometry_type="polygon",
                    coordinates=[[0.15, 0.25], [0.85, 0.25], [0.92, 0.82], [0.08, 0.82]],
                    is_active=True
                )
                db.add(default_zone)

                default_rule = ZoneRule(
                    id=str(uuid.uuid4()),
                    zone_id=default_zone.id,
                    object_type="all",
                    direction="ANY",
                    min_confidence=0.3,
                    loitering_threshold_sec=2,
                    severity="HIGH",
                    cooldown_sec=5,
                    enabled=True
                )
                db.add(default_rule)
                db.commit()
                zones = [default_zone]

            now_sec = time.time()
            hour_now = datetime.utcnow().hour
            is_night = (hour_now >= 18 or hour_now < 6)

            for zone in zones:
                coords = zone.coordinates  # List of [x, y] normalized
                if not coords or len(coords) < 3:
                    continue

                polygon = [(p[0], p[1]) for p in coords]

                for obj in tracked_objs:
                    nx, ny, nw, nh = obj.bbox
                    # Bottom-center of bounding box (foot position of target)
                    foot_point = (nx + nw / 2.0, ny + nh)

                    if point_in_polygon(foot_point, polygon):
                        rules = db.query(ZoneRule).filter(ZoneRule.zone_id == zone.id, ZoneRule.enabled == True).all()

                        for rule in rules:
                            if rule.object_type != "all" and rule.object_type != obj.class_name:
                                continue
                            if obj.confidence < rule.min_confidence:
                                continue

                            is_loitering = obj.dwell_time_sec >= rule.loitering_threshold_sec

                            # Alert deduplication check using cooldown
                            dedup_key = f"{self.camera_id}_{zone.id}_{obj.track_id}_{rule.id}"
                            last_time = self.last_alert_times.get(dedup_key, 0)
                            if now_sec - last_time < rule.cooldown_sec:
                                continue

                            self.last_alert_times[dedup_key] = now_sec

                            # Dynamic Risk Calculation
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

                            # Create Event
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

                            # Create Alert
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

                            # Create Incident if high risk
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

                            # Broadcast real alert over WS
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
            logger.error(f"Error in zone rule processing: {ex}")
        finally:
            db.close()

    def _update_db_status(self, status: str, fps: float, latency_ms: float):
        db = SessionLocal()
        try:
            cam = db.query(Camera).filter(Camera.camera_id == self.camera_id).first()
            if cam:
                cam.status = status
                cam.fps = fps
                if cam.health:
                    cam.health.status = status
                    cam.health.fps = fps
                    cam.health.latency_ms = latency_ms
                    cam.health.last_heartbeat = datetime.utcnow()
                    cam.health.processing_status = "PROCESSING" if status == "ONLINE" else "IDLE"
                db.commit()
        except Exception as e:
            logger.error(f"Failed to update camera status in DB: {e}")
        finally:
            db.close()

    def stop(self):
        self.is_running = False
        if self.task and not self.task.done():
            self.task.cancel()


class StreamManager:
    def __init__(self):
        self.workers: Dict[str, StreamWorker] = {}
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    def start_stream(self, camera_id: str, source_type: str, source_path: str, websocket_manager):
        if camera_id in self.workers and self.workers[camera_id].is_running:
            logger.info(f"Stream {camera_id} is already running.")
            return

        worker = StreamWorker(camera_id, source_type, source_path, websocket_manager)
        self.workers[camera_id] = worker

        target_loop = None
        try:
            target_loop = asyncio.get_running_loop()
        except RuntimeError:
            target_loop = self.main_loop

        if target_loop and target_loop.is_running():
            try:
                worker.task = target_loop.create_task(worker.run())
            except RuntimeError:
                worker.task = asyncio.run_coroutine_threadsafe(worker.run(), target_loop)
        else:
            import threading
            def run_worker_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(worker.run())

            t = threading.Thread(target=run_worker_thread, daemon=True)
            t.start()

    def stop_stream(self, camera_id: str):
        if camera_id in self.workers:
            self.workers[camera_id].stop()
            del self.workers[camera_id]

    def stop_all(self):
        for cid, worker in list(self.workers.items()):
            worker.stop()
        self.workers.clear()

stream_manager = StreamManager()

