import os
import uuid
import cv2
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any

class EvidenceManager:
    def __init__(self, storage_dir: str = "storage/evidence"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "crops"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "clips"), exist_ok=True)

    def save_snapshot(self, frame: np.ndarray, camera_id: str) -> Optional[str]:
        if frame is None or frame.size == 0:
            return None
        filename = f"snapshot_{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
        full_path = os.path.join(self.storage_dir, "snapshots", filename)
        cv2.imwrite(full_path, frame)
        return full_path

    def save_object_crop(self, frame: np.ndarray, bbox: list, camera_id: str, label: str = "object") -> Optional[str]:
        if frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        x1 = int(bbox[0] * w)
        y1 = int(bbox[1] * h)
        bw = int(bbox[2] * w)
        bh = int(bbox[3] * h)

        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(x1 + 1, min(w, x1 + bw))
        y2 = max(y1 + 1, min(h, y1 + bh))

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        filename = f"crop_{label}_{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
        full_path = os.path.join(self.storage_dir, "crops", filename)
        cv2.imwrite(full_path, crop)
        return full_path
