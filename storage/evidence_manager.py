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
        event_type: str = "DETECTION"
    ) -> Optional[tuple]:
        if frame is None or frame.size == 0:
            print("[EVIDENCE ERROR] Frame is empty or None")
            return None

        annotated = frame.copy()
        h, w = annotated.shape[:2]

        print(f"[EVIDENCE] Frame received: {w}x{h}")

        if bbox and len(bbox) == 4:
            x1 = int(bbox[0] * w)
            y1 = int(bbox[1] * h)
            bw = int(bbox[2] * w)
            bh = int(bbox[3] * h)
            x2 = min(w - 1, x1 + bw)
            y2 = min(h - 1, y1 + bh)

            # Red/amber bounding box
            box_color = (0, 0, 255) if event_type != "DETECTION" else (255, 165, 0)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)

            # Label box
            track_str = f"P-{track_id}" if track_id else "OBJ"
            tag = f"{track_str} | {label.upper()} {int(confidence * 100)}%".strip()
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(annotated, (x1, max(0, y1 - 25)), (x1 + tw + 10, y1), box_color, -1)
            cv2.putText(annotated, tag, (x1 + 5, max(15, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Top event banner
        now_dt = datetime.utcnow()
        banner_text = f"IBVAP EVIDENCE | {camera_id} | {event_type} | {now_dt.strftime('%d-%m-%Y %H:%M:%S UTC')}"
        cv2.rectangle(annotated, (0, 0), (w, 35), (15, 23, 42), -1)
        cv2.putText(annotated, banner_text, (15, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (59, 130, 246), 2)

        clean_event = event_type.replace(" ", "_").upper()
        clean_track = f"P-{track_id}" if track_id else "OBJ"
        clean_label = label.replace(" ", "_").upper()

        if event_type == "DETECTION":
            filename = f"{camera_id}_{clean_track}_{clean_label}_{now_dt.strftime('%Y-%m-%d_%H%M%S')}.jpg"
        else:
            filename = f"{camera_id}_{clean_track}_{clean_event}_{now_dt.strftime('%Y-%m-%d_%H%M%S')}.jpg"

        full_path = os.path.join(self.storage_dir, "snapshots", filename)
        print(f"[EVIDENCE] Saving: {full_path}")

        success = cv2.imwrite(full_path, annotated)
        if not success:
            print(f"[EVIDENCE ERROR] cv2.imwrite failed to write file: {full_path}")
            return None

        # Verify file existence & non-zero file size
        if not os.path.exists(full_path):
            print(f"[EVIDENCE ERROR] Written file does not exist: {full_path}")
            return None

        file_size = os.path.getsize(full_path)
        if file_size == 0:
            print(f"[EVIDENCE ERROR] Written file is 0 bytes: {full_path}")
            return None

        file_size_kb = round(file_size / 1024, 1)
        print(f"[EVIDENCE] File written successfully ({file_size_kb} KB): {full_path}")

        file_url = f"/static/evidence/{filename}"
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
