"""
IBVAP Evidence Manager
======================
Saves annotated high-resolution evidence snapshots and crops for confirmed AI detections,
security alerts, and incident investigations.
"""

import os
import uuid
import re
import cv2
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, List

from ai_engine.detection.real_ai_detector import get_display_label, get_track_prefix, VEHICLE_CLASSES, PERSON_CLASSES

class EvidenceManager:
    def __init__(self, storage_dir: str = "storage/evidence"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "crops"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "clips"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "detections"), exist_ok=True)

    def save_snapshot(self, frame: np.ndarray, camera_id: str) -> Optional[str]:
        if frame is None or frame.size == 0:
            return None
        filename = f"snapshot_{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
        full_path = os.path.join(self.storage_dir, "snapshots", filename)
        cv2.imwrite(full_path, frame)
        return full_path

    def save_annotated_snapshot(
        self, frame: np.ndarray, camera_id: str, bbox: list = None,
        label: str = "object", track_id: Any = None, confidence: float = 0.0,
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
        clean_label = (label or "object").lower().strip()
        display_label = get_display_label(clean_label)
        prefix = get_track_prefix(clean_label)
        track_str = f"{prefix}-{track_id}" if track_id is not None else f"{prefix}-OBJ"

        if bbox and len(bbox) == 4:
            x1 = max(0, int(bbox[0] * w))
            y1 = max(0, int(bbox[1] * h))
            bw = max(1, int(bbox[2] * w))
            bh = max(1, int(bbox[3] * h))
            x2 = min(w - 1, x1 + bw)
            y2 = min(h - 1, y1 + bh)

            # Color styling based on object class and event severity
            if "INTRUSION" in event_type.upper() or "CROSSING" in event_type.upper() or "WATCHLIST" in event_type.upper():
                box_color = (0, 0, 255)       # Red for critical security events
            elif "LOITERING" in event_type.upper() or "SUSPICIOUS" in event_type.upper():
                box_color = (0, 165, 255)     # Orange/amber for high risk
            elif clean_label == "person":
                box_color = (255, 191, 0)     # Cyan/blue for person
            elif clean_label in VEHICLE_CLASSES:
                box_color = (255, 140, 0)     # Sky blue / amber for vehicles
            elif clean_label == "drone":
                box_color = (255, 0, 200)     # Magenta for airborne targets
            else:
                box_color = (100, 220, 150)   # Emerald for general objects (laptops, phones, etc.)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)

            # Label banner above box
            conf_pct = f"{int(confidence * 100)}%" if confidence > 0 else ""
            tag = f"{track_str} | {display_label} {conf_pct}".strip()
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
            cv2.rectangle(annotated, (x1, max(0, y1 - 24)), (x1 + tw + 10, y1), box_color, -1)
            cv2.putText(annotated, tag, (x1 + 5, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (15, 23, 42), 2)
            cv2.putText(annotated, tag, (x1 + 5, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)

        # Top event & camera telemetry banner
        banner_h = 38
        cv2.rectangle(annotated, (0, 0), (w, banner_h), (15, 23, 42), -1)
        cv2.line(annotated, (0, banner_h), (w, banner_h), (59, 130, 246), 1)

        banner_text = (
            f"IBVAP AI EVIDENCE | {camera_id} - {camera_name} | LOC: {camera_location} | "
            f"{event_type.upper()} | {now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')}"
        )
        cv2.putText(annotated, banner_text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (226, 232, 240), 1, cv2.LINE_AA)

        # Organized Date-Structured Directory: storage/evidence/detections/YYYY/MM/DD/camera_id/
        year_str = now_dt.strftime("%Y")
        month_str = now_dt.strftime("%m")
        day_str = now_dt.strftime("%d")
        clean_cam = re.sub(r'[^A-Za-z0-9_-]', '_', camera_id)
        dir_path = os.path.join(self.storage_dir, "detections", year_str, month_str, day_str, clean_cam)
        os.makedirs(dir_path, exist_ok=True)

        clean_name = re.sub(r'[^A-Za-z0-9_-]', '_', clean_label.upper())
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

    def save_evidence_sequence(
        self,
        event_frame: np.ndarray,
        camera_id: str,
        bbox: list = None,
        label: str = "object",
        track_id: Any = None,
        confidence: float = 0.0,
        event_type: str = "SECURITY EVENT",
        camera_name: str = "Border Camera",
        camera_location: str = "Sector 4",
        pre_frame: Optional[np.ndarray] = None,
        post_frame: Optional[np.ndarray] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Saves a high-reliability evidence sequence (pre-event, event, and post-event frames).
        Returns a dictionary containing the primary snapshot metadata and sequence URLs.
        """
        primary = self.save_annotated_snapshot(
            frame=event_frame,
            camera_id=camera_id,
            bbox=bbox,
            label=label,
            track_id=track_id,
            confidence=confidence,
            event_type=event_type,
            camera_name=camera_name,
            camera_location=camera_location
        )
        if not primary:
            return None

        file_path, file_url, file_size = primary
        sequence_urls = [file_url]

        # Save pre-event frame if available
        if pre_frame is not None and pre_frame.size > 0:
            pre_res = self.save_annotated_snapshot(
                frame=pre_frame,
                camera_id=camera_id,
                bbox=None,
                label=label,
                track_id=track_id,
                confidence=confidence,
                event_type=f"PRE-EVENT {event_type}",
                camera_name=camera_name,
                camera_location=camera_location
            )
            if pre_res:
                sequence_urls.insert(0, pre_res[1])

        # Save post-event frame if available
        if post_frame is not None and post_frame.size > 0:
            post_res = self.save_annotated_snapshot(
                frame=post_frame,
                camera_id=camera_id,
                bbox=None,
                label=label,
                track_id=track_id,
                confidence=confidence,
                event_type=f"POST-EVENT {event_type}",
                camera_name=camera_name,
                camera_location=camera_location
            )
            if post_res:
                sequence_urls.append(post_res[1])

        return {
            "file_path": file_path,
            "file_url": file_url,
            "file_size": file_size,
            "sequence_urls": sequence_urls
        }

    def cleanup_expired_evidence(self, max_age_days: int = 30, max_storage_gb: float = 20.0, protected_urls: set = None) -> int:
        """
        Rolling storage system with automatic retention and disk-space protection.
        Safeguards all evidence files referenced by active/unresolved incidents.
        """
        protected = protected_urls or set()
        deleted_count = 0
        now_ts = datetime.utcnow().timestamp()
        max_age_sec = max_age_days * 86400

        total_bytes = 0
        file_entries = []

        for root, _, files in os.walk(self.storage_dir):
            for f in files:
                if not f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                    continue
                full_path = os.path.join(root, f)
                try:
                    stat = os.stat(full_path)
                    total_bytes += stat.st_size
                    file_entries.append((full_path, stat.st_mtime, stat.st_size))
                except OSError:
                    continue

        max_allowed_bytes = max_storage_gb * 1024 * 1024 * 1024

        # Sort files by modification time (oldest first)
        file_entries.sort(key=lambda x: x[1])

        for path, mtime, size in file_entries:
            # Check if file is protected
            is_protected = False
            for p_url in protected:
                if p_url and os.path.basename(path) in p_url:
                    is_protected = True
                    break

            if is_protected:
                continue

            age_sec = now_ts - mtime
            # Delete if older than retention limit or storage limit exceeded
            if age_sec > max_age_sec or total_bytes > max_allowed_bytes:
                try:
                    os.remove(path)
                    total_bytes -= size
                    deleted_count += 1
                except OSError:
                    pass

        return deleted_count

