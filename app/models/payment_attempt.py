from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base

class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String, ForeignKey("transactions.id"), index=True, nullable=False)
    attempt_number = Column(Integer, nullable=False)
    gateway_used = Column(String, nullable=False)
    decline_code = Column(String, index=True, nullable=True)
    decline_message = Column(String, nullable=True)
    attempted_at = Column(DateTime(timezone=True), nullable=False)
    succeeded = Column(Boolean, nullable=False, default=False)

    transaction = relationship("Transaction", back_populates="payment_attempts")
