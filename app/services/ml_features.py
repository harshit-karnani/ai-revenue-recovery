import pandas as pd
from typing import Dict, Any, List
from app.schemas.payment import PaymentEvent
from app.core.regulatory_rules import (
    IST_TZ,
    EXECUTION_BLOCK_START,
    EXECUTION_BLOCK_END,
    AFTERNOON_VALID_END,
    NIGHT_VALID_START
)

def _in_congestion_window(dt) -> bool:
    """
    Returns True if time is within NPCI peak hours (execution windows).
    Window 1: 10:00 (inclusive) to 13:00 (exclusive)
    Window 2: 17:00 (inclusive) to 21:30 (exclusive)
    """
    local_time = dt.time()
    
    is_morning_block = EXECUTION_BLOCK_START <= local_time < EXECUTION_BLOCK_END
    is_evening_block = AFTERNOON_VALID_END <= local_time < NIGHT_VALID_START
    
    return is_morning_block or is_evening_block

def extract_features(events: List[PaymentEvent]) -> pd.DataFrame:
    """
    Extracts features for ML training or inference.
    Takes a list of PaymentEvents and returns a pandas DataFrame.
    """
    records = []
    for event in events:
        # Get current time in IST
        dt = event.current_time.astimezone(IST_TZ)
        
        records.append({
            "amount": event.amount,
            "hour_of_day": dt.hour,
            "day_of_month": dt.day,
            "day_of_week": dt.weekday(), # Monday = 0, Sunday = 6
            "attempt_count": event.attempt_count,
            "in_congestion_window": int(_in_congestion_window(dt)),
            "decline_code": event.decline_code or "unknown",
            "payment_method": event.payment_type,
            "subscription_category": event.subscription_category
        })
    
    return pd.DataFrame(records)

def extract_single_feature(event: PaymentEvent) -> pd.DataFrame:
    """
    Convenience method for a single event.
    """
    return extract_features([event])
