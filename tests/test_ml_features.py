import pytest
from app.services.ml_features import extract_single_feature, _in_congestion_window
from app.schemas.payment import PaymentEvent
import datetime
from app.core.regulatory_rules import IST_TZ

def test_feature_extraction_logic():
    now = datetime.datetime.now(IST_TZ).replace(hour=14, minute=30, second=0, microsecond=0)
    
    event = PaymentEvent(
        amount=5000.50,
        payment_type="upi_autopay",
        subscription_category="ecommerce_subscription",
        notification_sent_at=(now - datetime.timedelta(hours=25)).isoformat(),
        scheduled_at=now.isoformat(),
        current_time=now.isoformat(),
        attempt_count=3,
        mandate_status="active",
        authentication_status="not_authenticated",
        decline_code="timeout"
    )
    
    df = extract_single_feature(event)
    
    assert len(df) == 1
    row = df.iloc[0]
    
    assert row["amount"] == 5000.50
    assert row["hour_of_day"] == 14
    assert row["day_of_month"] == now.day
    assert row["day_of_week"] == now.weekday()
    assert row["attempt_count"] == 3
    assert row["in_congestion_window"] == 0
    assert row["decline_code"] == "timeout"
    assert row["payment_method"] == "upi_autopay"
    assert row["subscription_category"] == "ecommerce_subscription"

def test_in_congestion_window_logic():
    # Window 1: 10:00 to 13:00
    dt_0959 = datetime.datetime(2026, 8, 25, 9, 59, 59, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_0959) is False
    
    dt_1000 = datetime.datetime(2026, 8, 25, 10, 0, 0, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_1000) is True
    
    dt_1259 = datetime.datetime(2026, 8, 25, 12, 59, 59, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_1259) is True
    
    dt_1300 = datetime.datetime(2026, 8, 25, 13, 0, 0, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_1300) is False

    # Window 2: 17:00 to 21:30
    dt_1659 = datetime.datetime(2026, 8, 25, 16, 59, 59, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_1659) is False

    dt_1700 = datetime.datetime(2026, 8, 25, 17, 0, 0, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_1700) is True

    dt_2129 = datetime.datetime(2026, 8, 25, 21, 29, 59, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_2129) is True

    dt_2130 = datetime.datetime(2026, 8, 25, 21, 30, 0, tzinfo=IST_TZ)
    assert _in_congestion_window(dt_2130) is False
