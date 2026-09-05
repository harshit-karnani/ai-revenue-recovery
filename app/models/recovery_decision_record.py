from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Float, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base

class RecoveryDecisionRecord(Base):
    __tablename__ = "recovery_decisions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=False, index=True)
    bucket = Column(String, nullable=False)
    strategy_id = Column(String, ForeignKey("recovery_strategies.id"), nullable=True) # nullable if no strategy selected (e.g. llm failure)
    classified_by = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    requires_llm = Column(Boolean, nullable=False, default=False)
    next_action = Column(String, nullable=False)
    reasoning = Column(Text, nullable=True)
    llm_provider = Column(String, nullable=True)
    llm_model = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transaction = relationship("Transaction")
    strategy = relationship("RecoveryStrategy")
