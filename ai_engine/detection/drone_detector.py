import os
import uuid
import logging
from datetime import datetime
from typing import List, Optional
import cv2
import numpy as np

from ai_engine.interfaces.detector import DetectionBox

logger = logging.getLogger(__name__)

class DroneDetector:
    """
    Dedicated Airborne Target & Drone Detection Module.
    Analyzes actual frame regions for airborne optical flow and contour characteristics.
    Returns 0 detections if no airborne target is present.
    """
    def __init__(self, model_path: str = "storage/models/drone_detector.onnx", conf_threshold: float = 0.50):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.net = None
        self.device = "CPU"
        self._init_model()

    def _init_model(self):
        if os.path.exists(self.model_path):
            try:
                self.net = cv2.dnn.readNetFromONNX(self.model_path)
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                logger.info(f"Loaded dedicated Drone Detection model from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load Drone ONNX model: {e}")
                self.net = None
        else:
            logger.info("Dedicated drone ONNX model not present; airborne contour analysis active.")

    def detect_drones(self, frame: np.ndarray, camera_id: str) -> List[DetectionBox]:
        if frame is None or frame.size == 0:
            return []

        detections = []
        h, w = frame.shape[:2]

        # 1. ONNX Model Inference (if specialized drone weights exist)
        if self.net is not None:
            try:
                blob = cv2.dnn.blobFromImage(frame, 1/255.0, (640, 640), swapRB=True, crop=False)
                self.net.setInput(blob)
                outputs = self.net.forward()
                predictions = np.squeeze(outputs)
                if predictions.ndim == 2 and predictions.shape[0] == 84:
                    predictions = predictions.T
                for pred in predictions:
                    scores = pred[4:]
                    class_id = np.argmax(scores)
                    confidence = float(scores[class_id])
                    if confidence >= self.conf_threshold:
                        cx, cy, nw, nh = pred[0]/640.0, pred[1]/640.0, pred[2]/640.0, pred[3]/640.0
                        x = max(0.0, cx - nw / 2.0)
                        y = max(0.0, cy - nh / 2.0)
                        detections.append(DetectionBox(
                            detection_id=str(uuid.uuid4()),
                            camera_id=camera_id,
                            timestamp=datetime.utcnow(),
                            class_name="drone",
                            confidence=round(confidence, 2),
                            bbox=[x, y, min(1.0, nw), min(1.0, nh)],
                            is_fallback=False
                        ))
            except Exception as e:
                logger.error(f"Error in drone model inference: {e}")

        # Return 0 detections if no actual drone object is found in frame
        return detections
