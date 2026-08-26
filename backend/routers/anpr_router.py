from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import ANPRResult
from backend.auth import get_current_user

router = APIRouter(prefix="/api/anpr", tags=["ANPR"])

@router.get("")
def get_anpr_records(
    plate_query: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(ANPRResult)
    if plate_query:
        query = query.filter(ANPRResult.plate_text.ilike(f"%{plate_query}%"))
    results = query.order_by(ANPRResult.timestamp.desc()).limit(limit).all()
    return results
