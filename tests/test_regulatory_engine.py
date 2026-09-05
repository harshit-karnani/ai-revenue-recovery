import pytest
import datetime
from app.schemas.payment import PaymentEvent
from app.services.regulatory_engine import evaluate_payment, get_next_valid_execution_window
from app.core.regulatory_rules import IST_TZ

def test_predebit_23_hours():
    now = datetime.datetime.now(IST_TZ)
    notif = now - datetime.timedelta(hours=23)
    event = PaymentEvent(
        amount=1000,
        payment_type="card",
        subscription_category="other",
        notification_sent_at=notif,
        scheduled_at=now,
        current_time=now,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    result = evaluate_payment(event)
    assert result.allowed is False
    assert result.failure_code == "missed_predebit_notification"

def test_predebit_23h59m():
    now = datetime.datetime.now(IST_TZ)
    notif = now - datetime.timedelta(hours=23, minutes=59)
    event = PaymentEvent(
        amount=1000,
        payment_type="card",
        subscription_category="other",
        notification_sent_at=notif,
        scheduled_at=now,
        current_time=now,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    result = evaluate_payment(event)
    assert result.allowed is False

def test_predebit_24_hours():
    now = datetime.datetime.now(IST_TZ)
    notif = now - datetime.timedelta(hours=24)
    event = PaymentEvent(
        amount=1000,
        payment_type="card",
        subscription_category="other",
        notification_sent_at=notif,
        scheduled_at=now,
        current_time=now,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    result = evaluate_payment(event)
    assert result.allowed is True

def test_predebit_25_hours():
    now = datetime.datetime.now(IST_TZ)
    notif = now - datetime.timedelta(hours=25)
    event = PaymentEvent(
        amount=1000,
        payment_type="card",
        subscription_category="other",
        notification_sent_at=notif,
        scheduled_at=now,
        current_time=now,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    result = evaluate_payment(event)
    assert result.allowed is True

def test_afa_limits():
    now = datetime.datetime.now(IST_TZ)
    def run_afa(amount, category="other"):
        event = PaymentEvent(
            amount=amount,
            payment_type="card",
            subscription_category=category,
            scheduled_at=now,
            current_time=now,
            attempt_count=1,
            mandate_status="active",
            authentication_status="not_authenticated"
        )
        return evaluate_payment(event)

    # Standard
    assert run_afa(15000).allowed is True
    res = run_afa(15000.01)
    assert res.allowed is False
    assert res.failure_code == "afa_reauth_required"
    assert run_afa(16000).allowed is False

    # Exceptions
    assert run_afa(100000, "insurance_premium").allowed is True
    assert run_afa(100000.01, "insurance_premium").allowed is False
    assert run_afa(100000, "mutual_fund_sip").allowed is True
    assert run_afa(100000, "credit_card_bill").allowed is True

def test_execution_windows():
    def run_window(hour, minute):
        dt = datetime.datetime.now(IST_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
        event = PaymentEvent(
            amount=1000,
            payment_type="upi_autopay",
            subscription_category="other",
            scheduled_at=dt,
            current_time=dt,
            attempt_count=1,
            mandate_status="active",
            authentication_status="not_authenticated"
        )
        return evaluate_payment(event)

    assert run_window(9, 59).allowed is True
    assert run_window(10, 0).allowed is False
    assert run_window(10, 0).failure_code == "execution_window_block"
    assert run_window(12, 59).allowed is False
    assert run_window(13, 0).allowed is True
    assert run_window(16, 59).allowed is True
    assert run_window(17, 0).allowed is False
    assert run_window(21, 29).allowed is False
    assert run_window(21, 30).allowed is True

def test_next_valid_window():
    def get_next(hour, minute):
        dt = datetime.datetime.now(IST_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return get_next_valid_execution_window(dt)

    assert get_next(11, 30).time() == datetime.time(13, 0)
    assert get_next(12, 59).time() == datetime.time(13, 0)
    assert get_next(17, 0).time() == datetime.time(21, 30)
    assert get_next(20, 0).time() == datetime.time(21, 30)

def test_retry_cap():
    now = datetime.datetime.now(IST_TZ)
    def run_retry(count):
        event = PaymentEvent(
            amount=1000,
            payment_type="card",
            subscription_category="other",
            scheduled_at=now,
            current_time=now,
            attempt_count=count,
            mandate_status="active",
            authentication_status="not_authenticated"
        )
        return evaluate_payment(event)

    assert run_retry(1).allowed is True
    assert run_retry(3).allowed is True
    res = run_retry(4)
    assert res.allowed is False
    assert res.failure_code == "permanently_failed"
    assert run_retry(5).allowed is False

def test_priorities():
    dt = datetime.datetime.now(IST_TZ).replace(hour=11, minute=0, second=0, microsecond=0)
    notif = dt - datetime.timedelta(hours=12)
    
    # Priority 1: Retry cap overrides execution window
    event1 = PaymentEvent(
        amount=1000,
        payment_type="upi_autopay",
        subscription_category="other",
        scheduled_at=dt,
        current_time=dt,
        attempt_count=4,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    assert evaluate_payment(event1).failure_code == "permanently_failed"

    # Priority 4: Execution window (only 1 attempt)
    event2 = PaymentEvent(
        amount=1000,
        payment_type="upi_autopay",
        subscription_category="other",
        scheduled_at=dt,
        current_time=dt,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    assert evaluate_payment(event2).failure_code == "execution_window_block"

    # Priority 2: Pre-debit overrides execution window
    event3 = PaymentEvent(
        amount=1000,
        payment_type="upi_autopay",
        subscription_category="other",
        notification_sent_at=notif,
        scheduled_at=dt,
        current_time=dt,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    assert evaluate_payment(event3).failure_code == "missed_predebit_notification"

    # Priority 3: AFA
    event4 = PaymentEvent(
        amount=16000,
        payment_type="upi_autopay",
        subscription_category="ecommerce_subscription",
        scheduled_at=datetime.datetime.now(IST_TZ).replace(hour=14), # valid window
        current_time=datetime.datetime.now(IST_TZ).replace(hour=14),
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    assert evaluate_payment(event4).failure_code == "afa_reauth_required"

def test_priority_predebit_over_afa():
    dt = datetime.datetime.now(IST_TZ).replace(hour=14, minute=0, second=0, microsecond=0)
    notif = dt - datetime.timedelta(hours=23)
    
    event = PaymentEvent(
        amount=16000,
        payment_type="card",
        subscription_category="ecommerce_subscription",
        notification_sent_at=notif,
        scheduled_at=dt,
        current_time=dt,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    result = evaluate_payment(event)
    assert result.allowed is False
    assert result.failure_code == "missed_predebit_notification"
    assert result.bucket == "C"
