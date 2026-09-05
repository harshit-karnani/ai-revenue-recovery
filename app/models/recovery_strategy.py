from sqlalchemy import Column, String, Integer
import uuid

from app.core.database import Base

class RecoveryStrategy(Base):
    __tablename__ = "recovery_strategies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True, nullable=False)
    applicable_bucket = Column(String, nullable=False)
    description = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=0)
