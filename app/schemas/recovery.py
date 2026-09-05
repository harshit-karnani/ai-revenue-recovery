from pydantic import BaseModel
from typing import Optional

class RecoveryDecision(BaseModel):
    failure_code: str
    bucket: Optional[str] = None
    classified_by: str = "rules"
    confidence: Optional[float] = None
    strategy: Optional[str] = None
    strategy_id: Optional[str] = None
    requires_ml: bool
    requires_llm: bool
    ml_prediction: Optional[str] = None
    ml_confidence: Optional[float] = None
    regulatory_block: bool
    reason: Optional[str] = None
    next_action: str
