import datetime
import uuid
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import SessionLocal, get_db
from app.models.transaction import Transaction
from app.models.payment_attempt import PaymentAttempt
from app.models.recovery_decision_record import RecoveryDecisionRecord
from app.services.batch_simulator import get_batch_summary, clear_demo_batch_data

client = TestClient(app)

@pytest.fixture
def db_session():
    db: Session = SessionLocal()
    try:
        clear_demo_batch_data(db, merchant_id="test_demo_batch")
        db.query(RecoveryDecisionRecord).filter(RecoveryDecisionRecord.transaction_id.like("txn_other_%")).delete(synchronize_session=False)
        db.query(Transaction).filter(Transaction.id.like("txn_other_%")).delete(synchronize_session=False)
        db.commit()
        yield db
    finally:
        clear_demo_batch_data(db, merchant_id="test_demo_batch")
        db.query(RecoveryDecisionRecord).filter(RecoveryDecisionRecord.transaction_id.like("txn_other_%")).delete(synchronize_session=False)
        db.query(Transaction).filter(Transaction.id.like("txn_other_%")).delete(synchronize_session=False)
        db.commit()
        db.close()

def test_empty_batch_summary(db_session: Session):
    """
    Requirement 7: Empty batch returns zero-safe values with no division-by-zero.
    """
    summary = get_batch_summary(db_session, merchant_id="test_demo_batch")
    assert summary.total_transactions == 0
    assert summary.total_amount_at_risk == 0.0
    assert summary.total_amount_recovered == 0.0
    assert summary.recovery_rate_by_amount == 0.0
    assert summary.recovery_rate_by_count == 0.0
    assert summary.breakdown_by_bucket["A"].amount_at_risk == 0.0
    assert summary.breakdown_by_bucket["A"].amount_recovered == 0.0
    assert summary.breakdown_by_bucket["B"].amount_at_risk == 0.0
    assert summary.breakdown_by_bucket["B"].amount_recovered == 0.0
    assert summary.breakdown_by_bucket["C"].amount_at_risk == 0.0
    assert summary.breakdown_by_bucket["C"].amount_recovered == 0.0
    assert summary.permanently_failed.amount_at_risk == 0.0
    assert summary.permanently_failed.amount_recovered == 0.0


def test_multi_attempt_transaction_does_not_inflate_revenue(db_session: Session):
    """
    Requirements 1 & 2:
    One ₹5,000 transaction with Attempt 1 fail, Attempt 2 fail, Attempt 3 success:
    Expected: amount_at_risk = ₹5,000, amount_recovered = ₹5,000.
    Must NOT produce ₹15,000 recovered.
    """
    tx = Transaction(
        id="txn_multi_att_test",
        merchant_id="test_demo_batch",
        customer_id="cust_test_1",
        amount=Decimal("5000.00"),
        currency="INR",
        status="recovered"
    )
    db_session.add(tx)

    # 3 payment attempts on the single transaction
    now = datetime.datetime.now(datetime.timezone.utc)
    db_session.add(PaymentAttempt(
        transaction_id="txn_multi_att_test",
        attempt_number=1,
        gateway_used="primary",
        decline_code="timeout",
        attempted_at=now - datetime.timedelta(hours=2),
        succeeded=False
    ))
    db_session.add(PaymentAttempt(
        transaction_id="txn_multi_att_test",
        attempt_number=2,
        gateway_used="primary",
        decline_code="processing_error",
        attempted_at=now - datetime.timedelta(hours=1),
        succeeded=False
    ))
    db_session.add(PaymentAttempt(
        transaction_id="txn_multi_att_test",
        attempt_number=3,
        gateway_used="secondary",
        decline_code=None,
        attempted_at=now,
        succeeded=True
    ))

    # Recovery decision record for Bucket B
    db_session.add(RecoveryDecisionRecord(
        transaction_id="txn_multi_att_test",
        bucket="B",
        classified_by="ml",
        confidence=0.85,
        next_action="execute_strategy",
        status="executed"
    ))
    db_session.commit()

    summary = get_batch_summary(db_session, merchant_id="test_demo_batch")
    assert summary.total_transactions == 1
    assert summary.total_amount_at_risk == 5000.00
    assert summary.total_amount_recovered == 5000.00
    # Explicit check: must NOT produce 15,000
    assert summary.total_amount_recovered != 15000.00
    assert summary.recovery_rate_by_amount == 1.0
    assert summary.recovery_rate_by_count == 1.0
    assert summary.breakdown_by_bucket["B"].amount_at_risk == 5000.00
    assert summary.breakdown_by_bucket["B"].amount_recovered == 5000.00


def test_permanently_failed_terminal_slice(db_session: Session):
    """
    Requirement 3:
    A permanently_failed / retry-cap transaction:
    - counted in amount_at_risk
    - NOT counted in amount_recovered
    - NOT included in Bucket C (kept in separate terminal slice)
    """
    tx = Transaction(
        id="txn_perm_fail_test",
        merchant_id="test_demo_batch",
        customer_id="cust_test_2",
        amount=Decimal("3500.00"),
        currency="INR",
        status="permanently_failed"
    )
    db_session.add(tx)
    db_session.add(RecoveryDecisionRecord(
        transaction_id="txn_perm_fail_test",
        bucket="Unknown",
        classified_by="rules",
        confidence=1.0,
        next_action="terminate_pipeline",
        status="rejected"
    ))
    db_session.commit()

    summary = get_batch_summary(db_session, merchant_id="test_demo_batch")
    assert summary.total_transactions == 1
    assert summary.total_amount_at_risk == 3500.00
    assert summary.total_amount_recovered == 0.00
    assert summary.recovery_rate_by_amount == 0.0
    # Must NOT be in Bucket C
    assert summary.breakdown_by_bucket["C"].amount_at_risk == 0.00
    assert summary.breakdown_by_bucket["C"].amount_recovered == 0.00
    # Must be in permanently_failed terminal slice
    assert summary.permanently_failed.amount_at_risk == 3500.00
    assert summary.permanently_failed.amount_recovered == 0.00


def test_regulatory_blocked_transaction(db_session: Session):
    """
    Requirement 4:
    A regulatory-blocked transaction:
    - counted in amount_at_risk
    - NOT counted in amount_recovered unless a later successful recovery exists
    - classified in Bucket C
    """
    tx = Transaction(
        id="txn_reg_block_test",
        merchant_id="test_demo_batch",
        customer_id="cust_test_3",
        amount=Decimal("18000.00"),
        currency="INR",
        status="regulatory_blocked"
    )
    db_session.add(tx)
    db_session.add(RecoveryDecisionRecord(
        transaction_id="txn_reg_block_test",
        bucket="C",
        classified_by="rules",
        confidence=1.0,
        next_action="terminate_pipeline",
        status="rejected"
    ))
    db_session.commit()

    summary = get_batch_summary(db_session, merchant_id="test_demo_batch")
    assert summary.total_transactions == 1
    assert summary.total_amount_at_risk == 18000.00
    assert summary.total_amount_recovered == 0.00
    assert summary.breakdown_by_bucket["C"].amount_at_risk == 18000.00
    assert summary.breakdown_by_bucket["C"].amount_recovered == 0.00


def test_reconciliation_and_bounds(db_session: Session):
    """
    Requirements 5, 6, 8, 9:
    - Bucket A + Bucket B + Bucket C + permanently_failed == total_amount_at_risk
    - Bucket A recovered + Bucket B recovered + Bucket C recovered == total_amount_recovered
    - amount_recovered <= amount_at_risk
    - Isolation: only test_demo_batch records included, external merchant ignored.
    """
    # 1. Bucket A: recovered ₹2,000 out of ₹3,000
    t1 = Transaction(id="txn_a1", merchant_id="test_demo_batch", customer_id="c1", amount=Decimal("2000.00"), status="recovered")
    t2 = Transaction(id="txn_a2", merchant_id="test_demo_batch", customer_id="c2", amount=Decimal("1000.00"), status="failed")
    db_session.add_all([t1, t2])
    db_session.add_all([
        RecoveryDecisionRecord(transaction_id="txn_a1", bucket="A", classified_by="rules", next_action="execute_strategy", status="executed"),
        RecoveryDecisionRecord(transaction_id="txn_a2", bucket="A", classified_by="rules", next_action="execute_strategy", status="failed")
    ])

    # 2. Bucket B: recovered ₹4,000 out of ₹4,000
    t3 = Transaction(id="txn_b1", merchant_id="test_demo_batch", customer_id="c3", amount=Decimal("4000.00"), status="recovered")
    db_session.add(t3)
    db_session.add(RecoveryDecisionRecord(transaction_id="txn_b1", bucket="B", classified_by="ml", next_action="execute_strategy", status="executed"))

    # 3. Bucket C: recovered ₹1,500 out of ₹2,500 (e.g. rescheduled window recovered)
    t4 = Transaction(id="txn_c1", merchant_id="test_demo_batch", customer_id="c4", amount=Decimal("1500.00"), status="recovered")
    t5 = Transaction(id="txn_c2", merchant_id="test_demo_batch", customer_id="c5", amount=Decimal("1000.00"), status="regulatory_blocked")
    db_session.add_all([t4, t5])
    db_session.add_all([
        RecoveryDecisionRecord(transaction_id="txn_c1", bucket="C", classified_by="rules", next_action="execute_strategy", status="executed"),
        RecoveryDecisionRecord(transaction_id="txn_c2", bucket="C", classified_by="rules", next_action="terminate_pipeline", status="rejected")
    ])

    # 4. Permanently Failed: ₹1,200 at risk, 0 recovered
    t6 = Transaction(id="txn_pf1", merchant_id="test_demo_batch", customer_id="c6", amount=Decimal("1200.00"), status="permanently_failed")
    db_session.add(t6)
    db_session.add(RecoveryDecisionRecord(transaction_id="txn_pf1", bucket="Unknown", classified_by="rules", next_action="terminate_pipeline", status="rejected"))

    # 5. External Merchant Record (Isolation test)
    t_other = Transaction(id="txn_other_merchant", merchant_id="merchant_external", customer_id="cx", amount=Decimal("99999.00"), status="recovered")
    db_session.add(t_other)
    db_session.add(RecoveryDecisionRecord(transaction_id="txn_other_merchant", bucket="A", classified_by="rules", next_action="execute_strategy", status="executed"))

    db_session.commit()

    summary = get_batch_summary(db_session, merchant_id="test_demo_batch")

    # Verify Isolation
    assert summary.total_transactions == 6
    assert summary.total_amount_at_risk == 10700.00  # 2000 + 1000 + 4000 + 1500 + 1000 + 1200
    assert summary.total_amount_recovered == 7500.00  # 2000 + 4000 + 1500

    # Bounds check
    assert summary.total_amount_recovered <= summary.total_amount_at_risk

    # Reconciliation checks:
    # 1. Total at risk == A + B + C + permanently_failed
    sum_buckets_at_risk = (
        summary.breakdown_by_bucket["A"].amount_at_risk +
        summary.breakdown_by_bucket["B"].amount_at_risk +
        summary.breakdown_by_bucket["C"].amount_at_risk +
        summary.permanently_failed.amount_at_risk
    )
    assert round(sum_buckets_at_risk, 2) == summary.total_amount_at_risk

    # 2. Total recovered == A + B + C recovered
    sum_buckets_recovered = (
        summary.breakdown_by_bucket["A"].amount_recovered +
        summary.breakdown_by_bucket["B"].amount_recovered +
        summary.breakdown_by_bucket["C"].amount_recovered
    )
    assert round(sum_buckets_recovered, 2) == summary.total_amount_recovered

    # Clean up
    db_session.query(RecoveryDecisionRecord).filter(RecoveryDecisionRecord.transaction_id == "txn_other_merchant").delete(synchronize_session=False)
    db_session.query(Transaction).filter(Transaction.id == "txn_other_merchant").delete(synchronize_session=False)
    db_session.commit()
