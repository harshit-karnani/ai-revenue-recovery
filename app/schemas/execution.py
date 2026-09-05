from pydantic import BaseModel, Field
from typing import Optional
from app.schemas.payment import PaymentEvent

class EvaluationRequest(BaseModel):
    transaction_id: str = Field(..., description="The unique identifier of the transaction being evaluated.")
    event: PaymentEvent

class EvaluationResponse(BaseModel):
    decision_id: str
    failure_code: Optional[str] = None
    bucket: Optional[str] = None
    classified_by: str
    confidence: Optional[float] = None
    strategy: Optional[str] = None
    strategy_id: Optional[str] = None
    requires_llm: bool
    requires_ml: bool
    ml_prediction: Optional[str] = None
    ml_confidence: Optional[float] = None
    regulatory_block: bool
    reason: Optional[str] = None
    next_action: str
    reasoning: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None

class ExecutionRequest(BaseModel):
    decision_id: str = Field(..., min_length=1)
    transaction_id: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1, max_length=255)
