import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class VideoSource(ABC):
    def __init__(self, camera_id: str, stream_url: str):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.status = "OFFLINE"
        self.fps = 25.0
        self.dropped_frames = 0
        self.reconnect_attempts = 0
        self.last_frame_time = time.time()

    @abstractmethod
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Reads and returns the next (success, frame) tuple."""
        pass

    @abstractmethod
    def release(self):
        """Releases video source resources."""
        pass


class MP4VideoSource(VideoSource):
    def __init__(self, camera_id: str, file_path: str):
        super().__init__(camera_id, file_path)
        self.cap = None
        self._connect()

    def _connect(self):
        self.status = "CONNECTING"
        self.cap = cv2.VideoCapture(self.stream_url)
        if self.cap.isOpened():
            self.status = "ONLINE"
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                self.fps = fps
        else:
            self.status = "ERROR"
            logger.warning(f"MP4VideoSource failed to open file for {self.camera_id}: {self.stream_url}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            # Loop MP4 video for uninterrupted continuous playback
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()

        if ret and frame is not None:
            self.last_frame_time = time.time()
            self.status = "ONLINE"
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


class WebcamVideoSource(VideoSource):
    def __init__(self, camera_id: str, device_index: int = 0):
        super().__init__(camera_id, str(device_index))
        self.device_index = int(device_index) if str(device_index).isdigit() else 0
        self.cap = None
        self.reconnect_cooldown = 2.0
        self.last_reconnect_time = 0.0
        self._connect()

    def _connect(self):
        now = time.time()
        if now - self.last_reconnect_time < self.reconnect_cooldown:
            return
        self.last_reconnect_time = now

        self.status = "CONNECTING"
        try:
            # Try default backend
            self.cap = cv2.VideoCapture(self.device_index)
            if not self.cap.isOpened():
                # Explicit AVFoundation backend for macOS
                self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_AVFOUNDATION)

            if self.cap.isOpened():
                # Warm up hardware sensor (read initial frames)
                for _ in range(3):
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        self.status = "ONLINE"
                        return
                self.status = "ONLINE"
            else:
                self.status = "ERROR"
                logger.warning(f"Webcam device {self.device_index} for {self.camera_id} could not be opened.")
        except Exception as e:
            self.status = "ERROR"
            logger.error(f"Error opening webcam device {self.device_index} for {self.camera_id}: {e}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            # Retry once for transient hardware read glitches
            time.sleep(0.01)
            ret, frame = self.cap.read()

        if ret and frame is not None:
            self.last_frame_time = time.time()
            self.status = "ONLINE"
            self.dropped_frames = 0
            return True, frame
        else:
            self.dropped_frames += 1
            if self.dropped_frames > 20:
                logger.warning(f"Webcam {self.camera_id} (device {self.device_index}) dropped {self.dropped_frames} frames. Triggering reconnect.")
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


class RTSPVideoSource(VideoSource):
    """
    RTSP & HTTP IP Webcam Video Ingestion Engine with automatic reconnect, exponential backoff,
    timeout handling, and frame drop monitoring.
    """
    def __init__(self, camera_id: str, rtsp_url: str, timeout_sec: int = 10):
        url = rtsp_url.strip()
        if (url.startswith("http://") or url.startswith("https://")) and not any(url.endswith(x) for x in ["/video", "/shot.jpg", ".mp4", "/mjpeg"]):
            url = url.rstrip("/") + "/video"
        super().__init__(camera_id, url)
        self.timeout_sec = timeout_sec
        self.cap = None
        self.last_reconnect_time = 0
        self.backoff_sec = 2.0
        self._connect()

    def _connect(self):
        now = time.time()
        if now - self.last_reconnect_time < self.backoff_sec:
            return

        self.last_reconnect_time = now
        self.reconnect_attempts += 1
        self.status = "CONNECTING"

        # OpenCV ffmpeg RTSP environment options: 2s timeout & TCP transport
        import os
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;2000000|rw_timeout;2000000"
        try:
            self.cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
            if self.cap.isOpened():
                self.status = "ONLINE"
                self.backoff_sec = 2.0  # Reset backoff on success
                logger.info(f"RTSP camera {self.camera_id} connected successfully.")
            else:
                self.status = "ERROR"
                self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)  # Max 10s reconnect delay
                logger.warning(f"RTSP camera {self.camera_id} connection failed. Retrying in {self.backoff_sec}s")
        except Exception as e:
            self.status = "ERROR"
            self.backoff_sec = min(self.backoff_sec * 1.5, 10.0)
            logger.error(f"RTSP connection error for {self.camera_id}: {e}")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        try:
            ret, frame = self.cap.read()
        except Exception as e:
            logger.error(f"Error reading RTSP frame for {self.camera_id}: {e}")
            ret, frame = False, None

        now = time.time()

        if ret and frame is not None:
            self.last_frame_time = now
            self.status = "ONLINE"
            return True, frame
        else:
            self.dropped_frames += 1
            if now - self.last_frame_time > self.timeout_sec:
                logger.error(f"RTSP stream timeout for {self.camera_id}. Triggering reconnect.")
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
