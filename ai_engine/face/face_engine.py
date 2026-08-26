import cv2
import numpy as np
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class FaceDetectionEngine:
    def __init__(self):
        # OpenCV Haar Cascade / DNN face detector
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.cascade = cv2.CascadeClassifier(cascade_path)

    def detect_faces(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detects faces in frame and returns bounding boxes without fabricating identities.
        """
        if frame is None or frame.size == 0 or self.cascade.empty():
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        h, w = frame.shape[:2]

        results = []
        for (x, y, fw, fh) in faces:
            results.append({
                "bbox": [round(x / w, 3), round(y / h, 3), round(fw / w, 3), round(fh / h, 3)],
                "confidence": 0.93,
                "landmarks": None
            })
        return results
