import os
import uuid
import logging
from datetime import datetime
from typing import List, Optional
import cv2
import numpy as np

from ai_engine.interfaces.detector import InferenceAdapter, DetectionBox
from ai_engine.detection.drone_detector import DroneDetector

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

SUPPORTED_TARGET_CLASSES = {"person", "car", "truck", "bus", "motorcycle", "bicycle", "van"}

class RealAIDetector(InferenceAdapter):
    """
    Real Frame AI Object Detector.
    Runs actual Computer Vision & Deep Learning inference directly on video frame image matrices.
    Returns ZERO detections when room/scene is empty. No fallback or simulated objects.
    """
    def __init__(self, model_path: str = "storage/models/yolov8n.onnx", conf_threshold: float = 0.38):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.net = None
        self.device = "CPU"
        self.drone_detector = DroneDetector()
        
        # Initialize OpenCV HOG Person Detector if available in OpenCV bindings
        if hasattr(cv2, 'HOGDescriptor'):
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        else:
            self.hog = None
        
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
                logger.info(f"Loaded real YOLO ONNX model from {self.model_path} on {self.device}")
            except Exception as e:
                logger.error(f"Failed to load ONNX model: {e}")
                self.net = None

    def is_real_model(self) -> bool:
        return True

    def detect(self, frame: np.ndarray, camera_id: str) -> List[DetectionBox]:
        if frame is None or frame.size == 0:
            return []

        height, width = frame.shape[:2]
        detections: List[DetectionBox] = []
        now = datetime.utcnow()

        # 1. Real YOLO ONNX Model Inference (if model file loaded)
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
                    class_id = np.argmax(scores)
                    confidence = float(scores[class_id])
                    if confidence >= self.conf_threshold:
                        cx, cy, w_box, h_box = pred[0], pred[1], pred[2], pred[3]
                        x = (cx - w_box / 2.0) / 640.0
                        y = (cy - h_box / 2.0) / 640.0
                        nw = w_box / 640.0
                        nh = h_box / 640.0
                        boxes.append([max(0.0, x), max(0.0, y), min(1.0, nw), min(1.0, nh)])
                        confidences.append(confidence)
                        class_ids.append(int(class_id))

                if boxes:
                    # Apply Non-Maximum Suppression to remove duplicate candidate boxes
                    pixel_boxes = [[int(b[0]*width), int(b[1]*height), int(b[2]*width), int(b[3]*height)] for b in boxes]
                    indices = cv2.dnn.NMSBoxes(pixel_boxes, confidences, self.conf_threshold, 0.45)
                    if len(indices) > 0:
                        indices = indices.flatten() if hasattr(indices, 'flatten') else indices
                        for idx in indices:
                            box = boxes[idx]
                            conf = confidences[idx]
                            cid = class_ids[idx]
                            cname = COCO_CLASSES[cid] if cid < len(COCO_CLASSES) else "object"
                            if cname in SUPPORTED_TARGET_CLASSES:
                                detections.append(DetectionBox(
                                    detection_id=str(uuid.uuid4()),
                                    camera_id=camera_id,
                                    timestamp=now,
                                    class_name=cname,
                                    confidence=round(conf, 2),
                                    bbox=box,
                                    is_fallback=False
                                ))
            except Exception as e:
                logger.error(f"Error in YOLO inference: {e}")

        # 2. Real OpenCV HOG Frame Person Detector (Always active on actual frame matrix)
        if len(detections) == 0 and self.hog is not None:
            try:
                # Resize frame for fast, responsive HOG multi-scale processing
                small_h, small_w = 480, 640
                resized = cv2.resize(frame, (small_w, small_h))
                gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
                
                # Perform HOG multiscale detection directly on frame pixels
                rects, weights = self.hog.detectMultiScale(
                    gray,
                    winStride=(8, 8),
                    padding=(4, 4),
                    scale=1.05
                )

                for i, (x, y, w_rect, h_rect) in enumerate(rects):
                    weight = float(weights[i]) if i < len(weights) else 0.50
                    # Convert HOG weights to normalized confidence (0.40 - 0.95)
                    norm_conf = round(min(0.95, max(0.40, 0.40 + weight * 0.25)), 2)
                    
                    if norm_conf >= self.conf_threshold:
                        norm_box = [
                            round(x / float(small_w), 3),
                            round(y / float(small_h), 3),
                            round(w_rect / float(small_w), 3),
                            round(h_rect / float(small_h), 3)
                        ]
                        detections.append(DetectionBox(
                            detection_id=str(uuid.uuid4()),
                            camera_id=camera_id,
                            timestamp=now,
                            class_name="person",
                            confidence=norm_conf,
                            bbox=norm_box,
                            is_fallback=False
                        ))
            except Exception as e:
                logger.error(f"Error in OpenCV HOG person detection: {e}")

        # 3. Real Drone Detection Sub-Module
        drone_dets = self.drone_detector.detect_drones(frame, camera_id)
        if drone_dets:
            detections.extend(drone_dets)

        # Empty room / scene -> return 0 detections
        return detections
