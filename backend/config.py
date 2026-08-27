import os

class Settings:
    JWT_SECRET: str = os.getenv("JWT_SECRET", "ibvap_super_secret_jwt_key_2026_sih_border_surveillance")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

settings = Settings()

# Real-time AI Object Detection & Confirmation Configuration
DETECTION_CONFIDENCE_THRESHOLD = float(os.getenv("DETECTION_CONFIDENCE_THRESHOLD", "0.45"))
NMS_IOU_THRESHOLD = float(os.getenv("NMS_IOU_THRESHOLD", "0.45"))

# Multi-Object Tracker Confirmation Pipeline
TRACK_CONFIRMATION_FRAMES = int(os.getenv("TRACK_CONFIRMATION_FRAMES", "3"))
TRACK_MAX_DISAPPEARED = int(os.getenv("TRACK_MAX_DISAPPEARED", "15"))

# Evidence Capture & Throttling Configuration
EVIDENCE_CAPTURE_INTERVAL_SEC = float(os.getenv("EVIDENCE_CAPTURE_INTERVAL_SEC", "5.0"))

# Event & Behavior Rule Evaluation
LOITERING_THRESHOLD_SEC = float(os.getenv("LOITERING_THRESHOLD_SEC", "30.0"))
ALERT_COOLDOWN_SEC = float(os.getenv("ALERT_COOLDOWN_SEC", "60.0"))
