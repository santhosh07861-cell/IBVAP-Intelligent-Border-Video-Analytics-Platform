import uuid
import time
import math
from datetime import datetime
from typing import List
import numpy as np

from ai_engine.interfaces.detector import InferenceAdapter, DetectionBox

class FallbackDetector(InferenceAdapter):
    """
    Simulates smooth, realistic detections across video frames.
    Moves test objects (persons and vehicles) along realistic trajectories
    so that Virtual Fencing, Intrusion, Loitering, ANPR, and Correlation are fully exercisable.
    """
    def __init__(self):
        self.start_time = time.time()

    def is_real_model(self) -> bool:
        return False

    def detect(self, frame: np.ndarray, camera_id: str) -> List[DetectionBox]:
        elapsed = time.time() - self.start_time
        detections = []
        now = datetime.utcnow()

        # Simulated Object 1: Person walking across restricted zone (track ID simulation handled by tracker)
        # Bounding box moves smoothly: x: 0.2 to 0.7, y: 0.3 to 0.65
        cycle_1 = (elapsed * 0.15) % (2 * math.pi)
        x1 = round(0.25 + 0.35 * (math.sin(cycle_1) + 1) / 2, 3)
        y1 = round(0.35 + 0.3 * (math.cos(cycle_1 * 0.7) + 1) / 2, 3)

        detections.append(DetectionBox(
            detection_id=str(uuid.uuid4()),
            camera_id=camera_id,
            timestamp=now,
            class_name="person",
            confidence=0.91,
            bbox=[x1, y1, 0.08, 0.22],
            is_fallback=True
        ))

        # Simulated Object 2: Patrol Vehicle moving along border perimeter
        cycle_2 = (elapsed * 0.08) % (2 * math.pi)
        x2 = round(0.60 + 0.25 * math.cos(cycle_2), 3)
        y2 = round(0.70 + 0.15 * math.sin(cycle_2), 3)

        detections.append(DetectionBox(
            detection_id=str(uuid.uuid4()),
            camera_id=camera_id,
            timestamp=now,
            class_name="car",
            confidence=0.88,
            bbox=[x2, y2, 0.18, 0.14],
            is_fallback=True
        ))

        # Periodic Object 3: Second Person appearing during loitering phase
        if int(elapsed) % 40 > 15:
            cycle_3 = (elapsed * 0.05) % (2 * math.pi)
            x3 = round(0.40 + 0.05 * math.sin(cycle_3), 3)
            y3 = round(0.50 + 0.05 * math.cos(cycle_3), 3)
            detections.append(DetectionBox(
                detection_id=str(uuid.uuid4()),
                camera_id=camera_id,
                timestamp=now,
                class_name="person",
                confidence=0.84,
                bbox=[x3, y3, 0.07, 0.20],
                is_fallback=True
            ))

        return detections
