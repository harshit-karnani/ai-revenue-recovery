from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base

class StrategyPerformance(Base):
    __tablename__ = "strategy_performance"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    bucket = Column(String, index=True, nullable=False)
    strategy_id = Column(String, ForeignKey("recovery_strategies.id"), nullable=False)
    success_count = Column(Integer, nullable=False, default=0)
    attempt_count = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("bucket", "strategy_id", name="uix_bucket_strategy"),
    )

    strategy = relationship("RecoveryStrategy")
