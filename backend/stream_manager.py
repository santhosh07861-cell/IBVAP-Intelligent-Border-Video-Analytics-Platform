import os
import time
import uuid
import queue
import asyncio
import logging
import cv2
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List, Set, Tuple

from database.connection import SessionLocal
from database.schema import (
    Camera, CameraHealth, CameraZone, ZoneRule,
    Event, Alert, Incident, Detection
)
from video_engine.ingestion.source import VideoSource, create_video_source
from event_engine.rules.virtual_fence import point_in_polygon
from event_engine.risk.scorer import OperationalRiskScorer
from ai_engine.surveillance_agent import AISurveillanceAgent

logger = logging.getLogger("stream_manager")

# Global inference semaphore — created lazily inside the running event loop
# to avoid Python 3.12+ asyncio deprecation for module-level Semaphore creation.
# On CPU (MODEL_DEVICE=cpu), max 2 concurrent inferences prevents core thrashing.
_INFERENCE_SEMAPHORE: Optional[asyncio.Semaphore] = None

def _get_inference_semaphore() -> asyncio.Semaphore:
    """Lazily create the bounded inference semaphore inside the running event loop."""
    global _INFERENCE_SEMAPHORE
    if _INFERENCE_SEMAPHORE is None:
        max_ai = int(os.getenv("MAX_CONCURRENT_AI_INFERENCE", "2"))
        _INFERENCE_SEMAPHORE = asyncio.Semaphore(max_ai)
    return _INFERENCE_SEMAPHORE

class StreamWorker:
    def __init__(self, camera_id: str, source_type: str, source_path: str, websocket_manager, rotation: int = 0):
        self.camera_id = camera_id
        self.source_type = source_type.upper()
        self.source_path = str(source_path).strip()
        self.ws_manager = websocket_manager
        self.rotation = int(rotation) % 360
        self.stream_manager = None

        self.is_running = True
        self.task: Optional[asyncio.Task] = None
        self.source: Optional[VideoSource] = None
        self.latest_jpeg: Optional[bytes] = None
        self.error_message: Optional[str] = None

        # AI Surveillance Agent dedicated to this camera
        self.agent = AISurveillanceAgent(self.camera_id, self.ws_manager)

        # Camera Metadata Cache
        self.camera_uuid = ""
        self.camera_name = f"Camera {self.camera_id}"
        self.camera_location = "Campus Security"
        self.camera_lat = 26.9124
        self.camera_lng = 70.9025
        self._load_camera_metadata()

        # Performance, Inference Queuing & Throttling state
        self.is_inferencing = False
        self._pending_ai_frame: Optional[Tuple[np.ndarray, float, Optional[np.ndarray]]] = None
        self.last_ai_time = 0.0
        self.last_jpeg_time = 0.0
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
        self.pending_push_frames = queue.Queue(maxsize=10)

    def _load_camera_metadata(self):
        try:
            db = SessionLocal()
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            if cam:
                self.camera_uuid = cam.id
                self.camera_name = cam.name or f"Camera {self.camera_id}"
                self.camera_location = cam.location or "Campus Security"
                self.camera_lat = float(cam.latitude) if cam.latitude is not None else 26.9124
                self.camera_lng = float(cam.longitude) if cam.longitude is not None else 70.9025
            db.close()
        except Exception:
            pass

    def _create_source(self) -> VideoSource:
        return create_video_source(self.camera_id, self.source_type, self.source_path)

    def push_frame(self, frame: np.ndarray) -> bool:
        """Pushes a video frame to this camera worker, buffering if source is initializing."""
        if self.source and hasattr(self.source, "push_frame"):
            while not self.pending_push_frames.empty():
                try:
                    f = self.pending_push_frames.get_nowait()
                    self.source.push_frame(f)
                except queue.Empty:
                    break
            self.source.push_frame(frame)
            return True
        else:
            if self.pending_push_frames.full():
                try:
                    self.pending_push_frames.get_nowait()
                except queue.Empty:
                    pass
            self.pending_push_frames.put(frame)
            return True

    def get_latest_jpeg(self) -> Optional[bytes]:
        return self.latest_jpeg

    async def _async_ai_step(self, initial_frame=None, loop_start=None, pre_frame=None):
        if self.is_inferencing:
            return
        self.is_inferencing = True
        sem = _get_inference_semaphore()
        try:
            async with sem:
                # If a fresher frame arrived while waiting for semaphore, consume the latest frame
                if self._pending_ai_frame is not None:
                    target_frame, target_start, target_pre = self._pending_ai_frame
                    self._pending_ai_frame = None
                elif initial_frame is not None:
                    target_frame, target_start, target_pre = initial_frame, (loop_start or time.time()), pre_frame
                else:
                    return

                result = await self.agent.process_frame(target_frame, target_start, pre_frame=target_pre)
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
                # Structured log: track updates
                if objs:
                    confirmed = [o for o in objs if getattr(o, 'is_confirmed', False)]
                    if confirmed:
                        logger.debug(f"[TRACK_UPDATED] camera={self.camera_id} confirmed_tracks={len(confirmed)} latency_ms={lat:.1f}")
        except Exception as e:
            logger.error(f"Error in async AI step for camera {self.camera_id}: {e}", exc_info=True)
        finally:
            self.is_inferencing = False

    async def run(self):
        self.is_running = True
        self.error_message = None
        logger.info(f"Starting independent StreamWorker for {self.camera_id} ({self.source_type}: {self.source_path})")

        loop = asyncio.get_running_loop()
        while self.is_running and self.source is None:
            try:
                self.source = await loop.run_in_executor(None, self._create_source)
                if self.source:
                    break
            except Exception as e:
                self.error_message = str(e)
                if self.source_type == "MP4":
                    self._update_db_status("FILE ERROR", fps=0.0, latency_ms=0.0, force=True)
                    logger.warning(f"MP4 Video source init for {self.camera_id} failed: {e}.")
                    return
                self._update_db_status("UNREACHABLE", fps=0.0, latency_ms=0.0, force=True)
                logger.warning(f"Video source init for {self.camera_id} failed: {e}. Retrying in 3.0s...")
                await asyncio.sleep(3.0)

        if not self.is_running:
            return

        if self.source_type == "MP4" and getattr(self.source, "status", "") == "FILE ERROR":
            self._update_db_status("FILE ERROR", fps=0.0, latency_ms=0.0, force=True)
            logger.warning(f"MP4 file for {self.camera_id} cannot be opened or decoded.")
            return

        # Drain any pending pushed frames into newly created source
        while not self.pending_push_frames.empty():
            try:
                f = self.pending_push_frames.get_nowait()
                if hasattr(self.source, "push_frame"):
                    self.source.push_frame(f)
            except queue.Empty:
                break

        frame_count = 0
        start_time = time.time()

        initial_status = "READY" if self.source_type == "MP4" else getattr(self.source, "status", "CONNECTING")
        self._update_db_status(initial_status, fps=0.0, latency_ms=0.0, force=True)
        logger.info(f"[CAMERA_CONNECTED] camera={self.camera_id} status={initial_status} source_type={self.source_type} path={self.source_path}")

        consecutive_read_failures = 0

        try:
            while self.is_running:
                loop_start = time.time()
                try:
                    ret, frame = await loop.run_in_executor(None, self.source.read_frame)
                except Exception as e:
                    logger.error(f"Exception during read_frame for {self.camera_id}: {e}")
                    ret, frame = False, None

                if not ret or frame is None:
                    if self.source_type == "MP4":
                        # End of Video reached: Stop processing, set COMPLETED, clear detections, stop worker
                        self.latest_tracked_objs = []
                        self.latest_face_objs = []
                        self.latest_anpr_objs = []
                        self.current_fps = 0.0
                        self.agent.cleanup_live_session()
                        self._update_db_status("COMPLETED", fps=0.0, latency_ms=0.0, force=True)
                        logger.info(f"[CAMERA_STATUS_UPDATE] MP4 camera={self.camera_id} status=COMPLETED (End of video reached)")
                        try:
                            await self.ws_manager.broadcast({
                                "type": "DETECTIONS_UPDATE",
                                "camera_id": self.camera_id,
                                "camera_uuid": self.camera_uuid,
                                "camera_number": self.camera_id,
                                "camera_name": self.camera_name,
                                "frame_sequence": self.frame_sequence,
                                "dropped_frames": self.dropped_frames,
                                "timestamp": datetime.utcnow().isoformat() + "Z",
                                "inference_mode": "IDLE",
                                "status": "COMPLETED",
                                "detections": [],
                                "faces": [],
                                "anpr": [],
                                "fps": 0.0,
                                "latency_ms": 0.0
                            })
                        except Exception:
                            pass
                        break

                    consecutive_read_failures += 1
                    self.dropped_frames += 1
                    source_status = getattr(self.source, "status", "ERROR")

                    # If camera has not received its first frame yet, give it a warmup window as CONNECTING (or UNREACHABLE if source marked unreachable)
                    is_push = hasattr(self.source, "push_frame")
                    now_ts = time.time()
                    warmup_period = (frame_count == 0 and (now_ts - start_time < 8.0))

                    if warmup_period:
                        self.current_fps = 0.0
                        interim_status = "UNREACHABLE" if source_status == "UNREACHABLE" else "CONNECTING"
                        self._update_db_status(interim_status, fps=0.0, latency_ms=0.0)
                        await asyncio.sleep(0.10)
                        continue

                    # For push streams or active connections, require sustained failures before marking NO_FRAMES/UNREACHABLE
                    failure_threshold = 40 if is_push else 20
                    if consecutive_read_failures == failure_threshold:
                        self.latest_tracked_objs = []
                        self.latest_face_objs = []
                        self.latest_anpr_objs = []
                        self.current_fps = 0.0
                        self.agent.cleanup_live_session()
                        final_status = "UNREACHABLE" if source_status == "UNREACHABLE" else "NO_FRAMES"
                        self._update_db_status(final_status, fps=0.0, latency_ms=0.0, force=True)
                        logger.warning(f"[CAMERA_STATUS_UPDATE] camera={self.camera_id} status={final_status} consecutive_failures={consecutive_read_failures}")
                        try:
                            await self.ws_manager.broadcast({
                                "type": "DETECTIONS_UPDATE",
                                "camera_id": self.camera_id,
                                "camera_uuid": self.camera_uuid,
                                "camera_number": self.camera_id,
                                "camera_name": self.camera_name,
                                "frame_sequence": self.frame_sequence,
                                "dropped_frames": self.dropped_frames,
                                "timestamp": datetime.utcnow().isoformat() + "Z",
                                "inference_mode": "IDLE",
                                "status": final_status,
                                "detections": [],
                                "faces": [],
                                "anpr": [],
                                "fps": 0.0,
                                "latency_ms": 0.0
                            })
                        except Exception:
                            pass
                    elif consecutive_read_failures % 50 == 0:
                        retry_status = "UNREACHABLE" if source_status == "UNREACHABLE" else "NO_FRAMES"
                        self._update_db_status(retry_status, fps=0.0, latency_ms=0.0)
                    sleep_dur = 0.3 if consecutive_read_failures > 20 else 0.05
                    await asyncio.sleep(sleep_dur)
                    continue

                if consecutive_read_failures >= 10:
                    active_status = "PLAYING" if self.source_type == "MP4" else "ONLINE"
                    logger.info(f"[CAMERA_RECONNECTED] camera={self.camera_id} reconnected successfully")
                    self._update_db_status(active_status, fps=self.current_fps, latency_ms=self.latest_latency_ms, force=True)

                consecutive_read_failures = 0
                self.frame_sequence += 1
                cap_ts = datetime.utcnow().isoformat() + "Z"

                # Apply camera rotation if configured (0°, 90°, 180°, 270°)
                if self.rotation == 90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif self.rotation == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif self.rotation == 270:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                # Maintain rolling frame buffer (last 20 frames)
                self.frame_buffer.append(frame.copy())
                if len(self.frame_buffer) > 20:
                    self.frame_buffer.pop(0)

                pre_frame = self.frame_buffer[0] if len(self.frame_buffer) > 5 else None

                # 1. Fast JPEG encoding for video stream (kept fresh at ~20 FPS for instant client playback)
                now_enc = time.time()
                if now_enc - self.last_jpeg_time >= 0.05:
                    self.last_jpeg_time = now_enc
                    try:
                        ok_enc, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        if ok_enc:
                            self.latest_jpeg = buf.tobytes()
                    except Exception as e:
                        logger.error(f"JPEG encode error on {self.camera_id}: {e}")

                frame_count += 1
                elapsed = time.time() - start_time
                self.current_fps = round(frame_count / max(1.0, elapsed), 1)

                active_status = "PLAYING" if self.source_type == "MP4" else "ONLINE"
                if frame_count == 1:
                    self._update_db_status(active_status, fps=max(1.0, self.current_fps), latency_ms=self.latest_latency_ms, force=True)
                    logger.info(f"[CAMERA] frame received camera={self.camera_id} seq={self.frame_sequence} fps={self.current_fps} status={active_status}")
                    logger.info(f"[CAMERA] frame width/height={frame.shape[1]}x{frame.shape[0]} camera={self.camera_id}")
                elif frame_count % 100 == 0:
                    logger.info(f"[CAMERA] frame received camera={self.camera_id} seq={self.frame_sequence} fps={self.current_fps} status={active_status}")
                    logger.info(f"[CAMERA] frame width/height={frame.shape[1]}x{frame.shape[0]} camera={self.camera_id}")

                # 2. Update pending frame buffer and trigger async AI inference at controlled rate (~8-10 AI FPS)
                self._pending_ai_frame = (frame, loop_start, pre_frame)
                if not self.is_inferencing and (time.time() - self.last_ai_time >= 0.10):
                    asyncio.create_task(self._async_ai_step())

                # 3. Telemetry WS broadcast (Throttled to 6 Hz per camera)
                now_ws = time.time()
                if now_ws - self.last_ws_time >= 0.16:
                    self.last_ws_time = now_ws
                    now_utc_str = datetime.utcnow().isoformat() + "Z"
                    dets_payload = [
                        {
                            "camera_id": self.camera_id,
                            "camera_uuid": self.camera_uuid,
                            "camera_number": self.camera_id,
                            "camera_name": self.camera_name,
                            "location": self.camera_location,
                            "latitude": self.camera_lat,
                            "longitude": self.camera_lng,
                            "track_id": t.track_id,
                            "class_name": t.class_name,
                            "confidence": t.confidence,
                            "bbox": t.bbox,
                            "timestamp": now_utc_str,
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
                        "camera_uuid": self.camera_uuid,
                        "camera_number": self.camera_id,
                        "camera_name": self.camera_name,
                        "location": self.camera_location,
                        "frame_sequence": self.frame_sequence,
                        "dropped_frames": self.dropped_frames,
                        "timestamp": now_utc_str,
                        "inference_mode": "REAL AI | PROCESSING" if self.source_type == "MP4" else "REAL AI | INFERENCE RUNNING",
                        "status": active_status if self.current_fps > 0 else ("READY" if self.source_type == "MP4" else "CONNECTING"),
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
                    self._update_db_status(active_status, fps=self.current_fps, latency_ms=self.latest_latency_ms)

                # Frame rate target delay matching native video FPS
                native_fps = getattr(self.source, "fps", 25.0) or 25.0
                target_delay = max(0.005, (1.0 / native_fps) - (time.time() - loop_start))
                await asyncio.sleep(target_delay)

        finally:
            # Complete cleanup on worker stop / disconnect
            if self.source:
                try:
                    self.source.release()
                except Exception as e:
                    logger.error(f"Error releasing source for {self.camera_id}: {e}")
            self.latest_jpeg = None
            self.frame_buffer.clear()
            self.latest_tracked_objs = []
            self.latest_face_objs = []
            self.latest_anpr_objs = []
            self.current_fps = 0.0
            self.latest_latency_ms = 0.0
            try:
                self.agent.cleanup_live_session()
            except Exception as e:
                logger.error(f"Error cleaning up live session for {self.camera_id}: {e}")
            
            if self.source_type == "MP4" and self.last_status in ["COMPLETED", "FILE ERROR"]:
                final_stop_status = self.last_status
            else:
                final_stop_status = "STOPPED"
            self._update_db_status(final_stop_status, fps=0.0, latency_ms=0.0, force=True)
            try:
                await self.ws_manager.broadcast({
                    "type": "DETECTIONS_UPDATE",
                    "camera_id": self.camera_id,
                    "frame_sequence": self.frame_sequence,
                    "dropped_frames": self.dropped_frames,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "inference_mode": "IDLE",
                    "status": final_stop_status,
                    "detections": [],
                    "faces": [],
                    "anpr": [],
                    "fps": 0.0,
                    "latency_ms": 0.0
                })
            except Exception:
                pass
            logger.info(f"StreamWorker for {self.camera_id} stopped cleanly with status {final_stop_status}.")

    def _update_db_status(self, status: str, fps: float, latency_ms: float, force: bool = False):
        now = time.time()
        # Guard: Never record ONLINE in DB if FPS is 0.0 — use transitional CONNECTING or NO_FRAMES
        if self.source_type == "MP4":
            effective_status = status
        else:
            effective_status = "CONNECTING" if (status == "ONLINE" and fps <= 0.0) else status

        if not force and effective_status == self.last_status and (now - self.last_db_update_time < 2.5):
            return

        self.last_db_update_time = now
        self.last_status = effective_status

        db = SessionLocal()
        try:
            cam = db.query(Camera).filter((Camera.camera_id == self.camera_id) | (Camera.id == self.camera_id)).first()
            if cam:
                cam.status = effective_status
                cam.fps = fps
                if cam.health:
                    cam.health.status = effective_status
                    cam.health.fps = fps
                    cam.health.latency_ms = latency_ms
                    cam.health.last_heartbeat = datetime.utcnow()
                    if effective_status in ["ONLINE", "PLAYING", "PROCESSING"]:
                        cam.health.processing_status = "PROCESSING"
                    elif effective_status == "READY":
                        cam.health.processing_status = "READY"
                    elif effective_status == "FILE ERROR":
                        cam.health.processing_status = "ERROR"
                    else:
                        cam.health.processing_status = "IDLE"
                db.commit()
        except Exception as e:
            logger.error(f"Failed to update camera status in DB for {self.camera_id}: {e}")
        finally:
            db.close()

    def stop(self):
        self.is_running = False
        try:
            self.agent.shutdown()
        except Exception:
            pass
        if self.source:
            try:
                self.source.release()
            except Exception:
                pass
        if self.task and not self.task.done():
            self.task.cancel()


class StreamManager:
    def __init__(self):
        self.workers: Dict[str, StreamWorker] = {}
        self.subscribers: Dict[str, Set[str]] = {}
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._id_cache: Dict[str, Tuple[str, float]] = {}

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    def resolve_canonical_id_cached(self, identifier: str) -> str:
        """Cached fast resolution of camera identifier to canonical ID without hitting SQLite."""
        if not identifier:
            return ""
        if identifier in self.workers:
            return identifier
        now = time.time()
        cached = self._id_cache.get(identifier)
        if cached and (now - cached[1] < 60.0):
            return cached[0]
        canonical_id, _ = self._resolve_camera_identifier(identifier)
        self._id_cache[identifier] = (canonical_id, now)
        return canonical_id

    def clear_id_cache(self, identifier: Optional[str] = None):
        if identifier:
            self._id_cache.pop(identifier, None)
        else:
            self._id_cache.clear()

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
        canonical_id = self.resolve_canonical_id_cached(identifier)
        return self.workers.get(canonical_id)

    def subscribe(self, camera_id: str, subscriber_id: str, websocket_manager=None) -> bool:
        canonical_id = self.resolve_canonical_id_cached(camera_id)
        if canonical_id not in self.subscribers:
            self.subscribers[canonical_id] = set()
        self.subscribers[canonical_id].add(subscriber_id)
        logger.info(f"Subscription added for camera {canonical_id} by {subscriber_id}. Total: {len(self.subscribers[canonical_id])}")

        if canonical_id not in self.workers or not self.workers[canonical_id].is_running:
            _, cam = self._resolve_camera_identifier(camera_id)
            if cam and cam.status not in ["STOPPED", "COMPLETED", "FILE ERROR"] and websocket_manager:
                self.start_stream(cam.camera_id, cam.protocol, cam.stream_url, websocket_manager)
        return True

    def unsubscribe(self, camera_id: str, subscriber_id: str):
        canonical_id = self.resolve_canonical_id_cached(camera_id)
        if canonical_id in self.subscribers and subscriber_id in self.subscribers[canonical_id]:
            self.subscribers[canonical_id].remove(subscriber_id)
            logger.info(f"Subscription removed for camera {canonical_id} by {subscriber_id}. Remaining: {len(self.subscribers[canonical_id])}")
        # Secondary cameras are NOT auto-stopped on unsubscribe. They continue running independently.

    def get_subscriber_count(self, camera_id: str) -> int:
        canonical_id = self.resolve_canonical_id_cached(camera_id)
        return len(self.subscribers.get(canonical_id, set()))

    def start_stream(self, camera_id: str, source_type: str, source_path: str, websocket_manager, rotation: Optional[int] = None):
        canonical_id, cam = self._resolve_camera_identifier(camera_id)
        self._id_cache[camera_id] = (canonical_id, time.time())
        self._id_cache[canonical_id] = (canonical_id, time.time())

        if canonical_id in self.workers and self.workers[canonical_id].is_running:
            logger.info(f"Stream {canonical_id} is already running.")
            return

        if rotation is None and cam and hasattr(cam, "rotation") and cam.rotation is not None:
            rot_val = cam.rotation
        else:
            rot_val = rotation or 0

        worker = StreamWorker(canonical_id, source_type, source_path, websocket_manager, rotation=rot_val)
        worker.stream_manager = self
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
        canonical_id = self.resolve_canonical_id_cached(camera_id)
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

    def push_frame(self, camera_id: str, frame: np.ndarray) -> bool:
        """Pushes a video frame into the camera's worker if active."""
        canonical_id = self.resolve_canonical_id_cached(camera_id)
        worker = self.get_worker(canonical_id)
        if worker and (worker.is_running or (worker.task and not worker.task.done())):
            return worker.push_frame(frame)
        return False

    def suppress_alert_across_workers(self, camera_id: Optional[str] = None, alert_id: Optional[str] = None, track_id: Optional[int] = None, zone_id: Optional[str] = None, duration_sec: float = 120.0):
        """Notifies active stream workers to temporarily suppress recreation of deleted alerts."""
        canonical_id = None
        if camera_id:
            canonical_id, _ = self._resolve_camera_identifier(camera_id)
        for cid, worker in list(self.workers.items()):
            if canonical_id is None or cid == canonical_id or getattr(worker, "camera_id", "") == canonical_id:
                if hasattr(worker, "agent") and hasattr(worker.agent, "suppress_alert"):
                    worker.agent.suppress_alert(alert_id, track_id, zone_id, duration_sec)

    def suppress_face_across_workers(self, camera_id: Optional[str] = None, track_id: Optional[int] = None, identity_name: Optional[str] = None, duration_sec: float = 120.0):
        """Notifies active stream workers to temporarily suppress recreation of deleted face records."""
        canonical_id = None
        if camera_id:
            canonical_id, _ = self._resolve_camera_identifier(camera_id)
        for cid, worker in list(self.workers.items()):
            if canonical_id is None or cid == canonical_id or getattr(worker, "camera_id", "") == canonical_id:
                if hasattr(worker, "agent") and hasattr(worker.agent, "suppress_face"):
                    worker.agent.suppress_face(track_id, identity_name, duration_sec)

stream_manager = StreamManager()

