import os

class Settings:
    PROJECT_NAME: str = "IBVAP - Intelligent Border Video Analytics Platform"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ibvap")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "ibvap_super_secret_jwt_key_2026_sih_border_surveillance")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
    MODEL_PATH: str = os.getenv("MODEL_PATH", "storage/models/yolov8n.onnx")
    MODEL_DEVICE: str = os.getenv("MODEL_DEVICE", "cpu")
    DEFAULT_CONFIDENCE: float = float(os.getenv("DEFAULT_CONFIDENCE", "0.50"))
    RTSP_TIMEOUT: int = int(os.getenv("RTSP_TIMEOUT", "10"))
    STORAGE_PATH: str = os.getenv("STORAGE_PATH", "storage/evidence")

settings = Settings()
