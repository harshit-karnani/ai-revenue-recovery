from pydantic import BaseModel, Field
from typing import Optional

class LLMResult(BaseModel):
    bucket: str = Field(..., description="A or B only")
    confidence: float = Field(..., ge=0, le=1)
    reasoning: str
    model: str
    provider: str
