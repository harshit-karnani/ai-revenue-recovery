from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.dashboard import BatchSummaryResponse
from app.services.batch_simulator import get_batch_summary, run_150_batch_simulation

router = APIRouter()

@router.get("/batch-summary", response_model=BatchSummaryResponse)
def get_batch_revenue_summary(db: Session = Depends(get_db)):
    """
    Returns the real database-aggregated revenue recovery metrics for the simulated demo batch.
    Operates at unique transaction level so retries cannot inflate recovered revenue.
    """
    return get_batch_summary(db, merchant_id="demo_batch")


@router.post("/run-batch", response_model=BatchSummaryResponse, status_code=status.HTTP_200_OK)
async def trigger_run_demo_batch(db: Session = Depends(get_db)):
    """
    Runs a safe 150-transaction simulated recovery batch through the Recovery Engine.
    Uses GatewaySimulator and MockLLM (zero real gateway calls, zero Gemini quota consumed).
    Returns real database-persisted aggregate outcomes.
    """
    return await run_150_batch_simulation(db)
