from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.schemas.recovery import RecoveryDecision
from app.models.recovery_strategy import RecoveryStrategy
from app.models.strategy_performance import StrategyPerformance

# Pre-defined deterministic mappings for Bucket A and C
STRATEGY_MAPPING = {
    # Bucket A
    "insufficient_funds": "delay_retry",
    "expired_card": "notify_customer",
    "invalid_card": "notify_customer",
    "card_blocked": "notify_customer",
    
    # Bucket B (High confidence ML or LLM or ML Fallback)
    "generic_decline": "short_delay_retry",
    "do_not_honor": "short_delay_retry",
    "processing_error": "short_delay_retry",
    "timeout": "short_delay_retry",

    # Bucket C (Regulatory)
    "missed_predebit_notification": "delay_retry",
    "afa_reauth_required": "trigger_reauthentication_link",
    "execution_window_block": "reschedule_valid_window",
    "mandate_expired": "refresh_mandate"
}

def get_best_strategy(db: Optional[Session], bucket: str, fallback_strategy_name: str) -> str:
    """
    Adaptive routing: select the strategy with highest success rate for the bucket,
    if it has at least MIN_SAMPLE=5 attempts. Otherwise return the fallback.
    Bucket C and permanently_failed cannot enter adaptive routing.
    Unauthorized strategies cannot be selected.
    """
    if not db or bucket not in ("A", "B"):
        return fallback_strategy_name
        
    try:
        strategies = db.query(RecoveryStrategy).filter(RecoveryStrategy.applicable_bucket == bucket).all()
        if not strategies:
            return fallback_strategy_name
            
        best_strategy_name = fallback_strategy_name
        max_success_rate = -1.0
        
        for strategy in strategies:
            if strategy.applicable_bucket != bucket:
                continue
                
            perf = db.query(StrategyPerformance).filter(
                StrategyPerformance.strategy_id == strategy.id,
                StrategyPerformance.bucket == bucket
            ).first()
            
            if perf and hasattr(perf, "attempt_count") and isinstance(perf.attempt_count, (int, float)) and perf.attempt_count >= 5:
                success_rate = perf.success_count / perf.attempt_count
                if success_rate > max_success_rate:
                    max_success_rate = success_rate
                    best_strategy_name = strategy.name
                    
        if max_success_rate >= 0.0:
            return best_strategy_name
    except Exception:
        pass
        
    return fallback_strategy_name

def route_strategy(classification: Dict[str, Any], db: Optional[Session] = None) -> RecoveryDecision:
    """
    Takes a deterministic classification and routes it to the appropriate recovery strategy,
    applying adaptive routing where applicable.
    """
    failure_code = classification["failure_code"]
    bucket = classification["bucket"]
    requires_ml = classification["requires_ml"]
    requires_llm = classification.get("requires_llm", False)
    classified_by = classification.get("classified_by", "rules")
    ml_prediction = classification.get("ml_prediction")
    ml_confidence = classification.get("ml_confidence")
    
    strategy_name = None
    next_action = "await_ml_classification"

    # 1. Terminal failure
    if failure_code == "permanently_failed":
        strategy_name = None
        next_action = "terminate_pipeline"
        
    # 2. Low confidence ML (Escalate to LLM, or LLM unavailable fail-closed)
    elif requires_llm and classified_by != "llm":
        strategy_name = None
        next_action = "llm_unavailable" if classified_by == "llm_unavailable" else "await_llm_reasoning"
        
    # 3. Ambiguous (Pre-ML state, only if requires_ml is True and classified by rules)
    elif requires_ml and classified_by == "rules":
        strategy_name = None
        next_action = "await_ml_classification"
        
    # 4. Deterministic cases (Bucket A, C) or ML/LLM (Bucket B, A)
    elif bucket in ["A", "B", "C"]:
        if bucket == "A":
            if failure_code in ["expired_card", "invalid_card", "card_blocked"]:
                base_strategy = "notify_customer"
            else:
                base_strategy = "delay_retry"
        elif bucket == "B":
            base_strategy = "short_delay_retry"
        else: # Bucket C
            base_strategy = STRATEGY_MAPPING.get(failure_code, "delay_retry")
                
        if classified_by in ["ml", "llm"] and bucket in ["A", "B"]:
            if base_strategy:
                # Apply adaptive routing for A and B
                strategy_name = get_best_strategy(db, bucket, base_strategy)
                next_action = "execute_strategy"
        else:
            strategy_name = base_strategy
            if strategy_name:
                next_action = "execute_strategy"
            else:
                next_action = "await_manual_review"

    # Look up the actual strategy ID if db session is provided
    strategy_id = None
    if db and strategy_name and bucket:
        try:
            strategy_obj = db.query(RecoveryStrategy).filter(
                RecoveryStrategy.name == strategy_name,
                RecoveryStrategy.applicable_bucket == bucket
            ).first()
            if strategy_obj and hasattr(strategy_obj, "id"):
                strategy_id = str(strategy_obj.id)
        except Exception:
            pass

    return RecoveryDecision(
        failure_code=failure_code,
        bucket=bucket,
        classified_by=classified_by,
        confidence=classification.get("confidence"),
        strategy=strategy_name,
        strategy_id=strategy_id,
        requires_ml=requires_ml,
        requires_llm=requires_llm,
        ml_prediction=ml_prediction,
        ml_confidence=ml_confidence,
        regulatory_block=classification["regulatory_block"],
        reason=classification["reason"],
        next_action=next_action
    )
