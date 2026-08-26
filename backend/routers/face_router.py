from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import FaceDetection
from backend.auth import get_current_user

router = APIRouter(prefix="/api/faces", tags=["Face Detection"])

@router.get("")
def get_face_detections(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    results = db.query(FaceDetection).order_by(FaceDetection.timestamp.desc()).limit(limit).all()
    return results
