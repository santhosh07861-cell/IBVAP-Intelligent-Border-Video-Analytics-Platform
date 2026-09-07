import os

class Settings:
    JWT_SECRET: str = os.getenv("JWT_SECRET", "ibvap_super_secret_jwt_key_2026_sih_border_surveillance")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

settings = Settings()

# Real-time AI Object Detection & Confirmation Configuration
DETECTION_CONFIDENCE_THRESHOLD = float(os.getenv("DETECTION_CONFIDENCE_THRESHOLD", "0.20"))
NMS_IOU_THRESHOLD = float(os.getenv("NMS_IOU_THRESHOLD", "0.45"))

# Multi-Object Tracker Confirmation Pipeline
TRACK_CONFIRMATION_FRAMES = int(os.getenv("TRACK_CONFIRMATION_FRAMES", "2"))
TRACK_MAX_DISAPPEARED = int(os.getenv("TRACK_MAX_DISAPPEARED", "20"))

# Evidence Capture & Throttling Configuration
EVIDENCE_CAPTURE_INTERVAL_SEC = float(os.getenv("EVIDENCE_CAPTURE_INTERVAL_SEC", "15.0"))

# Event & Behavior Rule Evaluation & Cooldowns
LOITERING_THRESHOLD_SEC = float(os.getenv("LOITERING_THRESHOLD_SEC", "10.0"))
ALERT_COOLDOWN_SEC = float(os.getenv("ALERT_COOLDOWN_SEC", "30.0"))
ZONE_INTRUSION_COOLDOWN_SEC = float(os.getenv("ZONE_INTRUSION_COOLDOWN_SEC", "30.0"))
ZONE_LOITERING_COOLDOWN_SEC = float(os.getenv("ZONE_LOITERING_COOLDOWN_SEC", "60.0"))
ZONE_EXIT_DEBOUNCE_FRAMES = int(os.getenv("ZONE_EXIT_DEBOUNCE_FRAMES", "10"))
FACE_RECORD_COOLDOWN_SEC = float(os.getenv("FACE_RECORD_COOLDOWN_SEC", "60.0"))


# ─── ANPR (Automatic Number Plate Recognition) Configuration ─────────────────
# ANPR_PLATE_CONFIDENCE_THRESHOLD:
#   Minimum score from the contour-based plate candidate detector to attempt OCR.
#   Set low (0.35) because we prefer false-positives (attempted OCR on a non-plate)
#   over false-negatives (skipping a real plate). Multi-frame confirmation filters noise.
ANPR_PLATE_CONFIDENCE_THRESHOLD = float(os.getenv("ANPR_PLATE_CONFIDENCE_THRESHOLD", "0.35"))

# ANPR_OCR_CONFIDENCE_THRESHOLD:
#   Minimum EasyOCR character confidence (0-1) to accept a reading.
#   Below this threshold the result is marked UNCERTAIN rather than accepted.
#   0.60 is the EasyOCR "reasonable confidence" boundary for license plate text.
ANPR_OCR_CONFIDENCE_THRESHOLD = float(os.getenv("ANPR_OCR_CONFIDENCE_THRESHOLD", "0.60"))

# ANPR_CONFIRMATION_FRAMES:
#   Number of consecutive video frames in which the SAME plate text must appear
#   before the result is treated as confirmed. Mirrors TRACK_CONFIRMATION_FRAMES.
#   3 frames at ~8 AI-FPS = ~375ms of consistent evidence required.
ANPR_CONFIRMATION_FRAMES = int(os.getenv("ANPR_CONFIRMATION_FRAMES", "3"))

# ANPR_TRACK_TIMEOUT:
#   Seconds without a new frame for a given vehicle track before its plate state
#   is expired. Prevents stale state for vehicles that leave the scene.
ANPR_TRACK_TIMEOUT = float(os.getenv("ANPR_TRACK_TIMEOUT", "10.0"))

# ANPR_DUPLICATE_COOLDOWN_SEC:
#   Per-(camera_id, plate_number) cooldown. Prevents creating hundreds of DB records
#   for a single stationary vehicle. Consistent with face watchlist 30s pattern.
ANPR_DUPLICATE_COOLDOWN_SEC = float(os.getenv("ANPR_DUPLICATE_COOLDOWN_SEC", "30.0"))

# ─── Face Alert Deduplication Configuration ───────────────────────────────────
# UNKNOWN_PERSON_ALERT_REFIRE_SEC:
#   Minimum seconds before a second UNKNOWN_PERSON_DETECTED alert can be created
#   for the SAME face track_id. Once an alert is active for a track, no new alert
#   is generated until this interval expires AND the track leaves+re-enters frame.
#   Default: 300s (5 min). Set to 0 to disable re-alerting entirely.
UNKNOWN_PERSON_ALERT_REFIRE_SEC = float(os.getenv("UNKNOWN_PERSON_ALERT_REFIRE_SEC", "300.0"))

# WATCHLIST_FACE_ALERT_REFIRE_SEC:
#   Same cooldown for FACE_WATCHLIST_MATCH events.
WATCHLIST_FACE_ALERT_REFIRE_SEC = float(os.getenv("WATCHLIST_FACE_ALERT_REFIRE_SEC", "300.0"))

# WATCHLIST_FACE_CONFIRMATION_FRAMES:
#   Number of consecutive high-quality recognition frames required before a
#   FACE_WATCHLIST_MATCH alert is generated. Prevents single-frame false positives.
#   Default: 2 (two consecutive frames with the same identity match).
WATCHLIST_FACE_CONFIRMATION_FRAMES = int(os.getenv("WATCHLIST_FACE_CONFIRMATION_FRAMES", "2"))
