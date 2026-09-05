from abc import ABC, abstractmethod
from typing import Dict, Any
from app.llm.models import LLMResult

class LLMProvider(ABC):
    @abstractmethod
    def classify(self, context: Dict[str, Any]) -> LLMResult:
        """Classifies the failure using the given context."""
        pass
