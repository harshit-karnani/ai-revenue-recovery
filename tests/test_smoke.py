import datetime
from app.models.transaction import Transaction
from app.models.payment_attempt import PaymentAttempt
from app.models.recovery_action import RecoveryAction
from app.schemas.payment import PaymentEvent
from app.services.regulatory_engine import evaluate_payment
from app.core.regulatory_rules import IST_TZ

def test_smoke_database_flow(db_session):
    # 1. Create transaction
    txn = Transaction(
        merchant_id="merch_123",
        customer_id="cust_456",
        amount=20000,
        currency="INR",
        status="failed"
    )
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)

    # 3. Create payment attempt
    attempt = PaymentAttempt(
        transaction_id=txn.id,
        attempt_number=1,
        gateway_used="razorpay",
        decline_code="generic_decline",
        attempted_at=datetime.datetime.now(datetime.timezone.utc),
        succeeded=False
    )
    db_session.add(attempt)
    db_session.commit()

    # 5. Run regulatory evaluation
    now = datetime.datetime.now(IST_TZ)
    event = PaymentEvent(
        amount=20000,
        currency="INR",
        payment_type="card",
        subscription_category="ecommerce",
        scheduled_at=now,
        current_time=now,
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated"
    )
    result = evaluate_payment(event)
    assert result.allowed is False
    assert result.failure_code == "afa_reauth_required"

    # 6. Create recovery action
    # We fake a strategy_id for test since we didn't seed sqlite db
    action = RecoveryAction(
        transaction_id=txn.id,
        strategy_id="123",
        classified_by="rules",
        predicted_bucket="C",
        status="executed"
    )
    db_session.add(action)
    db_session.commit()

    # 8. Query transaction back
    queried_txn = db_session.query(Transaction).filter(Transaction.id == txn.id).first()
    
    # 9. Verify
    assert queried_txn is not None
    assert queried_txn.amount == 20000
    assert len(queried_txn.payment_attempts) == 1
    assert queried_txn.payment_attempts[0].decline_code == "generic_decline"
    assert len(queried_txn.recovery_actions) == 1
    assert queried_txn.recovery_actions[0].predicted_bucket == "C"
