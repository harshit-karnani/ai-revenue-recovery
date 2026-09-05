import pytest
from app.services.strategy_router import route_strategy

def test_router_terminal():
    classification = {
        "failure_code": "permanently_failed",
        "bucket": None,
        "requires_ml": False,
        "confidence": 1.0,
        "regulatory_block": False,
        "reason": "Retry cap exceeded",
        "classified_by": "rules"
    }
    decision = route_strategy(classification)
    
    assert decision.strategy is None
    assert decision.next_action == "terminate_pipeline"
    assert decision.requires_ml is False
    assert decision.requires_llm is False
    assert decision.regulatory_block is False

def test_router_bucket_c():
    classification = {
        "failure_code": "afa_reauth_required",
        "bucket": "C",
        "requires_ml": False,
        "confidence": 1.0,
        "regulatory_block": True,
        "reason": "AFA Failed",
        "classified_by": "rules"
    }
    decision = route_strategy(classification)
    
    assert decision.strategy == "trigger_reauthentication_link"
    assert decision.next_action == "execute_strategy"
    assert decision.requires_llm is False
    assert decision.regulatory_block is True

def test_router_bucket_a():
    classification = {
        "failure_code": "insufficient_funds",
        "bucket": "A",
        "requires_ml": False,
        "confidence": 1.0,
        "regulatory_block": False,
        "reason": "No funds",
        "classified_by": "rules"
    }
    decision = route_strategy(classification)
    
    assert decision.strategy == "delay_retry"
    assert decision.next_action == "execute_strategy"
    assert decision.requires_llm is False
    assert decision.regulatory_block is False

def test_router_bucket_b_pre_ml():
    classification = {
        "failure_code": "generic_decline",
        "bucket": "B",
        "requires_ml": True,
        "confidence": None,
        "regulatory_block": False,
        "reason": "Generic",
        "classified_by": "rules"
    }
    decision = route_strategy(classification)
    
    assert decision.strategy is None
    assert decision.next_action == "await_ml_classification"
    assert decision.requires_ml is True
    assert decision.requires_llm is False

def test_router_bucket_b_high_confidence_ml():
    classification = {
        "failure_code": "generic_decline",
        "bucket": "B",
        "requires_ml": True,
        "requires_llm": False,
        "confidence": 0.85,
        "regulatory_block": False,
        "reason": "Generic",
        "classified_by": "ml"
    }
    decision = route_strategy(classification)
    
    assert decision.strategy == "short_delay_retry"
    assert decision.next_action == "execute_strategy"
    assert decision.requires_ml is True
    assert decision.requires_llm is False
    assert decision.classified_by == "ml"

def test_router_bucket_b_low_confidence_ml():
    cls = {
        "failure_code": "generic_decline",
        "bucket": "B",
        "requires_ml": True,
        "requires_llm": True,
        "classified_by": "ml",
        "confidence": 0.65,
        "ml_prediction": "B",
        "ml_confidence": 0.65,
        "regulatory_block": False,
        "reason": "Ambig"
    }
    decision = route_strategy(cls)
    assert decision.strategy is None
    assert decision.next_action == "await_llm_reasoning"
    assert decision.requires_llm is True

def test_router_bucket_a_ml():
    cls = {
        "failure_code": "generic_decline",
        "bucket": "A",
        "requires_ml": True,
        "requires_llm": False,
        "classified_by": "ml",
        "confidence": 0.85,
        "ml_prediction": "A",
        "ml_confidence": 0.85,
        "regulatory_block": False,
        "reason": "Ambig predicted A"
    }
    decision = route_strategy(cls)
    assert decision.strategy == "delay_retry" # Bucket A seeded strategy
    assert decision.next_action == "execute_strategy"
    assert decision.requires_llm is False

def test_router_unknown():
    classification = {
        "failure_code": "unknown_code",
        "bucket": None,
        "requires_ml": True,
        "confidence": None,
        "regulatory_block": False,
        "reason": "Unknown",
        "classified_by": "rules"
    }
    decision = route_strategy(classification)
    
    assert decision.strategy is None
    assert decision.next_action == "await_ml_classification"
    assert decision.requires_ml is True
    assert decision.requires_llm is False
