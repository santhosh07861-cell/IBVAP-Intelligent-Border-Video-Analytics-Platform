from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
import pydantic

class DetectionBox(pydantic.BaseModel):
    detection_id: str
    camera_id: str
    timestamp: datetime
    class_id: int = 0
    class_name: str
    confidence: float
    bbox: List[float]  # [x, y, width, height] normalized (0.0 to 1.0)
    track_id: Optional[int] = None
    is_fallback: bool = False

class InferenceAdapter(ABC):
    @abstractmethod
    def detect(self, frame, camera_id: str) -> List[DetectionBox]:
        """
        Process a video frame and return normalized detections.
        frame: numpy ndarray (BGR image from OpenCV)
        camera_id: identifier of camera
        """
        pass

    @abstractmethod
    def is_real_model(self) -> bool:
        """Returns True if running actual trained model, False if fallback/demo mode."""
        pass
