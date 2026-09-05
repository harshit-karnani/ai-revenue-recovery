import datetime
from typing import Optional
from app.schemas.payment import PaymentEvent
from app.models.recovery_decision_record import RecoveryDecisionRecord
from app.core.regulatory_rules import (
    MAX_TOTAL_ATTEMPTS,
    PRE_DEBIT_REQUIRED_HOURS,
    DEFAULT_AFA_LIMIT_INR,
    EXCEPTION_AFA_LIMIT_INR,
    AFA_EXCEPTION_CATEGORIES,
    IST_TZ,
    EXECUTION_BLOCK_START,
    EXECUTION_BLOCK_END,
    AFTERNOON_VALID_END,
    NIGHT_VALID_START
)

# 13 Named Safety Rejection Constants
SAFETY_RETRY_CAP_EXCEEDED = "SAFETY_RETRY_CAP_EXCEEDED"
SAFETY_BUCKET_C_FORBIDDEN = "SAFETY_BUCKET_C_FORBIDDEN"
SAFETY_INVALID_STRATEGY = "SAFETY_INVALID_STRATEGY"
SAFETY_STRATEGY_UNAUTHORIZED = "SAFETY_STRATEGY_UNAUTHORIZED"
SAFETY_MORNING_WINDOW_BLOCKED = "SAFETY_MORNING_WINDOW_BLOCKED"
SAFETY_EVENING_WINDOW_BLOCKED = "SAFETY_EVENING_WINDOW_BLOCKED"
SAFETY_DUPLICATE_EXECUTION = "SAFETY_DUPLICATE_EXECUTION"
SAFETY_INVALID_AMOUNT = "SAFETY_INVALID_AMOUNT"
SAFETY_UNRESOLVED_STATE = "SAFETY_UNRESOLVED_STATE"
SAFETY_INVALID_STATUS = "SAFETY_INVALID_STATUS"
SAFETY_PREDEBIT_BLIND_RETRY_FORBIDDEN = "SAFETY_PREDEBIT_BLIND_RETRY_FORBIDDEN"
SAFETY_AFA_BLIND_RETRY_FORBIDDEN = "SAFETY_AFA_BLIND_RETRY_FORBIDDEN"
SAFETY_MANDATE_INACTIVE = "SAFETY_MANDATE_INACTIVE"

def validate_execution(
    event: PaymentEvent,
    decision: RecoveryDecisionRecord,
    strategy_name: Optional[str] = None,
    strategy_applicable_bucket: Optional[str] = None
) -> Optional[str]:
    """
    Validates all safety invariants immediately prior to gateway execution.
    Returns a named rejection constant if any invariant is violated, or None if safe to execute.
    """
    # 1. Permanently failed / retry cap exceeded
    if event.attempt_count >= MAX_TOTAL_ATTEMPTS:
        return SAFETY_RETRY_CAP_EXCEEDED

    # 2. Bucket C is forbidden from gateway execution
    if decision.bucket == "C":
        return SAFETY_BUCKET_C_FORBIDDEN

    # 3. Unresolved LLM or ambiguous state
    if decision.requires_llm or not decision.bucket or decision.bucket not in ("A", "B"):
        return SAFETY_UNRESOLVED_STATE
    if decision.next_action != "execute_strategy":
        return SAFETY_UNRESOLVED_STATE

    # 4. Unknown or missing strategy
    if not decision.strategy_id:
        return SAFETY_INVALID_STRATEGY

    # 5. Invalid or non-positive amount
    if event.amount <= 0:
        return SAFETY_INVALID_AMOUNT

    # 6. Duplicate or already-executing execution
    if decision.status in ("executing", "executed"):
        return SAFETY_DUPLICATE_EXECUTION
    if decision.status != "pending":
        return SAFETY_INVALID_STATUS

    # 7. Strategy unauthorized for decision bucket
    if strategy_applicable_bucket and strategy_applicable_bucket != decision.bucket:
        return SAFETY_STRATEGY_UNAUTHORIZED

    # 8. Morning execution-window block (10:00 - 13:00 IST for UPI AutoPay)
    # 9. Evening execution-window block (17:00 - 21:30 IST for UPI AutoPay)
    if event.payment_type == "upi_autopay":
        local_dt = event.current_time.astimezone(IST_TZ)
        local_time = local_dt.time()
        
        if EXECUTION_BLOCK_START <= local_time < EXECUTION_BLOCK_END:
            return SAFETY_MORNING_WINDOW_BLOCKED
            
        if AFTERNOON_VALID_END <= local_time < NIGHT_VALID_START:
            return SAFETY_EVENING_WINDOW_BLOCKED

    # 10. Pre-debit violation: blind retry without delay_retry
    if event.notification_sent_at:
        elapsed = event.current_time - event.notification_sent_at
        if elapsed.total_seconds() < PRE_DEBIT_REQUIRED_HOURS * 3600:
            if strategy_name != "delay_retry":
                return SAFETY_PREDEBIT_BLIND_RETRY_FORBIDDEN

    # 11. AFA violation: blind retry without trigger_reauthentication_link
    limit = EXCEPTION_AFA_LIMIT_INR if event.subscription_category in AFA_EXCEPTION_CATEGORIES else DEFAULT_AFA_LIMIT_INR
    if event.amount > limit:
        if strategy_name != "trigger_reauthentication_link":
            return SAFETY_AFA_BLIND_RETRY_FORBIDDEN

    # 12. Transaction/mandate status check
    if event.mandate_status != "active":
        return SAFETY_MANDATE_INACTIVE

    return None
