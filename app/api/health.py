import os
import joblib
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db
from app.core.config import settings
from app.services.ml_classifier import MODEL_PATH

router = APIRouter()

@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

@router.get("/system-status")
def system_status(db: Session = Depends(get_db)):
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    ml_exists = os.path.exists(MODEL_PATH)
    active_model = "mock-deterministic" if settings.LLM_PROVIDER == "mock" else settings.LLM_MODEL
    
    return {
        "status": "online",
        "database_connected": db_ok,
        "active_llm_provider": settings.LLM_PROVIDER,
        "active_llm_model": active_model,
        "configured_llm_model": settings.LLM_MODEL,
        "llm_model": active_model,
        "ml_model_loaded": ml_exists,
        "ml_confidence_threshold": settings.ML_CONFIDENCE_THRESHOLD,
        "environment": settings.ENVIRONMENT
    }

