import os
import time
import uuid
import asyncio
import logging
import cv2
from datetime import datetime
from typing import Dict, Optional, List, Set, Tuple

from database.connection import SessionLocal
from database.schema import (
    Camera, CameraHealth, CameraZone, ZoneRule,
    Event, Alert, Incident, Detection
)
from video_engine.ingestion.source import VideoSource, MP4VideoSource, WebcamVideoSource, RTSPVideoSource
from event_engine.rules.virtual_fence import point_in_polygon
from event_engine.risk.scorer import OperationalRiskScorer
from ai_engine.surveillance_agent import AISurveillanceAgent

logger = logging.getLogger(__name__)

# Global semaphore to limit concurrent AI model inference across all active cameras
GLOBAL_INFERENCE_SEMAPHORE = asyncio.Semaphore(4)

class StreamWorker:
    def __init__(self, camera_id: str, source_type: str, source_path: str, websocket_manager):
        self.camera_id = camera_id
        self.source_type = source_type.upper()
        self.source_path = str(source_path).strip()
        self.ws_manager = websocket_manager

        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.source: Optional[VideoSource] = None
        self.latest_jpeg: Optional[bytes] = None
        self.error_message: Optional[str] = None

        # AI Surveillance Agent dedicated to this camera
        self.agent = AISurveillanceAgent(self.camera_id, self.ws_manager)

        # Performance & Throttling state
        self.is_inferencing = False
        self.last_ai_time = 0.0
        self.last_ws_time = 0.0
        self.last_db_update_time = 0.0
        self.last_status = "OFFLINE"
        self.latest_tracked_objs = []
        self.latest_face_objs = []
        self.latest_anpr_objs = []
        self.latest_latency_ms = 0.0
        self.current_fps = 0.0
        self.frame_sequence = 0
        self.dropped_frames = 0
        self.frame_buffer = []  # Ring buffer of (timestamp, frame)

    def _create_source(self) -> VideoSource:
        if self.source_type == "WEBCAM":
            dev_idx = int(self.source_path) if str(self.source_path).isdigit() else 0
            return WebcamVideoSource(self.camera_id, dev_idx)
        elif self.source_type == "RTSP" or self.source_path.startswith("http://") or self.source_path.startswith("https://") or self.source_path.startswith("rtsp://"):
            return RTSPVideoSource(self.camera_id, self.source_path)
        else:
            return MP4VideoSource(self.camera_id, self.source_path)

    def get_latest_jpeg(self) -> Optional[bytes]:
        return self.latest_jpeg

    async def _async_ai_step(self, frame, loop_start, pre_frame=None):
        if self.is_inferencing:
            return
        self.is_inferencing = True
        try:
            async with GLOBAL_INFERENCE_SEMAPHORE:
                result = await self.agent.process_frame(frame, loop_start, pre_frame=pre_frame)
                if len(result) == 5:
                    objs, lat, conf, faces, anpr_objs = result
                else:
                    objs, lat, conf, faces = result
                    anpr_objs = []
                self.latest_tracked_objs = objs
                self.latest_face_objs = faces
                self.latest_anpr_objs = anpr_objs
                self.latest_latency_ms = lat
                self.last_ai_time = time.time()
        except Exception as e:
            logger.error(f"Error in async AI step for camera {self.camera_id}: {e}", exc_info=True)
        finally:
            self.is_inferencing = False

    async def run(self):
        self.is_running = True
        self.error_message = None
        logger.info(f"Starting independent StreamWorker for {self.camera_id} ({self.source_type}: {self.source_path})")

        loop = asyncio.get_running_loop()
        try:
            self.source = await loop.run_in_executor(None, self._create_source)
        except Exception as e:
            self.error_message = str(e)
            self._update_db_status("ERROR", fps=0.0, latency_ms=0.0, force=True)
            logger.error(f"Failed to create video source for {self.camera_id}: {e}")
            self.is_running = False
            return

        frame_count = 0
        start_time = time.time()

        initial_status = getattr(self.source, "status", "ONLINE")
        self._update_db_status(initial_status, fps=0.0, latency_ms=0.0, force=True)
        logger.info(f"[CAMERA ONLINE] camera={self.camera_id} status={initial_status} source={self.source_type}")

        consecutive_read_failures = 0

        while self.is_running:
            loop_start = time.time()
            try:
                ret, frame = await loop.run_in_executor(None, self.source.read_frame)
            except Exception as e:
                logger.error(f"Exception during read_frame for {self.camera_id}: {e}")
                ret, frame = False, None

            if not ret or frame is None:
                consecutive_read_failures += 1
                self.dropped_frames += 1
                source_status = getattr(self.source, "status", "ERROR")
                if consecutive_read_failures >= 10:
                    self._update_db_status(source_status, fps=0.0, latency_ms=0.0)
                    logger.warning(f"[CAMERA OFFLINE] camera={self.camera_id} status={source_status} read_failures={consecutive_read_failures} dropped={self.dropped_frames}")
                await asyncio.sleep(0.1)
                continue

            consecutive_read_failures = 0
            self.frame_sequence += 1
            cap_ts = datetime.utcnow().isoformat() + "Z"

            # Maintain rolling frame buffer (last 20 frames)
            self.frame_buffer.append(frame.copy())
            if len(self.frame_buffer) > 20:
                self.frame_buffer.pop(0)

            pre_frame = self.frame_buffer[0] if len(self.frame_buffer) > 5 else None

            # 1. Fast JPEG encoding for video stream (~25 FPS)
            try:
                ok_enc, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok_enc:
                    self.latest_jpeg = buf.tobytes()
            except Exception as e:
                logger.error(f"JPEG encode error on {self.camera_id}: {e}")

            frame_count += 1
            elapsed = time.time() - start_time
            self.current_fps = round(frame_count / max(1.0, elapsed), 1)

            if frame_count % 100 == 1:
                logger.debug(f"[FRAME RECEIVED] camera={self.camera_id} seq={self.frame_sequence} fps={self.current_fps}")

            # 2. Trigger async AI inference at sampled rate (~8-10 AI FPS), skipping intermediate frames if busy
            if not self.is_inferencing and (time.time() - self.last_ai_time >= 0.10):
                asyncio.create_task(self._async_ai_step(frame.copy(), loop_start, pre_frame=pre_frame))

            # 3. Telemetry WS broadcast (Throttled to 6 Hz per camera)
            now_ws = time.time()
            if now_ws - self.last_ws_time >= 0.16:
                self.last_ws_time = now_ws
                dets_payload = [
                    {
                        "track_id": t.track_id,
                        "class_name": t.class_name,
                        "confidence": t.confidence,
                        "bbox": t.bbox,
                        "previous_bbox": getattr(t, "previous_bbox", None),
                        "center": t.center,
                        "previous_centroid": getattr(t, "previous_centroid", None),
                        "movement_delta": getattr(t, "movement_delta", 0.0),
                        "velocity": getattr(t, "velocity", 0.0),
                        "direction": getattr(t, "direction", "STATIONARY"),
                        "movement_state": getattr(t, "movement_state", "STATIONARY"),
                        "dwell_time_sec": t.dwell_time_sec,
                        "is_confirmed": getattr(t, "is_confirmed", False),
                        "is_fallback": False
                    } for t in self.latest_tracked_objs
                ]

                ws_payload = {
                    "type": "DETECTIONS_UPDATE",
                    "camera_id": self.camera_id,
                    "frame_sequence": self.frame_sequence,
                    "dropped_frames": self.dropped_frames,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "inference_mode": "REAL AI | INFERENCE RUNNING",
                    "detections": dets_payload,
                    "faces": self.latest_face_objs,
                    "anpr": getattr(self, 'latest_anpr_objs', []),
                    "fps": self.current_fps,
                    "latency_ms": self.latest_latency_ms
                }

                try:
                    await self.ws_manager.broadcast(ws_payload)
                except Exception as e:
                    logger.debug(f"WS broadcast error for {self.camera_id}: {e}")

            # 4. Throttled DB status updates (once every 2.5 seconds)
            if time.time() - self.last_db_update_time >= 2.5:
                self._update_db_status("ONLINE", fps=self.current_fps, latency_ms=self.latest_latency_ms)

            # Frame rate target delay (~25 FPS)
            target_delay = max(0.01, (1.0 / 25.0) - (time.time() - loop_start))
            await asyncio.sleep(target_delay)

        # Cleanup on worker stop
        if self.source:
            try:
                self.source.release()
            except Exception as e:
                logger.error(f"Error releasing source for {self.camera_id}: {e}")
        self._update_db_status("STOPPED", fps=0.0, latency_ms=0.0, force=True)
        logger.info(f"StreamWorker for {self.camera_id} stopped cleanly.")

    def _update_db_status(self, status: str, fps: float, latency_ms: float, force: bool = False):
        now = time.time()
        if not force and status == self.last_status and (now - self.last_db_update_time < 2.5):
            return

        self.last_db_update_time = now
        self.last_status = status

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
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
            logger.error(f"Failed to update camera status in DB for {self.camera_id}: {e}")
        finally:
            db.close()

    def stop(self):
        self.is_running = False
        if self.task and not self.task.done():
            self.task.cancel()


class StreamManager:
    def __init__(self):
        self.workers: Dict[str, StreamWorker] = {}
        self.subscribers: Dict[str, Set[str]] = {}
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    def _resolve_camera_identifier(self, identifier: str) -> Tuple[str, Optional[Camera]]:
        """Resolves identifier to canonical camera_id string (e.g. CAM-01) and DB Camera instance."""
        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == identifier) | (Camera.id == identifier)).first()
            if cam:
                return cam.camera_id, cam
            return identifier, None
        finally:
            db.close()

    def get_active_confirmed_people_count(self) -> int:
        total_people = 0
        for worker in list(self.workers.values()):
            if worker.is_running:
                for obj in worker.latest_tracked_objs:
                    if getattr(obj, "is_confirmed", False) and getattr(obj, "class_name", "") == "person":
                        total_people += 1
        return total_people

    def get_worker(self, identifier: str) -> Optional[StreamWorker]:
        if identifier in self.workers:
            return self.workers[identifier]
        canonical_id, _ = self._resolve_camera_identifier(identifier)
        return self.workers.get(canonical_id)

    def subscribe(self, camera_id: str, subscriber_id: str, websocket_manager=None) -> bool:
        canonical_id, cam = self._resolve_camera_identifier(camera_id)
        if canonical_id not in self.subscribers:
            self.subscribers[canonical_id] = set()
        self.subscribers[canonical_id].add(subscriber_id)
        logger.info(f"Subscription added for camera {canonical_id} by {subscriber_id}. Total: {len(self.subscribers[canonical_id])}")

        if canonical_id not in self.workers or not self.workers[canonical_id].is_running:
            if cam and cam.status != "STOPPED" and websocket_manager:
                self.start_stream(cam.camera_id, cam.protocol, cam.stream_url, websocket_manager)
        return True

    def unsubscribe(self, camera_id: str, subscriber_id: str):
        canonical_id, _ = self._resolve_camera_identifier(camera_id)
        if canonical_id in self.subscribers and subscriber_id in self.subscribers[canonical_id]:
            self.subscribers[canonical_id].remove(subscriber_id)
            logger.info(f"Subscription removed for camera {canonical_id} by {subscriber_id}. Remaining: {len(self.subscribers[canonical_id])}")
        # Secondary cameras are NOT auto-stopped on unsubscribe. They continue running independently.

    def get_subscriber_count(self, camera_id: str) -> int:
        canonical_id, _ = self._resolve_camera_identifier(camera_id)
        return len(self.subscribers.get(canonical_id, set()))

    def start_stream(self, camera_id: str, source_type: str, source_path: str, websocket_manager):
        canonical_id, _ = self._resolve_camera_identifier(camera_id)

        if canonical_id in self.workers and self.workers[canonical_id].is_running:
            logger.info(f"Stream {canonical_id} is already running.")
            return

        worker = StreamWorker(canonical_id, source_type, source_path, websocket_manager)
        self.workers[canonical_id] = worker

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
        canonical_id, _ = self._resolve_camera_identifier(camera_id)
        keys_to_stop = []
        for key, worker in list(self.workers.items()):
            if key in [camera_id, canonical_id] or worker.camera_id in [camera_id, canonical_id]:
                keys_to_stop.append(key)

        for key in keys_to_stop:
            if key in self.workers:
                self.workers[key].stop()
                del self.workers[key]

    def stop_all(self):
        for cid, worker in list(self.workers.items()):
            worker.stop()
        self.workers.clear()

stream_manager = StreamManager()
