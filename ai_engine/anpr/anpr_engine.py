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
_PLATE_STANDARD = re.compile(r'^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$')
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
    "train": "TRAIN",
    "airplane": "AIRPLANE",
    "boat": "BOAT",
}

VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "van", "auto", "auto-rickshaw", "train", "airplane", "boat"}


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
        plate_text is 'PLATE UNCERTAIN' if no reading met ANPR_OCR_CONFIDENCE_THRESHOLD,
        or if multi-frame readings conflict without reaching confirmation consensus.
        """
        key = (camera_id, track_id)
        with self._lock:
            state = self._tracks.get(key)
            if not state or not state["votes"]:
                return "PLATE UNCERTAIN", 0.0, False

            # Filter out unreadable / uncertain entries
            valid_votes = {
                t: c for t, c in state["votes"].items()
                if t and t not in ["PLATE UNCERTAIN", "UNKNOWN / UNREADABLE", "PLATE UNREADABLE"]
            }
            if not valid_votes:
                return "PLATE UNCERTAIN", 0.0, False

            # Order by vote count descending
            sorted_candidates = sorted(valid_votes.items(), key=lambda x: x[1], reverse=True)
            top_text, top_count = sorted_candidates[0]

            # If multiple conflicting plate readings exist:
            if len(sorted_candidates) > 1:
                second_text, second_count = sorted_candidates[1]
                # Tie or top candidate hasn't reached confirmation threshold with conflicting candidates
                if top_count == second_count or top_count < ANPR_CONFIRMATION_FRAMES:
                    # Do not randomly guess or pick one; keep as uncertain
                    return "PLATE UNCERTAIN", 0.0, False

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
    stripped = raw_text.strip().upper()
    if stripped in ["PLATE UNCERTAIN", "UNKNOWN / UNREADABLE", "PLATE UNREADABLE", "UNKNOWN"]:
        return "PLATE UNCERTAIN"
    # Keep only alphanumeric characters, uppercase
    cleaned = re.sub(r'[^A-Z0-9]', '', stripped)
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
    Preprocess a plate crop for optimal neural OCR accuracy:
      1. Ensure minimum height of 64px (clean character stroke resolution)
      2. Convert to grayscale
      3. CLAHE contrast enhancement (preserves natural gradient while normalizing illumination)
      4. Bilateral filter (denoise while keeping sharp character edges)
      5. Gentle unsharp masking (crispens character boundaries without destroying strokes)
      6. Return 3-channel RGB for EasyOCR (NO destructive binary thresholding)
    """
    if plate_img is None or plate_img.size == 0:
        return plate_img

    h, w = plate_img.shape[:2]

    # 1. Resize: ensure at least 64px height
    min_h = 64
    if h < min_h:
        scale = min_h / max(1, h)
        new_w = max(int(w * scale), 1)
        plate_img = cv2.resize(plate_img, (new_w, min_h), interpolation=cv2.INTER_CUBIC)
        h, w = plate_img.shape[:2]

    # 2. Grayscale
    if len(plate_img.shape) == 3:
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = plate_img.copy()

    # 3. CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 4. Bilateral filter (denoise while preserving sharp character edges)
    denoised = cv2.bilateralFilter(enhanced, d=7, sigmaColor=50, sigmaSpace=50)

    # 5. Gentle unsharp mask to crispen character boundaries
    gaussian = cv2.GaussianBlur(denoised, (0, 0), 2.0)
    sharpened = cv2.addWeighted(denoised, 1.25, gaussian, -0.25, 0)

    # Return as 3-channel BGR for EasyOCR compatibility
    return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)


# ─── Plate Localization ───────────────────────────────────────────────────────

def find_plate_region(vehicle_crop: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[List[float]]]:
    """
    Localizes the license plate region within a vehicle crop using:
      1. Deep text bounding box detection (CRAFT via EasyOCR) on the vehicle ROI
      2. Morphological Sobel-X character gradient and rectangular contour analysis
      3. Zero fake fallbacks: returns (None, None) if no genuine plate is detected.

    Returns:
      (plate_crop, plate_bbox_norm) where plate_bbox_norm is [x, y, w, h] normalized
      to the vehicle crop dimensions, or (None, None) if no plate is visible.
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return None, None

    full_h, full_w = vehicle_crop.shape[:2]
    if full_h < 30 or full_w < 40:
        return None, None

    # License plates are predominantly mounted in the lower ~65% of the vehicle
    roi_y_start = int(full_h * 0.35)
    roi = vehicle_crop[roi_y_start:full_h, :]
    roi_h, roi_w = roi.shape[:2]

    if roi_h < 20 or roi_w < 40:
        return None, None

    # ── Strategy 1: Deep Text Detection via EasyOCR CRAFT ─────────────────────
    try:
        reader = _EasyOCRLoader.get_reader()
        if reader is not None:
            horizontal_list, _ = reader.detect(roi)
            boxes = horizontal_list[0] if horizontal_list else []
            for box in boxes:
                x1, x2, y1, y2 = box
                bw = int(x2 - x1)
                bh = int(y2 - y1)
                if bw < 15 or bh < 8:
                    continue
                aspect = bw / max(1, bh)
                # Plate aspect ratio check (standard plates 2.0-6.5, two-tier 1.2-2.5)
                if 1.2 <= aspect <= 7.0 and (bw * bh) >= 120:
                    # Pad bounding box slightly to capture full plate border
                    pad_x = int(bw * 0.15)
                    pad_y = int(bh * 0.20)
                    px1 = max(0, int(x1) - pad_x)
                    py1 = max(0, int(y1) - pad_y)
                    px2 = min(roi_w, int(x2) + pad_x)
                    py2 = min(roi_h, int(y2) + pad_y)
                    plate_crop = roi[py1:py2, px1:px2]
                    if plate_crop.size > 0:
                        norm_x = round(px1 / full_w, 3)
                        norm_y = round((roi_y_start + py1) / full_h, 3)
                        norm_w = round((px2 - px1) / full_w, 3)
                        norm_h = round((py2 - py1) / full_h, 3)
                        return plate_crop, [norm_x, norm_y, norm_w, norm_h]
    except Exception as e:
        logger.debug(f"[ANPR] CRAFT localization error: {e}")

    # ── Strategy 2: Morphological Edge / Contour Localization ─────────────────
    try:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Vertical gradient (Sobel-X) highlights high-density plate characters
        grad_x = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        grad_x = cv2.convertScaleAbs(grad_x)
        # Morphological close with horizontal rectangle to connect character strokes
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
        closed = cv2.morphologyEx(grad_x, cv2.MORPH_CLOSE, kernel)
        _, thresh = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_candidate = None
        best_area = 0.0

        for c in contours:
            area = cv2.contourArea(c)
            if area < 250:
                continue
            x, y, w, h = cv2.boundingRect(c)
            aspect = w / max(h, 1)
            # Standard Indian plates: 1.8 to 6.0 aspect ratio
            if 1.8 <= aspect <= 6.0 and area > best_area:
                best_area = area
                best_candidate = (x, y, w, h)

        if best_candidate is not None:
            x, y, w, h = best_candidate
            plate_crop = roi[y:y + h, x:x + w]
            if plate_crop.size > 0:
                norm_x = round(x / full_w, 3)
                norm_y = round((roi_y_start + y) / full_h, 3)
                norm_w = round(w / full_w, 3)
                norm_h = round(h / full_h, 3)
                return plate_crop, [norm_x, norm_y, norm_w, norm_h]
    except Exception as e:
        logger.debug(f"[ANPR] Morphological localization error: {e}")

    # ── No visible plate found ────────────────────────────────────────────────
    # Strict rule: Never invent a fallback crop of the entire vehicle/bumper
    return None, None


# ─── OCR Runner ───────────────────────────────────────────────────────────────

def run_easyocr(plate_img: np.ndarray) -> Tuple[str, float]:
    """
    Run EasyOCR on a preprocessed plate image.
    Returns (normalized_text, mean_confidence).
    Returns ('PLATE UNCERTAIN', 0.0) on failure or low confidence.
    """
    reader = _EasyOCRLoader.get_reader()
    if reader is None or plate_img is None or plate_img.size == 0:
        return "PLATE UNCERTAIN", 0.0

    try:
        # allowlist: uppercase letters and digits — rejects spurious punctuation
        results = reader.readtext(
            plate_img,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            batch_size=1,
            detail=1,
        )

        if not results:
            return "PLATE UNCERTAIN", 0.0

        # Aggregate detected text segments across lines
        texts = []
        confidences = []
        for (_, text, conf) in results:
            cleaned = normalize_plate_text(text)
            if cleaned != "PLATE UNCERTAIN" and conf >= ANPR_OCR_CONFIDENCE_THRESHOLD:
                texts.append(cleaned)
                confidences.append(float(conf))

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
        if plate_text and plate_text not in ["PLATE UNCERTAIN", "UNKNOWN / UNREADABLE", "PLATE UNREADABLE"]:
            p_label = f"{plate_text} | OCR:{int(ocr_confidence * 100)}%"
        else:
            p_label = "PLATE UNREADABLE"

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
    if plate_text and plate_text not in ["PLATE UNCERTAIN", "UNKNOWN / UNREADABLE", "PLATE UNREADABLE"]:
        plate_display = f"PLATE: {plate_text} (OCR: {int(ocr_confidence * 100)}%)"
    else:
        plate_display = "PLATE: UNREADABLE"
    cv2.putText(annotated, plate_display, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.58,
                (0, 100, 255) if is_watchlist else (0, 255, 160), 1, cv2.LINE_AA)

    # ── Save to disk ──────────────────────────────────────────────────────────
    save_dir = "storage/evidence/anpr/snapshots"
    os.makedirs(save_dir, exist_ok=True)

    clean_cam = camera_id.replace(" ", "_").replace("/", "_")
    clean_plate = re.sub(r'[^A-Z0-9]', '_', (plate_text or 'UNREADABLE').upper())
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
