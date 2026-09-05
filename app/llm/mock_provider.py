import json
from typing import Dict, Any
from app.llm.base import LLMProvider
from app.llm.models import LLMResult

class MockProvider(LLMProvider):
    """
    Completely isolated mock LLM provider with zero network interaction.
    """
    def classify(self, context: Dict[str, Any]) -> LLMResult:
        # 1. Simulated failure triggers
        if context.get("force_llm_failure"):
            raise RuntimeError("Mock LLM network/API failure")
            
        if context.get("force_malformed_json"):
            raise ValueError("Malformed JSON response from mock LLM")
            
        if context.get("force_missing_fields"):
            # Return result missing reasoning / bucket
            raise ValueError("Missing expected field in LLM response: bucket")

        # 2. Simulated Bucket C trigger (safety violation)
        if context.get("force_llm_c_prediction"):
            return LLMResult(
                bucket="C",
                confidence=0.95,
                reasoning="Mocked Bucket C safety violation",
                model="mock-deterministic",
                provider="mock"
            )
            
        # 3. Simulated invalid confidence trigger
        if context.get("force_invalid_confidence"):
            # Will be rejected by Pydantic / service validation
            raise ValueError("Confidence out of bounds")

        # 4. Simulated unknown bucket trigger
        if context.get("force_unknown_bucket"):
            raise ValueError("Invalid bucket predicted: Z")

        # 5. Simulated markdown fenced JSON trigger
        if context.get("force_markdown_fenced"):
            json_str = '```json\n{\n  "bucket": "B",\n  "confidence": 0.88,\n  "reasoning": "Parsed from markdown fences"\n}\n```'
            # Extract json
            raw = json_str.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1])
            data = json.loads(raw)
            return LLMResult(
                bucket=data["bucket"],
                confidence=float(data["confidence"]),
                reasoning=data["reasoning"],
                model="mock-deterministic",
                provider="mock"
            )

        # 6. Default deterministic logic based on amount
        amount = context.get("amount", 0)
        bucket = "A" if amount > 1000 else "B"
        
        return LLMResult(
            bucket=bucket,
            confidence=0.85,
            reasoning=f"Deterministic mock classification based on amount {amount}",
            model="mock-deterministic",
            provider="mock"
        )
