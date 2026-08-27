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

    def save_annotated_snapshot(
        self, frame: np.ndarray, camera_id: str, bbox: list = None,
        label: str = "person", track_id: Any = None, confidence: float = 0.0,
        event_type: str = "NORMAL DETECTION",
        camera_name: str = "Border Surveillance Camera",
        camera_location: str = "Sector 4 Border Outpost"
    ) -> Optional[tuple]:
        if frame is None or frame.size == 0:
            print("[EVIDENCE ERROR] Frame is empty or None")
            return None

        annotated = frame.copy()
        h, w = annotated.shape[:2]

        now_dt = datetime.utcnow()
        clean_label = label.lower().strip()
        display_label = "TRUCK / LORRY" if clean_label in ["truck", "lorry"] else clean_label.upper()

        is_vehicle = clean_label in ["car", "truck", "lorry", "bus", "motorcycle", "bicycle"]
        prefix = "V" if is_vehicle else "P"
        track_str = f"{prefix}-{track_id}" if track_id else f"{prefix}-OBJ"

        if bbox and len(bbox) == 4:
            x1 = int(bbox[0] * w)
            y1 = int(bbox[1] * h)
            bw = int(bbox[2] * w)
            bh = int(bbox[3] * h)
            x2 = min(w - 1, x1 + bw)
            y2 = min(h - 1, y1 + bh)

            # Color styling based on event / object type
            if "INTRUSION" in event_type.upper() or "CROSSING" in event_type.upper() or "WATCHLIST" in event_type.upper():
                box_color = (0, 0, 255) # Red for critical security events
            elif "LOITERING" in event_type.upper() or "SUSPICIOUS" in event_type.upper():
                box_color = (0, 165, 255) # Orange/amber for high risk
            elif is_vehicle:
                box_color = (255, 140, 0) # Deep sky blue / amber for vehicles
            else:
                box_color = (255, 191, 0) # Cyan/blue for person detection

            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)

            # Label banner above box
            tag = f"{track_str} | {display_label} {int(confidence * 100)}%".strip()
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            cv2.rectangle(annotated, (x1, max(0, y1 - 24)), (x1 + tw + 10, y1), box_color, -1)
            cv2.putText(annotated, tag, (x1 + 5, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        # Top event & camera telemetry banner
        banner_h = 38
        cv2.rectangle(annotated, (0, 0), (w, banner_h), (15, 23, 42), -1)
        cv2.line(annotated, (0, banner_h), (w, banner_h), (59, 130, 246), 1)

        banner_text = (
            f"IBVAP AI EVIDENCE | {camera_id} - {camera_name} | LOC: {camera_location} | "
            f"{event_type.upper()} | {now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')}"
        )
        cv2.putText(annotated, banner_text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (226, 232, 240), 1, cv2.LINE_AA)

        # Organized Date-Structured Directory: storage/evidence/detections/YYYY/MM/DD/camera_id/
        year_str = now_dt.strftime("%Y")
        month_str = now_dt.strftime("%m")
        day_str = now_dt.strftime("%d")
        clean_cam = camera_id.replace(" ", "_").replace("/", "_")
        dir_path = os.path.join(self.storage_dir, "detections", year_str, month_str, day_str, clean_cam)
        os.makedirs(dir_path, exist_ok=True)

        clean_event = event_type.replace(" ", "_").upper()
        clean_name = clean_label.replace(" ", "_").upper()
        filename = f"{now_dt.strftime('%Y%m%d_%H%M%S')}_{clean_name}_{track_str}_{uuid.uuid4().hex[:4]}.jpg"
        full_path = os.path.join(dir_path, filename)

        success = cv2.imwrite(full_path, annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not success or not os.path.exists(full_path):
            print(f"[EVIDENCE ERROR] Failed to write evidence snapshot: {full_path}")
            return None

        file_size = os.path.getsize(full_path)
        file_url = f"/api/evidence/file/{year_str}/{month_str}/{day_str}/{clean_cam}/{filename}"
        return full_path, file_url, file_size

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
