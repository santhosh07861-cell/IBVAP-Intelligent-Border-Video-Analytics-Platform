"""
IBVAP Real ANPR Engine
======================
Real-time license plate detection and recognition pipeline.

Pipeline per vehicle crop:
  1. Contour-based plate localization (Canny edge → rectangular contour → perspective warp)
  2. Preprocessing (CLAHE → bilateral denoise → adaptive threshold)
  3. EasyOCR text recognition (allowlist A-Z0-9)
  4. Output normalization (uppercase, strip noise chars)
  5. Indian plate format validation (pattern only, no character substitution)
  6. Multi-frame plate confirmation via ANPRPlateTracker (vote-based Counter)

OCR Engine: EasyOCR 1.7.x (lazy-loaded on first use, thread-safe via lock)
Plate Detection: OpenCV contour-based (no additional ONNX model required)

Key Rules:
- Never substitute ambiguous chars (O/0, I/1, B/8, S/5, Z/2) unless both
  format validation AND multi-frame evidence agree.
- Below OCR confidence threshold → return 'PLATE UNCERTAIN', never invent text.
- Inactive/low-quality crops → return None, never produce dummy results.
"""

import os
import re
import time
import uuid
import threading
import logging
from collections import Counter
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import cv2
import numpy as np

from backend.config import (
    ANPR_PLATE_CONFIDENCE_THRESHOLD,
    ANPR_OCR_CONFIDENCE_THRESHOLD,
    ANPR_CONFIRMATION_FRAMES,
    ANPR_TRACK_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ─── Indian License Plate Format Patterns ────────────────────────────────────
# Standard Indian plates: RJ19CB4821, DL01AB9999, MH02CD1234
# BH (Bharat) series: 22BH1234AB
_PLATE_STANDARD = re.compile(r'^[A-Z]{2}[0-9]{1,2}[A-Z]{2,3}[0-9]{4}$')
_PLATE_BH_SERIES = re.compile(r'^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$')

# Characters that OCR commonly confuses — used only to report, NOT to auto-substitute
_OCR_CONFUSION_PAIRS = {
    'O': '0', '0': 'O',
    'I': '1', '1': 'I',
    'B': '8', '8': 'B',
    'S': '5', '5': 'S',
    'Z': '2', '2': 'Z',
}

# Vehicle classes from YOLO model mapped to display labels
VEHICLE_TYPE_MAP = {
    "car": "CAR",
    "truck": "TRUCK",
    "bus": "BUS",
    "motorcycle": "MOTORCYCLE",
    "bicycle": "BICYCLE",
    "van": "VAN",
    "auto": "AUTO-RICKSHAW",
    "auto-rickshaw": "AUTO-RICKSHAW",
}

VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "van"}


class ANPRPlateTracker:
    """
    Per-vehicle-track plate state tracker.
    Uses a vote-based Counter to accumulate OCR results across frames.
    A plate is 'confirmed' when the top-voted text has >= ANPR_CONFIRMATION_FRAMES hits.
    Tracks are expired after ANPR_TRACK_TIMEOUT seconds without a new update.
    """

    def __init__(self):
        # {(camera_id, track_id): TrackState dict}
        self._tracks: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _expire_stale(self):
        """Remove track states that haven't been updated within ANPR_TRACK_TIMEOUT."""
        now = time.time()
        expired = [
            k for k, v in self._tracks.items()
            if now - v["last_seen"] > ANPR_TRACK_TIMEOUT
        ]
        for k in expired:
            del self._tracks[k]

    def update(self, camera_id: str, track_id: int, plate_text: str, ocr_conf: float) -> bool:
        """
        Record a new OCR result for (camera_id, track_id).
        Returns True if the track just reached confirmation threshold.
        """
        key = (camera_id, track_id)
        now = time.time()
        with self._lock:
            self._expire_stale()
            if key not in self._tracks:
                self._tracks[key] = {
                    "votes": Counter(),
                    "conf_sum": {},      # text -> sum of confidences for averaging
                    "conf_count": {},    # text -> number of readings
                    "confirmed": False,
                    "last_seen": now,
                }
            state = self._tracks[key]
            state["last_seen"] = now
            state["votes"][plate_text] += 1

            # Accumulate confidence for averaging later
            state["conf_sum"][plate_text] = state["conf_sum"].get(plate_text, 0.0) + ocr_conf
            state["conf_count"][plate_text] = state["conf_count"].get(plate_text, 0) + 1

            top_text, top_count = state["votes"].most_common(1)[0]
            if top_count >= ANPR_CONFIRMATION_FRAMES and not state["confirmed"]:
                state["confirmed"] = True
                return True  # Just confirmed now
        return False

    def is_confirmed(self, camera_id: str, track_id: int) -> bool:
        key = (camera_id, track_id)
        with self._lock:
            return self._tracks.get(key, {}).get("confirmed", False)

    def get_best_result(self, camera_id: str, track_id: int) -> Tuple[str, float, bool]:
        """
        Returns (plate_text, avg_ocr_confidence, is_valid_format).
        plate_text is 'PLATE UNCERTAIN' if no reading met ANPR_OCR_CONFIDENCE_THRESHOLD.
        """
        key = (camera_id, track_id)
        with self._lock:
            state = self._tracks.get(key)
            if not state or not state["votes"]:
                return "PLATE UNCERTAIN", 0.0, False

            top_text, _ = state["votes"].most_common(1)[0]
            avg_conf = (
                state["conf_sum"].get(top_text, 0.0) /
                max(1, state["conf_count"].get(top_text, 1))
            )
            is_valid = validate_indian_plate(top_text)
            return top_text, round(avg_conf, 3), is_valid

    def reset_confirmed(self, camera_id: str, track_id: int):
        """Reset confirmation state so a track can trigger again (after cooldown)."""
        key = (camera_id, track_id)
        with self._lock:
            if key in self._tracks:
                self._tracks[key]["confirmed"] = False
                self._tracks[key]["votes"] = Counter()
                self._tracks[key]["conf_sum"] = {}
                self._tracks[key]["conf_count"] = {}


# ─── Plate Format Validation ──────────────────────────────────────────────────

def validate_indian_plate(text: str) -> bool:
    """
    Returns True if `text` matches a known Indian license plate format.
    IMPORTANT: This function ONLY validates. It does NOT modify or correct the text.
    """
    if not text or text == "PLATE UNCERTAIN":
        return False
    cleaned = text.replace(" ", "").upper()
    return bool(_PLATE_STANDARD.match(cleaned) or _PLATE_BH_SERIES.match(cleaned))


def normalize_plate_text(raw_text: str) -> str:
    """
    Normalize raw OCR output to a clean plate string:
      - Uppercase
      - Remove spaces and hyphens (plate formatting)
      - Strip OCR noise: only keep A-Z and 0-9
      - DO NOT substitute ambiguous characters (O/0, I/1, etc.)
    Returns the cleaned string, or 'PLATE UNCERTAIN' if nothing useful remains.
    """
    if not raw_text:
        return "PLATE UNCERTAIN"
    # Keep only alphanumeric characters, uppercase
    cleaned = re.sub(r'[^A-Z0-9]', '', raw_text.upper())
    # Minimum 4 chars for any meaningful plate fragment
    if len(cleaned) < 4:
        return "PLATE UNCERTAIN"
    return cleaned


# ─── EasyOCR Lazy Loader ──────────────────────────────────────────────────────

class _EasyOCRLoader:
    """Thread-safe singleton EasyOCR reader with lazy initialization."""
    _instance = None
    _lock = threading.Lock()
    _loading = False
    _loaded = False

    @classmethod
    def get_reader(cls):
        if cls._loaded and cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._loaded and cls._instance is not None:
                return cls._instance
            if not cls._loading:
                cls._loading = True
                cls._do_load()
        return cls._instance

    @classmethod
    def _do_load(cls):
        try:
            import easyocr
            logger.info("[ANPR] Initializing EasyOCR reader (English)... (first-run may download models)")
            cls._instance = easyocr.Reader(
                ['en'],
                gpu=False,        # CPU-safe; set to True if CUDA available
                verbose=False,
                model_storage_directory=os.path.expanduser("~/.EasyOCR"),
                download_enabled=True,
            )
            cls._loaded = True
            logger.info("[ANPR] EasyOCR reader initialized successfully.")
        except Exception as e:
            logger.error(f"[ANPR] EasyOCR initialization failed: {e}")
            cls._instance = None
            cls._loaded = True  # Mark as tried to avoid repeated retries


# ─── Image Preprocessing ──────────────────────────────────────────────────────

def preprocess_plate_image(plate_img: np.ndarray) -> np.ndarray:
    """
    Preprocess a plate crop for best OCR accuracy:
      1. Ensure minimum height of 60px (resize up if too small)
      2. Convert to grayscale
      3. CLAHE contrast enhancement
      4. Bilateral filter denoising (preserves edges)
      5. Adaptive thresholding for binarization
    Returns the preprocessed image.
    """
    if plate_img is None or plate_img.size == 0:
        return plate_img

    h, w = plate_img.shape[:2]

    # 1. Resize: ensure at least 60px height (plates are often small in frame)
    min_h = 60
    if h < min_h:
        scale = min_h / h
        new_w = max(int(w * scale), 1)
        plate_img = cv2.resize(plate_img, (new_w, min_h), interpolation=cv2.INTER_CUBIC)
        h, w = plate_img.shape[:2]

    # 2. Grayscale
    if len(plate_img.shape) == 3:
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = plate_img.copy()

    # 3. CLAHE contrast enhancement (helps with uneven lighting, shadows)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 4. Bilateral filter (denoise while preserving character edges)
    denoised = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)

    # 5. Adaptive threshold (handles varying illumination across the plate)
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # Return as 3-channel for EasyOCR compatibility
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


# ─── Plate Localization ───────────────────────────────────────────────────────

def find_plate_region(vehicle_crop: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[List[float]]]:
    """
    Attempts to localize the license plate within a vehicle crop using:
      1. Canny edge detection on the lower 60% of the crop
      2. Contour-based rectangular region detection
      3. Perspective warp correction for angled plates

    Returns:
      (plate_img, plate_bbox_norm) where plate_bbox_norm is [x, y, w, h] normalized
      to vehicle crop dimensions, or (None, None) if no plate found.
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return None, None

    full_h, full_w = vehicle_crop.shape[:2]

    # License plates are mounted in the lower ~60% of a vehicle
    roi_y_start = int(full_h * 0.35)
    roi = vehicle_crop[roi_y_start:full_h, :]
    roi_h, roi_w = roi.shape[:2]

    if roi_h < 20 or roi_w < 40:
        return None, None

    # Edge detection
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 30, 150)

    # Morphological close to connect plate character edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None

    best_candidate = None
    best_area = 0.0

    for c in contours:
        area = cv2.contourArea(c)
        if area < 300:  # Too small to be a plate
            continue

        # Approximate to polygon
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)

        if len(approx) == 4:
            # 4-corner rectangle: strong plate candidate
            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / max(h, 1)
            # Indian plates: typically 2:1 to 5:1 aspect ratio
            if 1.5 <= aspect <= 6.0 and area > best_area:
                best_area = area
                best_candidate = (approx, x, y, w, h)
        else:
            # Non-4-corner contour: use bounding rect fallback
            x, y, w, h = cv2.boundingRect(c)
            aspect = w / max(h, 1)
            if 1.8 <= aspect <= 6.0 and area > best_area:
                best_area = area
                best_candidate = (None, x, y, w, h)

    if best_candidate is None:
        # No good plate candidate found → use lower-center region as fallback
        fallback_y = int(roi_h * 0.3)
        fallback_h = roi_h - fallback_y
        fallback_x = int(roi_w * 0.1)
        fallback_w = int(roi_w * 0.8)
        plate_crop = roi[fallback_y:roi_h, fallback_x:fallback_x + fallback_w]
        if plate_crop.size == 0:
            return None, None
        # Normalize bbox relative to full vehicle crop
        norm_x = fallback_x / full_w
        norm_y = (roi_y_start + fallback_y) / full_h
        norm_w = fallback_w / full_w
        norm_h = fallback_h / full_h
        return plate_crop, [round(norm_x, 3), round(norm_y, 3), round(norm_w, 3), round(norm_h, 3)]

    approx_pts, x, y, w, h = best_candidate

    # Perspective correction for 4-corner candidates
    if approx_pts is not None and len(approx_pts) == 4:
        pts = approx_pts.reshape(4, 2).astype(np.float32)
        # Sort corners: top-left, top-right, bottom-right, bottom-left
        rect = _order_corners(pts)
        max_w = int(max(
            np.linalg.norm(rect[0] - rect[1]),
            np.linalg.norm(rect[2] - rect[3])
        ))
        max_h = int(max(
            np.linalg.norm(rect[0] - rect[3]),
            np.linalg.norm(rect[1] - rect[2])
        ))
        if max_w < 20 or max_h < 5:
            plate_crop = roi[y:y + h, x:x + w]
        else:
            dst = np.array([[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(rect, dst)
            plate_crop = cv2.warpPerspective(roi, M, (max_w, max_h))
    else:
        plate_crop = roi[y:y + h, x:x + w]

    if plate_crop is None or plate_crop.size == 0:
        return None, None

    norm_x = x / full_w
    norm_y = (roi_y_start + y) / full_h
    norm_w = w / full_w
    norm_h = h / full_h
    return plate_crop, [round(norm_x, 3), round(norm_y, 3), round(norm_w, 3), round(norm_h, 3)]


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 corner points: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # Top-left: smallest sum
    rect[2] = pts[np.argmax(s)]   # Bottom-right: largest sum
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # Top-right: smallest diff
    rect[3] = pts[np.argmax(diff)]  # Bottom-left: largest diff
    return rect


# ─── OCR Runner ───────────────────────────────────────────────────────────────

def run_easyocr(plate_img: np.ndarray) -> Tuple[str, float]:
    """
    Run EasyOCR on a preprocessed plate image.
    Returns (normalized_text, mean_confidence).
    Returns ('PLATE UNCERTAIN', 0.0) on failure or low confidence.
    """
    reader = _EasyOCRLoader.get_reader()
    if reader is None:
        return "PLATE UNCERTAIN", 0.0

    try:
        # allowlist: only uppercase letters and digits — reject OCR hallucinations
        results = reader.readtext(
            plate_img,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            batch_size=1,
            detail=1,
        )

        if not results:
            return "PLATE UNCERTAIN", 0.0

        # Aggregate all detected text segments (handles multi-line plates)
        texts = []
        confidences = []
        for (_, text, conf) in results:
            if conf >= ANPR_OCR_CONFIDENCE_THRESHOLD:
                normalized = normalize_plate_text(text)
                if normalized != "PLATE UNCERTAIN":
                    texts.append(normalized)
                    confidences.append(conf)

        if not texts:
            return "PLATE UNCERTAIN", 0.0

        combined = "".join(texts)
        avg_conf = sum(confidences) / len(confidences)
        normalized = normalize_plate_text(combined)
        return normalized, round(avg_conf, 3)

    except Exception as e:
        logger.error(f"[ANPR OCR] EasyOCR error: {e}")
        return "PLATE UNCERTAIN", 0.0


# ─── Main ANPREngine ──────────────────────────────────────────────────────────

class ANPREngine:
    """
    Real ANPR processing engine.
    Called by the surveillance agent for each confirmed vehicle track.

    Usage:
        engine = ANPREngine()
        # In background thread (non-blocking for video pipeline):
        plate_crop, plate_bbox = find_plate_region(vehicle_crop)
        preprocessed = preprocess_plate_image(plate_crop)
        text, conf = run_easyocr(preprocessed)
        just_confirmed = engine.tracker.update(camera_id, track_id, text, conf)
        if just_confirmed:
            result = engine.tracker.get_best_result(camera_id, track_id)
    """

    def __init__(self):
        self.tracker = ANPRPlateTracker()
        # Trigger lazy EasyOCR load in background on engine creation
        threading.Thread(target=_EasyOCRLoader.get_reader, daemon=True).start()
        logger.info("[ANPR] ANPREngine initialized (EasyOCR loading in background)")

    def process_vehicle_crop(
        self,
        vehicle_crop: np.ndarray,
        camera_id: str,
        track_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Full ANPR pipeline on a single vehicle crop.
        Returns a dict with OCR result info if a useful reading was obtained,
        or None if the crop is unusable (too small, no plate found, etc.).

        Does NOT create DB records or fire WebSocket events — that is the
        responsibility of the AISurveillanceAgent.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        h, w = vehicle_crop.shape[:2]
        # Skip crops too small for reliable plate detection
        if h < 30 or w < 40:
            return None

        # Step 1: Locate plate region within vehicle crop
        plate_crop, plate_bbox_norm = find_plate_region(vehicle_crop)
        if plate_crop is None or plate_crop.size == 0:
            return None

        # Step 2: Preprocess for OCR
        processed = preprocess_plate_image(plate_crop)

        # Step 3: OCR
        ocr_text, ocr_conf = run_easyocr(processed)

        # Step 4: Update tracker → check for confirmation
        just_confirmed = self.tracker.update(camera_id, track_id, ocr_text, ocr_conf)

        return {
            "ocr_text": ocr_text,
            "ocr_confidence": ocr_conf,
            "plate_bbox_norm": plate_bbox_norm,
            "just_confirmed": just_confirmed,
            "is_valid_format": validate_indian_plate(ocr_text),
        }


# ─── Evidence Snapshot Generator ─────────────────────────────────────────────

def save_anpr_evidence_snapshot(
    frame: np.ndarray,
    vehicle_bbox: List[float],       # [x, y, w, h] normalized in full frame
    plate_bbox_in_vehicle: Optional[List[float]],  # [x, y, w, h] normalized in vehicle crop
    plate_text: str,
    vehicle_type: str,
    ocr_confidence: float,
    detection_confidence: float,
    camera_id: str,
    camera_name: str,
    camera_location: str,
    track_id: int,
    status: str = "CONFIRMED",
) -> Optional[Tuple[str, str, int]]:
    """
    Annotates a real camera frame with ANPR evidence overlays and saves it.

    Overlays:
    - Amber bounding box for vehicle + label
    - Green bounding box for plate region
    - Plate number label with OCR confidence
    - Top tactical banner (camera info, date/time)

    Returns (file_path, file_url, file_size) or None on failure.
    """
    if frame is None or frame.size == 0:
        logger.error("[ANPR EVIDENCE] Frame is empty — cannot save snapshot")
        return None

    annotated = frame.copy()
    fh, fw = annotated.shape[:2]
    now_dt = datetime.utcnow()
    now_str = now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')

    is_watchlist = "WATCHLIST" in status.upper()

    # ── Vehicle bounding box ──────────────────────────────────────────────────
    vx = int(vehicle_bbox[0] * fw)
    vy = int(vehicle_bbox[1] * fh)
    vw = int(vehicle_bbox[2] * fw)
    vh = int(vehicle_bbox[3] * fh)
    vx2 = min(fw - 1, vx + vw)
    vy2 = min(fh - 1, vy + vh)

    vehicle_color = (0, 30, 220) if is_watchlist else (30, 140, 255)  # Red for watchlist, amber otherwise
    cv2.rectangle(annotated, (vx, vy), (vx2, vy2), vehicle_color, 2)

    # Vehicle label
    v_label = f"T-{track_id} | {vehicle_type.upper()} | DET:{int(detection_confidence * 100)}%"
    (tw, th), _ = cv2.getTextSize(v_label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
    lbl_y = max(22, vy - 6)
    cv2.rectangle(annotated, (vx, lbl_y - th - 4), (vx + tw + 8, lbl_y + 2), vehicle_color, -1)
    cv2.putText(annotated, v_label, (vx + 4, lbl_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)

    # ── Plate bounding box (if detected within vehicle) ───────────────────────
    if plate_bbox_in_vehicle and len(plate_bbox_in_vehicle) == 4:
        # plate_bbox_in_vehicle is normalized to vehicle crop, convert to full frame
        px = int((vehicle_bbox[0] + plate_bbox_in_vehicle[0] * vehicle_bbox[2]) * fw)
        py = int((vehicle_bbox[1] + plate_bbox_in_vehicle[1] * vehicle_bbox[3]) * fh)
        pw = int(plate_bbox_in_vehicle[2] * vehicle_bbox[2] * fw)
        ph = int(plate_bbox_in_vehicle[3] * vehicle_bbox[3] * fh)
        px2 = min(fw - 1, px + pw)
        py2 = min(fh - 1, py + ph)

        plate_color = (0, 0, 220) if is_watchlist else (0, 220, 60)  # Red for watchlist, green otherwise
        cv2.rectangle(annotated, (px, py), (px2, py2), plate_color, 2)

        # Plate number label on plate box
        if plate_text != "PLATE UNCERTAIN":
            p_label = f"{plate_text} | OCR:{int(ocr_confidence * 100)}%"
        else:
            p_label = "PLATE UNCERTAIN"

        (ptw, pth), _ = cv2.getTextSize(p_label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        ply = min(fh - 4, py2 + 16)
        cv2.rectangle(annotated, (px, ply - pth - 3), (px + ptw + 8, ply + 3), plate_color, -1)
        cv2.putText(annotated, p_label, (px + 4, ply - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    # ── Top tactical banner ────────────────────────────────────────────────────
    banner_h = 42
    banner_color = (120, 0, 0) if is_watchlist else (15, 23, 42)
    cv2.rectangle(annotated, (0, 0), (fw, banner_h), banner_color, -1)
    cv2.line(annotated, (0, banner_h), (fw, banner_h), (255, 165, 0) if is_watchlist else (59, 130, 246), 1)

    if is_watchlist:
        banner_text = f"⚠ ANPR WATCHLIST ALERT | {camera_id} — {camera_name} | {camera_location} | {now_str}"
    else:
        banner_text = f"IBVAP ANPR | {camera_id} — {camera_name} | LOC: {camera_location} | {now_str}"

    cv2.putText(annotated, banner_text, (10, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (230, 230, 230), 1, cv2.LINE_AA)

    # Plate number prominent display in banner
    plate_display = f"PLATE: {plate_text}"
    cv2.putText(annotated, plate_display, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.58,
                (0, 100, 255) if is_watchlist else (0, 255, 160), 1, cv2.LINE_AA)

    # ── Save to disk ──────────────────────────────────────────────────────────
    save_dir = "storage/evidence/anpr/snapshots"
    os.makedirs(save_dir, exist_ok=True)

    clean_cam = camera_id.replace(" ", "_").replace("/", "_")
    clean_plate = re.sub(r'[^A-Z0-9]', '_', plate_text.upper())
    filename = (
        f"{clean_cam}_{vehicle_type.upper()}_{clean_plate}_"
        f"{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
    )
    file_path = os.path.join(save_dir, filename)

    success = cv2.imwrite(file_path, annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not success or not os.path.exists(file_path):
        logger.error(f"[ANPR EVIDENCE] Failed to write snapshot: {file_path}")
        return None

    file_size = os.path.getsize(file_path)
    file_url = f"/api/anpr/snapshots/{filename}"
    logger.info(f"[ANPR EVIDENCE] Snapshot saved: {file_path} ({round(file_size/1024, 1)} KB)")
    return file_path, file_url, file_size
