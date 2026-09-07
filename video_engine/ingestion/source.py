import os
import time
import logging
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
        self.fps = 25.0
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
    Ingests pre-recorded MP4 video files with continuous looping for uninterrupted playback.
    """
    def __init__(self, camera_id: str, file_path: str):
        super().__init__(camera_id, file_path)
        self.cap = None
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connecting to {self.stream_url} (type: mp4)")
        self._connect()

    def _connect(self):
        self.status = "CONNECTING"
        self.cap = cv2.VideoCapture(self.stream_url)
        if self.cap.isOpened():
            self.status = "ONLINE"
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                self.fps = fps
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            logger.info(f"[CAMERA CONNECT] MP4 video file opened for {self.camera_id}: {self.stream_url} ({self.width}x{self.height} @ {self.fps} FPS)")
        else:
            self.status = "ERROR"
            logger.warning(f"[CAMERA ERROR] MP4VideoSource failed to open file for {self.camera_id}: {self.stream_url}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            # Loop MP4 video for continuous surveillance simulation
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()

        if ret and frame is not None:
            self._track_fps_and_log(frame, "mp4")
            return True, frame

        return False, None

    def release(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.status = "OFFLINE"
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} MP4 video source released.")


class WebcamVideoSource(VideoSource):
    """
    Ingests local USB or built-in FaceTime HD webcams via OpenCV / AVFoundation.
    """
    def __init__(self, camera_id: str, device_index: int = 0):
        super().__init__(camera_id, str(device_index))
        self.device_index = int(device_index) if str(device_index).isdigit() else 0
        self.cap = None
        self.reconnect_cooldown = 2.0
        self.last_reconnect_time = 0.0
        logger.info(f"[CAMERA CONNECT] Camera {self.camera_id} connecting to device index {self.device_index} (type: webcam)")
        self._connect()

    def _connect(self):
        now = time.time()
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
                        self._track_fps_and_log(frame, "webcam")
                        return
                self.status = "ONLINE"
            else:
                self.status = "ERROR"
                logger.warning(f"[CAMERA ERROR] Webcam device {self.device_index} for {self.camera_id} could not be opened.")
        except Exception as e:
            self.status = "ERROR"
            logger.error(f"[CAMERA ERROR] Error opening webcam device {self.device_index} for {self.camera_id}: {e}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            ret, frame = self.cap.read()

        if ret and frame is not None:
            self._track_fps_and_log(frame, "webcam")
            return True, frame
        else:
            self.dropped_frames += 1
            if self.dropped_frames > 20:
                logger.warning(f"[CAMERA DISCONNECT] Webcam {self.camera_id} dropped {self.dropped_frames} frames. Triggering reconnect.")
                self.release()
                self._connect()
            return False, None

    def release(self):
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
        if (url.startswith("http://") or url.startswith("https://")) and not any(url.endswith(x) for x in ["/video", "/videofeed", "/mjpegfeed", "/mjpeg", "/shot.jpg", ".mp4"]):
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

        # Set OpenCV FFmpeg environment options for fast failure
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;1500000|stimeout;1500000|rw_timeout;1500000"

        # Attempt 1: Standard OpenCV VideoCapture
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

        # Attempt 2: Direct HTTP streaming multipart/x-mixed-replace reader
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
        except Exception as e:
            self.status = "ERROR"
            self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)
            logger.warning(f"[CAMERA ERROR] Camera {self.camera_id} failed to connect to {self.stream_url}: {e}. Retrying in {self.backoff_sec:.1f}s")

    def _read_direct_http_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.http_stream:
            return False, None
        try:
            # Read chunks until a full JPEG (0xFF 0xD8 to 0xFF 0xD9) is accumulated
            for _ in range(8):
                chunk = self.http_stream.read(4096)
                if not chunk:
                    break
                self.http_bytes += chunk
                a = self.http_bytes.find(b'\xff\xd8')
                b = self.http_bytes.find(b'\xff\xd9')
                if a != -1 and b != -1 and b > a:
                    jpg = self.http_bytes[a:b+2]
                    self.http_bytes = self.http_bytes[b+2:]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
        except Exception as e:
            logger.debug(f"[CAMERA DISCONNECT] Direct HTTP read exception on {self.camera_id}: {e}")
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
                if self.status != "OFFLINE":
                    logger.warning(f"[CAMERA DISCONNECT] Camera {self.camera_id} stream lost / timed out ({self.timeout_sec}s without frames). Marking OFFLINE.")
                    self.status = "OFFLINE"
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
            self.status = "ERROR"
            self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)
            logger.warning(f"[CAMERA ERROR] RTSP camera {self.camera_id} connection failed. Retrying in {self.backoff_sec:.1f}s")
        except Exception as e:
            self.status = "ERROR"
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
                if self.status != "OFFLINE":
                    logger.error(f"[CAMERA DISCONNECT] RTSP stream timeout for {self.camera_id}. Marking OFFLINE.")
                    self.status = "OFFLINE"
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
        self.status = "OFFLINE"
        logger.info(f"[CAMERA DISCONNECT] Camera {self.camera_id} RTSP stream released.")


def create_video_source(camera_id: str, source_type: str, source_path: str) -> VideoSource:
    """
    Factory function to instantiate the correct VideoSource engine based on source path and type.
    """
    st = str(source_type).upper().strip()
    path = str(source_path).strip()

    if st == "WEBCAM" or path.isdigit():
        dev_idx = int(path) if path.isdigit() else 0
        return WebcamVideoSource(camera_id, dev_idx)
    elif path.startswith("http://") or path.startswith("https://") or st in ["HTTP_MJPEG", "MJPEG", "HTTP"]:
        return HTTPMJPEGVideoSource(camera_id, path)
    elif path.startswith("rtsp://") or path.startswith("rtsps://") or st == "RTSP":
        return RTSPVideoSource(camera_id, path)
    else:
        return MP4VideoSource(camera_id, path)
