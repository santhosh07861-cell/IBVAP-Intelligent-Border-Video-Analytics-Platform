from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.connection import get_db
from database.schema import ModelRegistry
from backend.auth import get_current_user

router = APIRouter(prefix="/api/models", tags=["Model Registry & Evaluation"])

@router.get("")
def list_models(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    models = db.query(ModelRegistry).all()
    return models
