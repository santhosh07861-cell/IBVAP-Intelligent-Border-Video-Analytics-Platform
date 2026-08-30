"""
IBVAP Real AI Object Detector
==============================
Real-time deep learning object detection running on actual camera frame matrices.

Core Principles:
  1. Uses the real YOLOv8n ONNX deep neural network model for multi-class detection.
  2. Supports all verified COCO object classes (Person, Vehicles, Electronics, Furniture, etc.).
  3. Every detection outputs {class_id, class_name, confidence, bounding_box}.
  4. NEVER defaults to "PERSON" for arbitrary detections or unrecognized objects.
  5. NO simulated or fallback detectors. Empty scene = 0 detections.
  6. Implements Non-Maximum Suppression (NMS) to eliminate duplicate overlapping bounding boxes.
"""

import os
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import cv2
import numpy as np

from ai_engine.interfaces.detector import InferenceAdapter, DetectionBox
from ai_engine.detection.drone_detector import DroneDetector
from backend.config import DETECTION_CONFIDENCE_THRESHOLD, NMS_IOU_THRESHOLD

logger = logging.getLogger(__name__)

# Complete 80 COCO classes corresponding exactly to YOLOv8 output tensor indices [0..79]
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

# Primary categories
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "van", "airplane", "boat", "train"}
PERSON_CLASSES = {"person"}
DRONE_CLASSES = {"drone"}

# UI Display Label Mapping
CLASS_DISPLAY_NAMES: Dict[str, str] = {
    "person": "PERSON",
    "bicycle": "BICYCLE",
    "car": "CAR",
    "motorcycle": "MOTORCYCLE",
    "airplane": "AIRPLANE",
    "bus": "BUS",
    "train": "TRAIN",
    "truck": "TRUCK / LORRY",
    "boat": "BOAT",
    "drone": "DRONE",
    "laptop": "LAPTOP",
    "cell phone": "PHONE",
    "backpack": "BACKPACK",
    "handbag": "HANDBAG",
    "suitcase": "SUITCASE",
    "chair": "CHAIR",
    "couch": "COUCH",
    "bed": "BED",
    "dining table": "TABLE",
    "tv": "TV / MONITOR",
    "mouse": "MOUSE",
    "keyboard": "KEYBOARD",
    "bottle": "BOTTLE",
    "book": "BOOK",
    "clock": "CLOCK",
    "dog": "DOG",
    "cat": "CAT",
    "horse": "HORSE",
    "cow": "COW",
    "sheep": "SHEEP",
    "bird": "BIRD",
    "bench": "BENCH",
    "umbrella": "UMBRELLA",
    "traffic light": "TRAFFIC LIGHT",
    "stop sign": "STOP SIGN",
    "fire hydrant": "FIRE HYDRANT",
    "scissors": "SCISSORS",
    "teddy bear": "TEDDY BEAR",
    "potted plant": "PLANT",
    "sink": "SINK",
    "refrigerator": "REFRIGERATOR",
    "oven": "OVEN",
    "microwave": "MICROWAVE",
    "cup": "CUP",
    "unknown": "UNKNOWN OBJECT",
    "other": "OTHER OBJECT",
}


def get_display_label(class_name: str) -> str:
    """Returns human-friendly tactical display label for an object class."""
    if not class_name or class_name.lower().strip() == "unknown":
        return "UNKNOWN OBJECT"
    clean = class_name.lower().strip()
    if clean in CLASS_DISPLAY_NAMES:
        return CLASS_DISPLAY_NAMES[clean]
    if clean in ["truck", "lorry"]:
        return "TRUCK / LORRY"
    return clean.upper()


def get_track_prefix(class_name: str) -> str:
    """
    Returns the appropriate track prefix:
      'P' for Person (P-101)
      'V' for Vehicles (V-201)
      'D' for Drones (D-301)
      'O' for Other general objects / Unknown (O-401)
    """
    if not class_name:
        return "O"
    clean = class_name.lower().strip()
    if clean == "person":
        return "P"
    if clean in VEHICLE_CLASSES or clean in ["lorry", "van", "auto", "auto-rickshaw"]:
        return "V"
    if clean == "drone":
        return "D"
    return "O"


class RealAIDetector(InferenceAdapter):
    """
    Real Frame AI General Object Detector.
    Runs actual Deep Learning inference on video frame matrices.
    Returns ZERO detections when room/scene is empty. No fake or fallback objects.
    """
    def __init__(self, model_path: str = "storage/models/yolov8n.onnx", conf_threshold: float = DETECTION_CONFIDENCE_THRESHOLD):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.nms_iou_threshold = NMS_IOU_THRESHOLD
        self.net = None
        self.device = "CPU"
        self.drone_detector = DroneDetector()
        self._init_yolo_model()

    def _init_yolo_model(self):
        if os.path.exists(self.model_path):
            try:
                self.net = cv2.dnn.readNetFromONNX(self.model_path)
                if cv2.cuda.getCudaEnabledDeviceCount() > 0:
                    self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                    self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                    self.device = "CUDA / GPU"
                else:
                    self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                    self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                    self.device = "CPU"
                logger.info(f"Loaded real YOLOv8n ONNX model from {self.model_path} on {self.device}")
            except Exception as e:
                logger.error(f"Failed to load ONNX model: {e}")
                self.net = None

    def is_real_model(self) -> bool:
        return self.net is not None

    def detect(self, frame: np.ndarray, camera_id: str) -> List[DetectionBox]:
        if frame is None or frame.size == 0:
            return []

        height, width = frame.shape[:2]
        detections: List[DetectionBox] = []
        now = datetime.utcnow()

        # 1. Real YOLOv8 ONNX Model Inference
        if self.net is not None:
            try:
                blob = cv2.dnn.blobFromImage(frame, 1/255.0, (640, 640), swapRB=True, crop=False)
                self.net.setInput(blob)
                outputs = self.net.forward()

                predictions = np.squeeze(outputs)
                if predictions.ndim == 2 and predictions.shape[0] == 84:
                    predictions = predictions.T

                boxes, confidences, class_ids = [], [], []
                for pred in predictions:
                    scores = pred[4:]
                    class_id = int(np.argmax(scores))
                    confidence = float(scores[class_id])
                    if confidence >= self.conf_threshold:
                        cx, cy, w_box, h_box = pred[0], pred[1], pred[2], pred[3]
                        x = (cx - w_box / 2.0) / 640.0
                        y = (cy - h_box / 2.0) / 640.0
                        nw = w_box / 640.0
                        nh = h_box / 640.0
                        boxes.append([max(0.0, x), max(0.0, y), min(1.0, nw), min(1.0, nh)])
                        confidences.append(confidence)
                        class_ids.append(class_id)

                if boxes:
                    # Apply Non-Maximum Suppression (NMS) to eliminate duplicate overlapping boxes
                    pixel_boxes = [[int(b[0]*width), int(b[1]*height), int(b[2]*width), int(b[3]*height)] for b in boxes]
                    indices = cv2.dnn.NMSBoxes(pixel_boxes, confidences, self.conf_threshold, self.nms_iou_threshold)
                    if len(indices) > 0:
                        indices = indices.flatten() if hasattr(indices, 'flatten') else indices
                        for idx in indices:
                            box_raw = boxes[idx]
                            bx = max(0.0, min(1.0, float(box_raw[0])))
                            by = max(0.0, min(1.0, float(box_raw[1])))
                            bw = max(0.0, min(1.0 - bx, float(box_raw[2])))
                            bh = max(0.0, min(1.0 - by, float(box_raw[3])))
                            conf = float(confidences[idx])
                            cid = class_ids[idx]
                            cname = COCO_CLASSES[cid] if (0 <= cid < len(COCO_CLASSES)) else "unknown"
                            detections.append(DetectionBox(
                                detection_id=str(uuid.uuid4()),
                                camera_id=camera_id,
                                timestamp=now,
                                class_id=cid,
                                class_name=cname,
                                confidence=round(conf, 4),
                                bbox=[bx, by, bw, bh],
                                is_fallback=False
                            ))
            except Exception as e:
                logger.error(f"Error in YOLO inference: {e}")

        # 2. Dedicated Airborne Drone Detection
        drone_dets = self.drone_detector.detect_drones(frame, camera_id)
        if drone_dets:
            detections.extend(drone_dets)

        # Empty room / scene -> return 0 detections
        return detections
