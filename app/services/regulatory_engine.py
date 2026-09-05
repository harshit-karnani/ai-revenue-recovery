import datetime
from app.schemas.payment import PaymentEvent, RegulatoryEvaluationResult
from app.core.regulatory_rules import (
    PRE_DEBIT_REQUIRED_HOURS,
    DEFAULT_AFA_LIMIT_INR,
    EXCEPTION_AFA_LIMIT_INR,
    MAX_TOTAL_ATTEMPTS,
    IST_TZ,
    EXECUTION_BLOCK_START,
    EXECUTION_BLOCK_END,
    AFTERNOON_VALID_START,
    AFTERNOON_VALID_END,
    NIGHT_VALID_START,
    AFA_EXCEPTION_CATEGORIES
)

def evaluate_payment(event: PaymentEvent) -> RegulatoryEvaluationResult:
    # Rule 1: Retry cap
    if event.attempt_count >= MAX_TOTAL_ATTEMPTS:
        return RegulatoryEvaluationResult(
            allowed=False,
            failure_code="permanently_failed",
            bucket=None,
            recommended_strategy=None,
            reason="Maximum retry limit reached.",
            retry_allowed=False
        )

    # Rule 2: Pre-debit notification
    if event.notification_sent_at:
        elapsed = event.current_time - event.notification_sent_at
        if elapsed.total_seconds() < PRE_DEBIT_REQUIRED_HOURS * 3600:
            return RegulatoryEvaluationResult(
                allowed=False,
                failure_code="missed_predebit_notification",
                bucket="C",
                recommended_strategy="delay_retry",
                reason="Required notification window has not elapsed.",
                retry_allowed=True
            )

    # Rule 3: AFA Threshold
    limit = EXCEPTION_AFA_LIMIT_INR if event.subscription_category in AFA_EXCEPTION_CATEGORIES else DEFAULT_AFA_LIMIT_INR
    if event.amount > limit:
        return RegulatoryEvaluationResult(
            allowed=False,
            failure_code="afa_reauth_required",
            bucket="C",
            recommended_strategy="trigger_reauthentication_link",
            reason="Amount exceeds AFA threshold for this category.",
            authentication_required=True,
            retry_allowed=False
        )

    # Rule 4: NPCI Execution Window (UPI AutoPay)
    if event.payment_type == "upi_autopay":
        # Convert to IST for execution window check
        local_dt = event.current_time.astimezone(IST_TZ)
        local_time = local_dt.time()
        
        is_morning_block = EXECUTION_BLOCK_START <= local_time < EXECUTION_BLOCK_END
        is_evening_block = AFTERNOON_VALID_END <= local_time < NIGHT_VALID_START
        
        if is_morning_block or is_evening_block:
            return RegulatoryEvaluationResult(
                allowed=False,
                failure_code="execution_window_block",
                bucket="C",
                recommended_strategy="reschedule_valid_window",
                reason="UPI AutoPay is scheduled during the blocked execution window.",
                next_valid_execution_time=get_next_valid_execution_window(event.current_time),
                retry_allowed=False
            )

    # Allowed
    return RegulatoryEvaluationResult(
        allowed=True,
        retry_allowed=True
    )

def get_next_valid_execution_window(current_time: datetime.datetime) -> datetime.datetime:
    local_dt = current_time.astimezone(IST_TZ)
    local_time = local_dt.time()

    # If before 10:00, valid now. (But we shouldn't be asked unless blocked, but let's handle it)
    if local_time < EXECUTION_BLOCK_START:
        return current_time # already valid

    if EXECUTION_BLOCK_START <= local_time < AFTERNOON_VALID_START:
        # blocked, next is 13:00 today
        next_valid = datetime.datetime.combine(local_dt.date(), AFTERNOON_VALID_START, tzinfo=IST_TZ)
        return next_valid

    if AFTERNOON_VALID_START <= local_time < AFTERNOON_VALID_END:
        return current_time # already valid

    if AFTERNOON_VALID_END <= local_time < NIGHT_VALID_START:
        # blocked, next is 21:30 today
        next_valid = datetime.datetime.combine(local_dt.date(), NIGHT_VALID_START, tzinfo=IST_TZ)
        return next_valid

    # >= 21:30, valid now
    return current_time
