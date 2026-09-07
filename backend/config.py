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
# ─── Face Detection & Recognition Configuration ──────────────────────────────
# FACE_CONFIDENCE_THRESHOLD:
#   Minimum score from YuNet deep neural network face detector (0.0 to 1.0).
#   0.55 provides high precision while catching moderate face angles & lighting.
FACE_CONFIDENCE_THRESHOLD = float(os.getenv("FACE_CONFIDENCE_THRESHOLD", "0.55"))

# MIN_FACE_SIZE:
#   Minimum width and height in pixels for a valid face detection crop.
MIN_FACE_SIZE = int(os.getenv("MIN_FACE_SIZE", "28"))

# MIN_FACE_QUALITY:
#   Multi-metric face quality score threshold (0.0 to 1.0) combining Laplacian blur,
#   exposure/brightness, contrast, and resolution.
MIN_FACE_QUALITY = float(os.getenv("MIN_FACE_QUALITY", "0.35"))

# FACE_RECOGNITION_THRESHOLD:
#   Cosine similarity threshold for SFace 128-dimensional facial embedding matching.
#   OpenCV FaceRecognizerSF cosine distance baseline: 0.363; standard: 0.380.
FACE_RECOGNITION_THRESHOLD = float(os.getenv("FACE_RECOGNITION_THRESHOLD", "0.38"))

# FACE_RECOGNITION_INTERVAL_SEC:
#   Interval in seconds to re-evaluate SFace embedding on a continuous face track.
FACE_RECOGNITION_INTERVAL_SEC = float(os.getenv("FACE_RECOGNITION_INTERVAL_SEC", "1.5"))

# FACE_TRACK_CONFIRMATION_FRAMES:
#   Consecutive frames required to confirm a new FaceTrack before database logging.
FACE_TRACK_CONFIRMATION_FRAMES = int(os.getenv("FACE_TRACK_CONFIRMATION_FRAMES", "2"))

# FACE_TRACK_MAX_DISAPPEARED:
#   Maximum missed frames before a FaceTrack is terminated.
FACE_TRACK_MAX_DISAPPEARED = int(os.getenv("FACE_TRACK_MAX_DISAPPEARED", "20"))

# FACE_RECORD_COOLDOWN_SEC:
#   Cooldown in seconds between persisting successive FaceDetection database rows
#   for the SAME continuously present face track.
FACE_RECORD_COOLDOWN_SEC = float(os.getenv("FACE_RECORD_COOLDOWN_SEC", "15.0"))

# ─── ANPR (Automatic Number Plate Recognition) Configuration ─────────────────
ANPR_PLATE_CONFIDENCE_THRESHOLD = float(os.getenv("ANPR_PLATE_CONFIDENCE_THRESHOLD", "0.35"))
ANPR_OCR_CONFIDENCE_THRESHOLD = float(os.getenv("ANPR_OCR_CONFIDENCE_THRESHOLD", "0.60"))
ANPR_CONFIRMATION_FRAMES = int(os.getenv("ANPR_CONFIRMATION_FRAMES", "3"))
ANPR_TRACK_TIMEOUT = float(os.getenv("ANPR_TRACK_TIMEOUT", "10.0"))
ANPR_DUPLICATE_COOLDOWN_SEC = float(os.getenv("ANPR_DUPLICATE_COOLDOWN_SEC", "30.0"))

# ─── Face Alert Deduplication Configuration ───────────────────────────────────
# UNKNOWN_PERSON_ALERT_REFIRE_SEC:
#   Minimum seconds before a second UNKNOWN_PERSON_DETECTED alert can be created
#   for the SAME face track_id.
#   Default: 300s (5 min).
UNKNOWN_PERSON_ALERT_REFIRE_SEC = float(os.getenv("UNKNOWN_PERSON_ALERT_REFIRE_SEC", "300.0"))

# WATCHLIST_FACE_ALERT_REFIRE_SEC:
#   Cooldown for FACE_WATCHLIST_MATCH alerts to prevent alert spamming.
#   Default: 120s (2 min).
WATCHLIST_FACE_ALERT_REFIRE_SEC = float(os.getenv("WATCHLIST_FACE_ALERT_REFIRE_SEC", "120.0"))

# WATCHLIST_FACE_CONFIRMATION_FRAMES:
#   Number of consecutive high-quality recognition frames required before a
#   FACE_WATCHLIST_MATCH alert is generated. Prevents single-frame false positives.
#   Default: 2 (two consecutive frames with the same identity match).
WATCHLIST_FACE_CONFIRMATION_FRAMES = int(os.getenv("WATCHLIST_FACE_CONFIRMATION_FRAMES", "2"))


