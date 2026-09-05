from sqlalchemy import Column, String, Boolean, Integer
import uuid

from app.core.database import Base

class FailureReason(Base):
    __tablename__ = "failure_reasons"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    decline_code = Column(String, unique=True, index=True, nullable=False)
    bucket = Column(String, nullable=False)  # 'A', 'B', 'C'
    description = Column(String, nullable=False)
    is_ambiguous = Column(Boolean, nullable=False, default=False)
    source_type = Column(String, nullable=False, default="simulated")
