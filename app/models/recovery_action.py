from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base

class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String, ForeignKey("transactions.id"), index=True, nullable=False)
    strategy_id = Column(String, ForeignKey("recovery_strategies.id"), nullable=False)
    classified_by = Column(String, index=True, nullable=False)  # rules, ml, llm
    predicted_bucket = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    llm_reasoning = Column(Text, nullable=True)
    llm_provider = Column(String, nullable=True)
    executed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status = Column(String, nullable=False, default="pending")
    idempotency_key = Column(String, unique=True, index=True, nullable=True) # UniqueConstraint for idempotency

    transaction = relationship("Transaction", back_populates="recovery_actions")
    strategy = relationship("RecoveryStrategy")
