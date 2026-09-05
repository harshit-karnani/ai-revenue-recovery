from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime

class PaymentEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    decline_code: Optional[str] = None
    amount: float = Field(..., ge=0)
    currency: str = "INR"
    payment_type: str
    subscription_category: str
    notification_sent_at: Optional[datetime] = None
    scheduled_at: datetime
    current_time: datetime
    attempt_count: int = Field(..., ge=0)
    mandate_status: str
    authentication_status: str
    force_llm_failure: Optional[bool] = False
    force_llm_c_prediction: Optional[bool] = False

class RegulatoryEvaluationResult(BaseModel):
    allowed: bool
    failure_code: Optional[str] = None
    bucket: Optional[str] = None
    recommended_strategy: Optional[str] = None
    reason: Optional[str] = None
    next_valid_execution_time: Optional[datetime] = None
    authentication_required: bool = False
    retry_allowed: bool = True
