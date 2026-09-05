from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Integer, Boolean, Float, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    merchant_id = Column(String, index=True, nullable=False)
    customer_id = Column(String, index=True, nullable=False)
    amount = Column(Numeric, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    status = Column(String, index=True, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    payment_attempts = relationship("PaymentAttempt", back_populates="transaction")
    recovery_actions = relationship("RecoveryAction", back_populates="transaction")
