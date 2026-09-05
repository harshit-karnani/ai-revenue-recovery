import json
from typing import Dict, Any
from app.llm.base import LLMProvider
from app.llm.models import LLMResult
from app.core.config import settings

def get_llm_provider() -> LLMProvider:
    provider_name = settings.LLM_PROVIDER.lower()
    
    if provider_name == "gemini":
        from app.llm.gemini_provider import GeminiProvider
        return GeminiProvider()
    elif provider_name in ("claude", "anthropic"):
        from app.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    
    from app.llm.mock_provider import MockProvider
    return MockProvider()

def classify_with_llm(context: Dict[str, Any]) -> LLMResult:
    provider = get_llm_provider()
    
    result = provider.classify(context)
    
    # Provider-independent validation
    if result.bucket not in ("A", "B"):
        if result.bucket == "C":
            raise ValueError("Safety Violation: LLM output Bucket C")
        raise ValueError(f"Invalid bucket predicted: {result.bucket}")
        
    if not (0 <= result.confidence <= 1):
        raise ValueError("Confidence out of bounds")
        
    return result
