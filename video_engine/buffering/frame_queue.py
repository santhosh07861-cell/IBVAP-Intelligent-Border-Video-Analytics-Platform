import queue
import threading
import time
import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

class FrameBuffer:
    def __init__(self, max_size: int = 30, target_fps: int = 15):
        self.queue = queue.Queue(maxsize=max_size)
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.last_sampled_time = 0.0

    def put_frame(self, frame: np.ndarray) -> bool:
        now = time.time()
        if now - self.last_sampled_time >= self.frame_interval:
            self.last_sampled_time = now
            if self.queue.full():
                try:
                    self.queue.get_nowait()  # Drop oldest frame if buffer is full
                except queue.Empty:
                    pass
            try:
                self.queue.put_nowait(frame)
                return True
            except queue.Full:
                return False
        return False

    def get_frame(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
