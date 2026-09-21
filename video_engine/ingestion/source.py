import os
import time
import logging
import queue
import urllib.request
import urllib.parse
from abc import ABC, abstractmethod
from typing import Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("video_engine")

class VideoSource(ABC):
    def __init__(self, camera_id: str, stream_url: str):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.status = "OFFLINE"
        self.fps = 0.0
        self.width = 0
        self.height = 0
        self.dropped_frames = 0
        self.reconnect_attempts = 0
        self.last_frame_time = time.time()
        self.first_frame_logged = False
        self._frame_count = 0
        self._fps_start_time = time.time()

    @abstractmethod
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Reads and returns the next (success, frame) tuple."""
        pass

    @abstractmethod
    def release(self):
        """Releases video source resources."""
        pass

    def _track_fps_and_log(self, frame: np.ndarray, source_type: str):
        now = time.time()
        self.last_frame_time = now
        self.status = "ONLINE"
        self.dropped_frames = 0
        self.height, self.width = frame.shape[:2]

        if not self.first_frame_logged:
            self.first_frame_logged = True
            logger.info(f"[CAMERA FRAME] Camera {self.camera_id} received first frame {self.width}x{self.height} from {source_type} ({self.stream_url})")

        self._frame_count += 1
        elapsed = now - self._fps_start_time
        if elapsed >= 3.0:
            self.fps = round(self._frame_count / max(0.1, elapsed), 1)
            self._frame_count = 0
            self._fps_start_time = now
            logger.debug(f"[CAMERA FPS] Camera {self.camera_id} running at {self.fps:.1f} FPS")


class MP4VideoSource(VideoSource):
    """
    Ingests pre-recorded MP4 video files frame-by-frame.
    Transitions through READY -> PLAYING -> COMPLETED (or FILE ERROR).
    Never loops automatically on EOF unless explicitly requested.
    """
    def __init__(self, camera_id: str, file_path: str):
        clean_path = str(file_path).strip()
        if (clean_path.startswith("'") and clean_path.endswith("'")) or (clean_path.startswith('"') and clean_path.endswith('"')):
            clean_path = clean_path[1:-1].strip()
        super().__init__(camera_id, clean_path)
        self.cap = None
        self.total_frames = 0
        self.current_frame_idx = 0
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connecting to {self.stream_url} (type: mp4)")
        self._connect()

    def _connect(self):
        self.status = "READY"
        target_path = self.stream_url
        if not os.path.exists(target_path) and not os.path.isabs(target_path):
            alt_path = os.path.join(os.getcwd(), target_path)
            if os.path.exists(alt_path):
                target_path = alt_path

        if not os.path.exists(target_path) and not target_path.startswith("http"):
            self.status = "FILE ERROR"
            logger.warning(f"[CAMERA ERROR] MP4 file does not exist on disk for {self.camera_id}: {self.stream_url}")
            return

        self.cap = cv2.VideoCapture(target_path)
        if self.cap.isOpened():
            self.status = "READY"
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            if fps and fps > 0:
                self.fps = fps
            else:
                self.fps = 25.0
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self.current_frame_idx = 0
            logger.info(f"[CAMERA CONNECT] MP4 video file opened for {self.camera_id}: {self.stream_url} ({self.width}x{self.height} @ {self.fps} FPS, {self.total_frames} frames)")
        else:
            self.status = "FILE ERROR"
            logger.warning(f"[CAMERA ERROR] MP4VideoSource failed to open/decode file for {self.camera_id}: {self.stream_url}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.status in ["COMPLETED", "FILE ERROR"]:
            return False, None

        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            # End of Video reached: Stop processing, mark COMPLETED, DO NOT LOOP
            self.status = "COMPLETED"
            logger.info(f"[CAMERA EOF] Camera {self.camera_id} reached end of MP4 video ({self.current_frame_idx}/{self.total_frames} frames). Status set to COMPLETED.")
            return False, None

        self.current_frame_idx += 1
        self.status = "PLAYING"
        self._track_fps_and_log(frame, "mp4")
        return True, frame

    def release(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self.status != "COMPLETED":
            self.status = "STOPPED"
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} MP4 video source released.")


class WebcamVideoSource(VideoSource):
    """
    Ingests webcams via dual-mode support:
    1. Direct push frames from browser client session (navigator.mediaDevices.getUserMedia)
    2. Local USB or built-in FaceTime HD webcams via OpenCV / AVFoundation hardware capture.
    """
    def __init__(self, camera_id: str, device_index: int = 0):
        super().__init__(camera_id, str(device_index))
        self.device_index = int(device_index) if str(device_index).isdigit() else 0
        self.cap = None
        self.is_fallback_video = False
        self.fallback_path = "storage/demo_videos/border_patrol.mp4"
        self.frame_queue = queue.Queue(maxsize=10)
        self.last_push_time = 0.0
        self._init_time = time.time()
        self.reconnect_cooldown = 2.0
        self.last_reconnect_time = 0.0
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} initialized WebcamVideoSource (device index {self.device_index})")
        # Delay hardware connect slightly so browser push streams can claim immediately without device contention
        self.status = "CONNECTING"

    def push_frame(self, frame: np.ndarray):
        """Thread-safe ingestion of frames pushed from client/browser webcam session."""
        now = time.time()
        self.last_push_time = now
        self.status = "ONLINE"
        if self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
        self.frame_queue.put(frame)

    def _connect(self):
        now = time.time()
        # If client is actively pushing frames or stream just started, skip OpenCV hardware capture to avoid hardware locks
        if now - self.last_push_time < 5.0 or (self.last_push_time == 0.0 and now - self._init_time < 2.5):
            return

        if now - self.last_reconnect_time < self.reconnect_cooldown:
            return
        self.last_reconnect_time = now

        self.status = "CONNECTING"
        try:
            self.cap = cv2.VideoCapture(self.device_index)
            if not self.cap.isOpened():
                # Try explicit AVFoundation on macOS
                self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_AVFOUNDATION)

            if self.cap.isOpened():
                # Warm up hardware sensor
                for _ in range(3):
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        self.status = "ONLINE"
                        self.is_fallback_video = False
                        self._track_fps_and_log(frame, "webcam_hw")
                        return
                self.status = "ONLINE"
                self.is_fallback_video = False
            else:
                # Cloud / Headless fallback: use border patrol video simulation
                if os.path.exists(self.fallback_path):
                    self.cap = cv2.VideoCapture(self.fallback_path)
                    if self.cap.isOpened():
                        self.status = "ONLINE"
                        self.is_fallback_video = True
                        logger.info(f"[CAMERA CLOUD FALLBACK] Headless cloud environment detected for {self.camera_id}. Streaming demo border video.")
                        return
                self.status = "ERROR"
                logger.warning(f"[CAMERA ERROR] Webcam device {self.device_index} for {self.camera_id} could not be opened.")
        except Exception as e:
            if os.path.exists(self.fallback_path):
                try:
                    self.cap = cv2.VideoCapture(self.fallback_path)
                    if self.cap.isOpened():
                        self.status = "ONLINE"
                        self.is_fallback_video = True
                        return
                except Exception:
                    pass
            self.status = "ERROR"
            logger.error(f"[CAMERA ERROR] Error opening webcam device {self.device_index} for {self.camera_id}: {e}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        now = time.time()
        # 1. Prioritize frames pushed from client browser session
        try:
            timeout = 0.08 if (now - self.last_push_time < 5.0 or self.last_push_time == 0.0) else 0.01
            frame = self.frame_queue.get(timeout=timeout)
            self._track_fps_and_log(frame, "webcam_push")
            return True, frame
        except queue.Empty:
            pass

        # If client recently pushed frames or stream just initialized, do not lock hardware
        if (now - self.last_push_time < 5.0) or (self.last_push_time == 0.0 and now - self._init_time < 2.5):
            return False, None

        # 2. Otherwise fall back to local OpenCV hardware capture
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            if self.is_fallback_video and self.cap:
                # Loop fallback video
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
            else:
                time.sleep(0.01)
                ret, frame = self.cap.read()

        if ret and frame is not None:
            self._track_fps_and_log(frame, "webcam_simulated" if self.is_fallback_video else "webcam_hw")
            return True, frame
        else:
            self.dropped_frames += 1
            if self.dropped_frames > 20:
                logger.warning(f"[CAMERA DISCONNECT] Webcam {self.camera_id} dropped {self.dropped_frames} frames. Triggering reconnect.")
                self.release()
                self._connect()
            return False, None

    def release(self):
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.status = "OFFLINE"
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} webcam released.")


class HTTPMJPEGVideoSource(VideoSource):
    """
    Dedicated HTTP MJPEG / Phone IP Camera Video Ingestion Engine (e.g. Android IP Webcam, DroidCam).
    Features dual-mode reading (OpenCV VideoCapture + fallback direct streaming multipart JPEG parser),
    automatic reconnect backoff, timeout detection, and real-time FPS computation.
    """
    def __init__(self, camera_id: str, stream_url: str, timeout_sec: int = 8):
        url = stream_url.strip()
        parsed_p = urllib.parse.urlparse(url)
        # Preserve user custom endpoints (/mjpegfeed, /live, /h264, etc.). Only append /video if bare root URL.
        if (url.startswith("http://") or url.startswith("https://")) and (not parsed_p.path or parsed_p.path == "/"):
            url = url.rstrip("/") + "/video"
        super().__init__(camera_id, url)
        self.timeout_sec = timeout_sec
        self.cap = None
        self.http_stream = None
        self.http_bytes = b""
        self.use_direct_http = False
        self.last_reconnect_time = 0.0
        self.backoff_sec = 2.0
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connecting to {self.stream_url} (type: http_mjpeg)")
        self._connect()

    def _connect(self):
        now = time.time()
        if now - self.last_reconnect_time < self.backoff_sec:
            return

        self.last_reconnect_time = now
        self.reconnect_attempts += 1
        self.status = "CONNECTING"
        logger.info(f"[CAMERA RECONNECT] Camera {self.camera_id} connecting to HTTP MJPEG source: {self.stream_url} (attempt {self.reconnect_attempts})")

        # Attempt 1: Direct HTTP streaming multipart/x-mixed-replace reader (Fast & Native for phone IP webcams)
        try:
            req = urllib.request.Request(
                self.stream_url,
                headers={"User-Agent": "IBVAP-Surveillance-Engine/1.0"}
            )
            self.http_stream = urllib.request.urlopen(req, timeout=2.0)
            self.http_bytes = b""
            self.use_direct_http = True
            self.status = "ONLINE"
            self.backoff_sec = 2.0
            logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connected via Direct HTTP Stream to {self.stream_url}")
            return
        except Exception as http_err:
            logger.debug(f"[CAMERA CONNECT] Direct HTTP connect failed for {self.camera_id}: {http_err}. Trying OpenCV fallback.")
            if self.http_stream:
                try:
                    self.http_stream.close()
                except Exception:
                    pass
                self.http_stream = None

        # Attempt 2: Standard OpenCV VideoCapture fallback
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;1500000|stimeout;1500000|rw_timeout;1500000"
        try:
            self.cap = cv2.VideoCapture(self.stream_url)
            if self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    self.status = "ONLINE"
                    self.use_direct_http = False
                    self.backoff_sec = 2.0
                    self._track_fps_and_log(frame, "http_mjpeg")
                    logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connected via OpenCV to {self.stream_url} ({self.width}x{self.height})")
                    return
                else:
                    self.cap.release()
                    self.cap = None
        except Exception as e:
            logger.debug(f"[CAMERA CONNECT] OpenCV open error for {self.camera_id}: {e}")
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None

        self.status = "UNREACHABLE"
        self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)
        logger.warning(f"[CAMERA ERROR] Camera {self.camera_id} failed to connect to {self.stream_url}. Retrying in {self.backoff_sec:.1f}s")

    def _read_direct_http_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.http_stream:
            return False, None
        try:
            # Read until full JPEG (0xFF 0xD8 to 0xFF 0xD9) is accumulated or up to 16 chunks (128KB)
            for _ in range(16):
                a = self.http_bytes.find(b'\xff\xd8')
                b = self.http_bytes.find(b'\xff\xd9', a + 2) if a != -1 else -1
                if a != -1 and b != -1 and b > a:
                    jpg = self.http_bytes[a:b+2]
                    self.http_bytes = self.http_bytes[b+2:]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        # If backlog accumulated beyond 200KB, fast-forward to latest frame to eliminate streaming lag
                        if len(self.http_bytes) > 200000:
                            next_a = self.http_bytes.rfind(b'\xff\xd8')
                            if next_a != -1:
                                self.http_bytes = self.http_bytes[next_a:]
                        return True, frame

                chunk = self.http_stream.read(8192)
                if not chunk:
                    break
                self.http_bytes += chunk

                # Guard against unbounded buffer growth if stream emits corrupted data
                if len(self.http_bytes) > 500000:
                    last_start = self.http_bytes.rfind(b'\xff\xd8')
                    if last_start != -1:
                        self.http_bytes = self.http_bytes[last_start:]
                    else:
                        self.http_bytes = b""
        except Exception as e:
            logger.debug(f"[CAMERA DISCONNECT] Direct HTTP read exception on {self.camera_id}: {e}")
            if self.http_stream:
                try:
                    self.http_stream.close()
                except Exception:
                    pass
                self.http_stream = None
            self.http_bytes = b""
        return False, None

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        now = time.time()
        ret, frame = False, None

        if self.use_direct_http:
            ret, frame = self._read_direct_http_frame()
        elif self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
            except Exception as e:
                logger.debug(f"[CAMERA ERROR] OpenCV read error for {self.camera_id}: {e}")
                ret, frame = False, None

        if not ret or frame is None:
            if now - self.last_frame_time > self.timeout_sec:
                if self.status != "RECONNECTING" and self.status != "UNREACHABLE":
                    logger.warning(f"[CAMERA DISCONNECT] Camera {self.camera_id} stream lost / timed out ({self.timeout_sec}s without frames). Marking RECONNECTING.")
                    self.status = "RECONNECTING"
                self.release()
                self._connect()
            else:
                self.status = "DEGRADED"
                self.dropped_frames += 1
            return False, None

        self._track_fps_and_log(frame, "http_mjpeg")
        return True, frame

    def release(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self.http_stream:
            try:
                self.http_stream.close()
            except Exception:
                pass
            self.http_stream = None
        self.http_bytes = b""
        if self.status not in ["RECONNECTING", "UNREACHABLE"]:
            self.status = "OFFLINE"
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} HTTP MJPEG stream released.")


class RTSPVideoSource(VideoSource):
    """
    RTSP Video Ingestion Engine with automatic reconnect, exponential backoff,
    timeout handling, and frame drop monitoring.
    """
    def __init__(self, camera_id: str, rtsp_url: str, timeout_sec: int = 10):
        url = rtsp_url.strip()
        super().__init__(camera_id, url)
        self.timeout_sec = timeout_sec
        self.cap = None
        self.last_reconnect_time = 0.0
        self.backoff_sec = 2.0
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connecting to {self.stream_url} (type: rtsp)")
        self._connect()

    def _connect(self):
        now = time.time()
        if now - self.last_reconnect_time < self.backoff_sec:
            return

        self.last_reconnect_time = now
        self.reconnect_attempts += 1
        self.status = "CONNECTING"
        logger.info(f"[CAMERA RECONNECT] Camera {self.camera_id} attempting RTSP connection: {self.stream_url} (attempt {self.reconnect_attempts})")

        # OpenCV ffmpeg RTSP environment options: 2s timeout & TCP transport
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;2000000|rw_timeout;2000000"
        try:
            self.cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
            if self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    self.status = "ONLINE"
                    self.backoff_sec = 2.0
                    self._track_fps_and_log(frame, "rtsp")
                    logger.info(f"[CAMERA CONNECT] RTSP camera {self.camera_id} connected successfully ({self.width}x{self.height}).")
                    return
                else:
                    self.cap.release()
                    self.cap = None
            self.status = "UNREACHABLE"
            self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)
            logger.warning(f"[CAMERA ERROR] RTSP camera {self.camera_id} connection failed. Retrying in {self.backoff_sec:.1f}s")
        except Exception as e:
            self.status = "UNREACHABLE"
            self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)
            logger.error(f"[CAMERA ERROR] RTSP connection error for {self.camera_id}: {e}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        try:
            ret, frame = self.cap.read()
        except Exception as e:
            logger.error(f"[CAMERA ERROR] Error reading RTSP frame for {self.camera_id}: {e}")
            ret, frame = False, None

        now = time.time()

        if ret and frame is not None:
            self._track_fps_and_log(frame, "rtsp")
            return True, frame
        else:
            self.dropped_frames += 1
            if now - self.last_frame_time > self.timeout_sec:
                if self.status != "RECONNECTING" and self.status != "UNREACHABLE":
                    logger.error(f"[CAMERA DISCONNECT] RTSP stream timeout for {self.camera_id}. Marking RECONNECTING.")
                    self.status = "RECONNECTING"
                self.release()
                self._connect()
            else:
                self.status = "DEGRADED"

        return False, None

    def release(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self.status not in ["RECONNECTING", "UNREACHABLE"]:
            self.status = "OFFLINE"
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} RTSP stream released.")


class PushVideoSource(VideoSource):
    """
    Video ingestion engine that receives live frames pushed from client/browser webcam sessions
    (e.g. navigator.mediaDevices.getUserMedia pushing via POST /api/cameras/{id}/frame).
    Maintains an independent thread-safe buffer and real-time FPS computation.
    """
    def __init__(self, camera_id: str, stream_url: str = "push"):
        super().__init__(camera_id, stream_url)
        self.frame_queue = queue.Queue(maxsize=10)
        self.status = "CONNECTING"
        self.last_push_time = time.time()
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} initialized PushVideoSource for client stream.")

    def push_frame(self, frame: np.ndarray):
        now = time.time()
        self.last_push_time = now
        self.status = "ONLINE"
        if self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
        self.frame_queue.put(frame)

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        try:
            # Wait up to 100ms for incoming frame from client
            frame = self.frame_queue.get(timeout=0.1)
            self._track_fps_and_log(frame, "client_push")
            return True, frame
        except queue.Empty:
            now = time.time()
            if self._frame_count > 0 and now - self.last_push_time > 8.0:
                self.status = "DISCONNECTED"
                self.fps = 0.0
            elif self._frame_count > 0 and now - self.last_push_time > 3.0:
                self.status = "DEGRADED"
            elif self._frame_count == 0 and now - self.last_push_time > 15.0:
                self.status = "NO_FRAME_INPUT"
            return False, None

    def release(self):
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        self.status = "OFFLINE"
        self.fps = 0.0
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} push stream released.")


def create_video_source(camera_id: str, source_type: str, source_path: str) -> VideoSource:
    """
    Factory function to instantiate the correct VideoSource engine based on source path and type.
    """
    st = str(source_type).upper().strip()
    path = str(source_path).strip()
    if (path.startswith("'") and path.endswith("'")) or (path.startswith('"') and path.endswith('"')):
        path = path[1:-1].strip()

    if st == "MP4" or any(path.lower().endswith(ext) for ext in [".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm"]):
        return MP4VideoSource(camera_id, path)
    elif st in ["CLIENT", "BROWSER", "BROWSER_WEBCAM", "PUSH"] or path.startswith("browser:") or path.startswith("client:") or path.startswith("push:") or path == "push" or (st == "WEBCAM" and not path.isdigit()):
        return PushVideoSource(camera_id, path)
    elif st == "WEBCAM" or path.isdigit():
        dev_idx = int(path) if path.isdigit() else 0
        return WebcamVideoSource(camera_id, dev_idx)
    elif path.startswith("http://") or path.startswith("https://") or st in ["HTTP_MJPEG", "MJPEG", "HTTP"]:
        return HTTPMJPEGVideoSource(camera_id, path)
    elif path.startswith("rtsp://") or path.startswith("rtsps://") or st == "RTSP":
        return RTSPVideoSource(camera_id, path)
    else:
        return MP4VideoSource(camera_id, path)

