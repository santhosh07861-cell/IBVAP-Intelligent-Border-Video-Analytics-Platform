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

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if not ret:
            # Loop MP4 video for uninterrupted SIH demo continuous playback
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()

        if ret:
            self.last_frame_time = time.time()
            self.status = "ONLINE"

        return ret, frame

    def release(self):
        if self.cap:
            self.cap.release()
            self.status = "OFFLINE"

class WebcamVideoSource(VideoSource):
    def __init__(self, camera_id: str, device_index: int = 0):
        super().__init__(camera_id, str(device_index))
        self.device_index = int(device_index) if str(device_index).isdigit() else 0
        self.cap = None
        self._connect()

    def _connect(self):
        self.status = "CONNECTING"
        self.cap = cv2.VideoCapture(self.device_index)
        if self.cap.isOpened():
            self.status = "ONLINE"
        else:
            self.status = "OFFLINE"

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        if ret:
            self.last_frame_time = time.time()
            self.status = "ONLINE"
        else:
            self.dropped_frames += 1
            self.status = "DEGRADED"
        return ret, frame

    def release(self):
        if self.cap:
            self.cap.release()
            self.status = "OFFLINE"

class RTSPVideoSource(VideoSource):
    """
    Robust RTSP & HTTP IP Webcam Video Ingestion Engine with automatic reconnect, exponential backoff,
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

        # OpenCV ffmpeg RTSP environment options
        self.cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        if self.cap.isOpened():
            self.status = "ONLINE"
            self.backoff_sec = 2.0  # Reset backoff on success
            logger.info(f"RTSP camera {self.camera_id} connected successfully.")
        else:
            self.status = "ERROR"
            self.backoff_sec = min(self.backoff_sec * 1.2, 5.0)  # Max 5s reconnect delay
            logger.warning(f"RTSP camera {self.camera_id} connection failed. Retrying in {self.backoff_sec}s")

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            self._connect()
            if self.cap is None or not self.cap.isOpened():
                return False, None

        ret, frame = self.cap.read()
        now = time.time()

        if ret:
            self.last_frame_time = now
            self.status = "ONLINE"
        else:
            self.dropped_frames += 1
            # If no frame received within timeout, trigger reconnect
            if now - self.last_frame_time > self.timeout_sec:
                logger.error(f"RTSP stream timeout for {self.camera_id}. Triggering reconnect.")
                self.status = "OFFLINE"
                self.release()
                self._connect()
            else:
                self.status = "DEGRADED"

        return ret, frame

    def release(self):
        if self.cap:
            self.cap.release()
            self.status = "OFFLINE"
