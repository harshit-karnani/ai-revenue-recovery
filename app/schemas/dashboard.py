from pydantic import BaseModel
from typing import Dict, Optional

class BucketSummary(BaseModel):
    amount_at_risk: float
    amount_recovered: float

class BatchSummaryResponse(BaseModel):
    total_transactions: int
    total_amount_at_risk: float
    total_amount_recovered: float
    recovery_rate_by_amount: float
    recovery_rate_by_count: float
    breakdown_by_bucket: Dict[str, BucketSummary]
    permanently_failed: BucketSummary
    currency: str = "INR"
