import os
import time
import uuid
import asyncio
import logging
import cv2
from datetime import datetime
from typing import Dict, Optional, List, Set

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
GLOBAL_INFERENCE_SEMAPHORE = asyncio.Semaphore(3)

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

        # AI Surveillance Agent
        self.agent = AISurveillanceAgent(self.camera_id, self.ws_manager)

        # Performance & Throttling state
        self.is_inferencing = False
        self.last_ai_time = 0.0
        self.last_db_update_time = 0.0
        self.last_status = "OFFLINE"
        self.latest_tracked_objs = []
        self.latest_latency_ms = 0.0

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

    async def _async_ai_step(self, frame, loop_start):
        if self.is_inferencing:
            return
        self.is_inferencing = True
        try:
            async with GLOBAL_INFERENCE_SEMAPHORE:
                tracked_objs, latency_ms, _ = await self.agent.process_frame(frame, loop_start)
                self.latest_tracked_objs = tracked_objs
                self.latest_latency_ms = latency_ms
                self.last_ai_time = time.time()
        except Exception as e:
            logger.error(f"Error in async AI step for {self.camera_id}: {e}")
        finally:
            self.is_inferencing = False

    async def run(self):
        self.is_running = True
        logger.info(f"Starting StreamWorker for {self.camera_id} ({self.source_type}: {self.source_path})")

        self.source = self._create_source()
        frame_count = 0
        start_time = time.time()

        self._update_db_status("ONLINE", fps=0.0, latency_ms=0.0, force=True)

        while self.is_running:
            loop_start = time.time()
            ret, frame = self.source.read_frame()

            if not ret or frame is None:
                if self.source.status != "ONLINE":
                    self._update_db_status(self.source.status, fps=0.0, latency_ms=0.0)
                await asyncio.sleep(0.1)
                continue

            # 1. Fast JPEG encoding for video stream (Runs at full 25 FPS)
            ok_enc, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok_enc:
                self.latest_jpeg = buf.tobytes()

            frame_count += 1
            elapsed = time.time() - start_time
            current_fps = round(frame_count / max(1.0, elapsed), 1)

            # 2. Trigger async AI inference at sampled rate (~5-8 AI FPS), skipping intermediate frames if inference is busy
            if not self.is_inferencing and (time.time() - self.last_ai_time >= 0.12):
                asyncio.create_task(self._async_ai_step(frame.copy(), loop_start))

            # 3. Telemetry WS update (Throttled, only broadcast active detections state)
            dets_payload = [
                {
                    "track_id": t.track_id,
                    "class_name": t.class_name,
                    "confidence": t.confidence,
                    "bbox": t.bbox,
                    "dwell_time_sec": t.dwell_time_sec,
                    "is_confirmed": getattr(t, "is_confirmed", False),
                    "is_fallback": False
                } for t in self.latest_tracked_objs if getattr(t, "is_confirmed", False)
            ]

            ws_payload = {
                "type": "DETECTIONS_UPDATE",
                "camera_id": self.camera_id,
                "timestamp": datetime.utcnow().isoformat(),
                "inference_mode": "REAL AI | INFERENCE RUNNING",
                "detections": dets_payload,
                "fps": current_fps,
                "latency_ms": self.latest_latency_ms
            }

            await self.ws_manager.broadcast(ws_payload)

            # 4. Throttled DB status updates (once every 2.5 seconds instead of 25x/sec)
            if time.time() - self.last_db_update_time >= 2.5:
                self._update_db_status("ONLINE", fps=current_fps, latency_ms=self.latest_latency_ms)

            # Video rendering sleep target (~25 FPS)
            target_delay = max(0.01, (1.0 / 25.0) - (time.time() - loop_start))
            await asyncio.sleep(target_delay)

        # Cleanup on stop
        if self.source:
            self.source.release()
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
        self.subscribers: Dict[str, Set[str]] = {}
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    def get_active_confirmed_people_count(self) -> int:
        total_people = 0
        for worker in self.workers.values():
            if worker.is_running:
                for obj in worker.latest_tracked_objs:
                    if getattr(obj, "is_confirmed", False) and getattr(obj, "class_name", "") == "person":
                        total_people += 1
        return total_people

    def subscribe(self, camera_id: str, subscriber_id: str, websocket_manager=None) -> bool:
        if camera_id not in self.subscribers:
            self.subscribers[camera_id] = set()
        self.subscribers[camera_id].add(subscriber_id)
        logger.info(f"Subscription added for camera {camera_id} by {subscriber_id}. Total subscribers: {len(self.subscribers[camera_id])}")

        if camera_id not in self.workers or not self.workers[camera_id].is_running:
            db = SessionLocal()
            try:
                cam = db.query(Camera).filter((Camera.camera_id == camera_id) | (Camera.id == camera_id)).first()
                if cam and websocket_manager:
                    self.start_stream(cam.camera_id, cam.protocol, cam.stream_url, websocket_manager)
            except Exception as e:
                logger.error(f"Error starting stream on subscribe for {camera_id}: {e}")
            finally:
                db.close()
        return True

    def unsubscribe(self, camera_id: str, subscriber_id: str):
        if camera_id in self.subscribers and subscriber_id in self.subscribers[camera_id]:
            self.subscribers[camera_id].remove(subscriber_id)
            logger.info(f"Subscription removed for camera {camera_id} by {subscriber_id}. Remaining subscribers: {len(self.subscribers[camera_id])}")

            # Check if camera is primary. If camera is NOT primary and subscriber count drops to 0, stop stream worker
            if len(self.subscribers[camera_id]) == 0:
                db = SessionLocal()
                try:
                    cam = db.query(Camera).filter((Camera.camera_id == camera_id) | (Camera.id == camera_id)).first()
                    if cam and cam.role != "primary":
                        logger.info(f"No active subscribers for secondary camera {camera_id}. Stopping stream worker and pausing AI inference.")
                        self.stop_stream(camera_id)
                except Exception as e:
                    logger.error(f"Error checking camera role on unsubscribe: {e}")
                finally:
                    db.close()

    def get_subscriber_count(self, camera_id: str) -> int:
        return len(self.subscribers.get(camera_id, set()))

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
