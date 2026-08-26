import os
import uuid
import logging
from datetime import datetime
from typing import List
import cv2
import numpy as np

from ai_engine.interfaces.detector import InferenceAdapter, DetectionBox

logger = logging.getLogger(__name__)

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
    "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop",
    "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]

class YOLODetector(InferenceAdapter):
    def __init__(self, model_path: str = "storage/models/yolov8n.onnx", conf_threshold: float = 0.45):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.net = None
        self.device = "CPU"
        self._init_model()

    def _init_model(self):
        if not os.path.exists(self.model_path):
            logger.warning(f"YOLO model file not found at {self.model_path}. Real inference will fall back to DNN/demo.")
            return

        try:
            self.net = cv2.dnn.readNetFromONNX(self.model_path)
            # Check CUDA availability
            if cv2.cuda.getCudaEnabledDeviceCount() > 0:
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                self.device = "CUDA / GPU"
            else:
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self.device = "CPU"
            logger.info(f"Loaded real YOLO model from {self.model_path} using {self.device}")
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            self.net = None

    def is_real_model(self) -> bool:
        return self.net is not None

    def detect(self, frame: np.ndarray, camera_id: str) -> List[DetectionBox]:
        if self.net is None or frame is None:
            return []

        height, width = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(frame, 1/255.0, (640, 640), swapRB=True, crop=False)
        self.net.setInput(blob)
        outputs = self.net.forward()

        detections = []
        # Parse YOLOv8 ONNX output format [1, 84, 8400]
        try:
            predictions = np.squeeze(outputs)
            if predictions.shape[0] == 84:
                predictions = predictions.T

            boxes, confidences, class_ids = [], [], []
            for pred in predictions:
                scores = pred[4:]
                class_id = np.argmax(scores)
                confidence = float(scores[class_id])
                if confidence > self.conf_threshold:
                    cx, cy, w, h = pred[0], pred[1], pred[2], pred[3]
                    x = (cx - w / 2) / 640.0
                    y = (cy - h / 2) / 640.0
                    nw = w / 640.0
                    nh = h / 640.0
                    boxes.append([max(0.0, x), max(0.0, y), min(1.0, nw), min(1.0, nh)])
                    confidences.append(confidence)
                    class_ids.append(int(class_id))

            for box, conf, cid in zip(boxes, confidences, class_ids):
                cname = COCO_CLASSES[cid] if cid < len(COCO_CLASSES) else "object"
                # Filter for border surveillance targets (person, car, truck, bus, motorcycle, bicycle)
                if cname in ["person", "car", "truck", "bus", "motorcycle", "bicycle", "van"]:
                    detections.append(DetectionBox(
                        detection_id=str(uuid.uuid4()),
                        camera_id=camera_id,
                        timestamp=datetime.utcnow(),
                        class_name=cname,
                        confidence=round(conf, 2),
                        bbox=box,
                        is_fallback=False
                    ))
        except Exception as e:
            logger.error(f"Error parsing YOLO inference: {e}")

        return detections
