import datetime
import random
from typing import Dict, Any, List, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, case

from app.models.transaction import Transaction
from app.models.payment_attempt import PaymentAttempt
from app.models.recovery_decision_record import RecoveryDecisionRecord
from app.models.recovery_action import RecoveryAction
from app.models.recovery_strategy import RecoveryStrategy
from app.schemas.payment import PaymentEvent
from app.schemas.dashboard import BatchSummaryResponse, BucketSummary
from app.core.regulatory_rules import IST_TZ
from app.services.regulatory_engine import evaluate_payment
from app.services.rules_classifier import classify_failure
from app.services.ml_classifier import predict as ml_predict, is_confident
from app.services.strategy_router import route_strategy
from app.services.safety_validator import validate_execution
from app.services.gateway_simulator import GatewaySimulator
from app.llm.mock_provider import MockProvider


def get_batch_summary(db: Session, merchant_id: str = "demo_batch") -> BatchSummaryResponse:
    """
    Computes real database-side aggregation of revenue recovery metrics for a batch of transactions.
    Ensures each unique transaction is counted once. Retries cannot inflate recovered revenue.
    """
    # 1. Database-side headline aggregation
    headline = db.query(
        func.count(distinct(Transaction.id)).label("total_transactions"),
        func.coalesce(func.sum(Transaction.amount), 0).label("total_amount_at_risk"),
        func.coalesce(
            func.sum(
                case(
                    (Transaction.status == "recovered", Transaction.amount),
                    else_=0
                )
            ),
            0
        ).label("total_amount_recovered"),
        func.count(
            distinct(
                case(
                    (Transaction.status == "recovered", Transaction.id),
                    else_=None
                )
            )
        ).label("recovered_count")
    ).filter(Transaction.merchant_id == merchant_id).one()

    total_transactions = int(headline.total_transactions or 0)
    total_amount_at_risk = round(float(headline.total_amount_at_risk or 0.0), 2)
    total_amount_recovered = round(float(headline.total_amount_recovered or 0.0), 2)
    recovered_count = int(headline.recovered_count or 0)

    # Zero-safe rate calculations
    recovery_rate_by_amount = (
        round(total_amount_recovered / total_amount_at_risk, 4)
        if total_amount_at_risk > 0 else 0.0
    )
    recovery_rate_by_count = (
        round(recovered_count / total_transactions, 4)
        if total_transactions > 0 else 0.0
    )

    # 2. Database-side breakdown by bucket (A, B, C, and terminal permanently_failed)
    # Join Transaction with primary RecoveryDecisionRecord
    bucket_rows = (
        db.query(
            RecoveryDecisionRecord.bucket,
            func.coalesce(func.sum(Transaction.amount), 0).label("amount_at_risk"),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.status == "recovered", Transaction.amount),
                        else_=0
                    )
                ),
                0
            ).label("amount_recovered")
        )
        .join(RecoveryDecisionRecord, Transaction.id == RecoveryDecisionRecord.transaction_id)
        .filter(Transaction.merchant_id == merchant_id)
        .group_by(RecoveryDecisionRecord.bucket)
        .all()
    )

    breakdown_by_bucket: Dict[str, BucketSummary] = {
        "A": BucketSummary(amount_at_risk=0.0, amount_recovered=0.0),
        "B": BucketSummary(amount_at_risk=0.0, amount_recovered=0.0),
        "C": BucketSummary(amount_at_risk=0.0, amount_recovered=0.0)
    }
    perm_failed_summary = BucketSummary(amount_at_risk=0.0, amount_recovered=0.0)

    for row in bucket_rows:
        b_key = row.bucket
        at_risk = round(float(row.amount_at_risk or 0.0), 2)
        recovered = round(float(row.amount_recovered or 0.0), 2)

        if b_key in ("A", "B", "C"):
            breakdown_by_bucket[b_key] = BucketSummary(
                amount_at_risk=at_risk,
                amount_recovered=recovered
            )
        else:
            # retry-cap / attempt=4 / permanently_failed slice
            perm_failed_summary = BucketSummary(
                amount_at_risk=round(perm_failed_summary.amount_at_risk + at_risk, 2),
                amount_recovered=0.0
            )

    return BatchSummaryResponse(
        total_transactions=total_transactions,
        total_amount_at_risk=total_amount_at_risk,
        total_amount_recovered=total_amount_recovered,
        recovery_rate_by_amount=recovery_rate_by_amount,
        recovery_rate_by_count=recovery_rate_by_count,
        breakdown_by_bucket=breakdown_by_bucket,
        permanently_failed=perm_failed_summary,
        currency="INR"
    )


def clear_demo_batch_data(db: Session, merchant_id: str = "demo_batch") -> int:
    """
    Safely deletes ONLY demo_batch records from the database.
    Never touches real or non-demo transactions.
    """
    demo_txns = db.query(Transaction.id).filter(Transaction.merchant_id == merchant_id).all()
    txn_ids = [t[0] for t in demo_txns]
    if not txn_ids:
        return 0

    # Delete child records in correct foreign key order
    db.query(PaymentAttempt).filter(PaymentAttempt.transaction_id.in_(txn_ids)).delete(synchronize_session=False)
    db.query(RecoveryAction).filter(RecoveryAction.transaction_id.in_(txn_ids)).delete(synchronize_session=False)
    db.query(RecoveryDecisionRecord).filter(RecoveryDecisionRecord.transaction_id.in_(txn_ids)).delete(synchronize_session=False)
    count = db.query(Transaction).filter(Transaction.id.in_(txn_ids)).delete(synchronize_session=False)
    db.commit()
    return count


async def run_150_batch_simulation(db: Session, seed: int = 42) -> BatchSummaryResponse:
    """
    Executes a 150-transaction safe demo simulation through the real Recovery Engine.
    Uses GatewaySimulator and MockLLM (zero real gateway calls, zero Gemini quota consumed).
    Exercises:
      - 55 Bucket A (Customer-Side)
      - 55 Bucket B (Bank & Network / Ambiguity) with multi-attempt recovery proof
      - 25 Bucket C (India Regulatory Guardrails)
      - 15 Permanently Failed / Terminal Retry Cap (attempt = 4)
    """
    # 1. Clean previous demo batch data strictly isolated to demo_batch
    clear_demo_batch_data(db, merchant_id="demo_batch")

    rng = random.Random(seed)
    gateway_sim = GatewaySimulator(seed=seed)
    mock_llm = MockProvider()

    now = datetime.datetime.now(IST_TZ)
    # Reference valid times
    valid_notif = now - datetime.timedelta(hours=25)
    valid_exec = now.replace(hour=14, minute=0, second=0, microsecond=0)

    # 150 Planned Scenarios
    # Category 1: 55 Bucket A cases
    # Category 2: 55 Bucket B cases (including 10 multi-attempt cases)
    # Category 3: 25 Bucket C cases (including reschedule and reauth cases)
    # Category 4: 15 Terminal cases (attempt_count = 4)
    scenarios: List[Dict[str, Any]] = []

    # 1. Bucket A: 55 cases (Insufficient funds, expired card)
    for i in range(1, 56):
        if i <= 35:
            code = "insufficient_funds"
            amt = round(rng.uniform(300, 7500), 2)
        else:
            code = "expired_card"
            amt = round(rng.uniform(250, 4500), 2)
        scenarios.append({
            "code": code,
            "amount": amt,
            "payment_type": "card",
            "category": "ecommerce_subscription",
            "attempt_count": rng.choice([1, 2]),
            "notif_time": valid_notif,
            "exec_time": valid_exec,
            "is_multi_attempt": False
        })

    # 2. Bucket B: 55 cases (Network timeouts, generic decline, processing errors)
    for i in range(1, 56):
        if i <= 25:
            code = "generic_decline"
            amt = round(rng.uniform(600, 8500), 2)
        elif i <= 45:
            code = "timeout"
            amt = round(rng.uniform(500, 6000), 2)
        else:
            code = "processing_error"
            amt = round(rng.uniform(400, 5000), 2)

        # 10 cases configured as multi-attempt recovery demonstration
        is_multi = (i <= 10)
        scenarios.append({
            "code": code,
            "amount": amt,
            "payment_type": rng.choice(["card", "upi_autopay"]),
            "category": "other",
            "attempt_count": 2 if is_multi else 1,
            "notif_time": valid_notif,
            "exec_time": valid_exec,
            "is_multi_attempt": is_multi
        })

    # 3. Bucket C: 25 Regulatory cases
    for i in range(1, 26):
        if i <= 10:
            # Missed pre-debit notice (12h elapsed < 24h) -> hard regulatory block
            scenarios.append({
                "code": "insufficient_funds",
                "amount": round(rng.uniform(500, 4000), 2),
                "payment_type": "card",
                "category": "ecommerce_subscription",
                "attempt_count": 1,
                "notif_time": now - datetime.timedelta(hours=12),
                "exec_time": valid_exec,
                "is_multi_attempt": False
            })
        elif i <= 18:
            # Restricted execution window (11:00 IST) -> eligible for reschedule_valid_window
            blocked_time = now.replace(hour=11, minute=15, second=0, microsecond=0)
            scenarios.append({
                "code": "generic_decline",
                "amount": round(rng.uniform(400, 3500), 2),
                "payment_type": "upi_autopay",
                "category": "ecommerce_subscription",
                "attempt_count": 1,
                "notif_time": valid_notif,
                "exec_time": blocked_time,
                "is_multi_attempt": False
            })
        else:
            # AFA limit exceeded (>15,000 INR for ecommerce) -> eligible for trigger_reauthentication_link
            scenarios.append({
                "code": "insufficient_funds",
                "amount": round(rng.uniform(15500, 28000), 2),
                "payment_type": "card",
                "category": "ecommerce_subscription",
                "attempt_count": 1,
                "notif_time": valid_notif,
                "exec_time": valid_exec,
                "is_multi_attempt": False
            })

    # 4. Terminal Slice: 15 cases (Retry cap attempt = 4)
    for i in range(1, 16):
        scenarios.append({
            "code": "insufficient_funds",
            "amount": round(rng.uniform(700, 6000), 2),
            "payment_type": "card",
            "category": "ecommerce_subscription",
            "attempt_count": 4, # Exceeds retry cap
            "notif_time": valid_notif,
            "exec_time": valid_exec,
            "is_multi_attempt": False
        })

    # Process all 150 scenarios through the Recovery Engine
    for idx, sc in enumerate(scenarios, start=1):
        tx_id = f"txn_batch_{idx:03d}"
        amount = Decimal(str(sc["amount"]))

        # 1. Insert Transaction record
        txn = Transaction(
            id=tx_id,
            merchant_id="demo_batch",
            customer_id=f"cust_sim_{idx:03d}",
            amount=amount,
            currency="INR",
            status="failed"
        )
        db.add(txn)
        db.flush()

        # 2. Build PaymentEvent
        event = PaymentEvent(
            amount=float(sc["amount"]),
            currency="INR",
            payment_type=sc["payment_type"],
            subscription_category=sc["category"],
            decline_code=sc["code"],
            attempt_count=sc["attempt_count"],
            mandate_status="active",
            authentication_status="not_authenticated",
            notification_sent_at=sc["notif_time"],
            scheduled_at=sc["exec_time"],
            current_time=sc["exec_time"]
        )

        # 3. Layer 1: Regulatory Engine
        reg_result = evaluate_payment(event)

        # 4. Layer 2a: Rules Taxonomy Classification
        classification = classify_failure(event, reg_result, db)

        # 5. Layer 2b: ML Classifier (if ambiguous)
        if classification.get("requires_ml"):
            try:
                ml_res = ml_predict(event)
                if is_confident(ml_res.confidence):
                    classification["bucket"] = ml_res.predicted_bucket
                    classification["confidence"] = ml_res.confidence
                    classification["classified_by"] = "ml"
                    classification["requires_llm"] = False
                else:
                    classification["bucket"] = ml_res.predicted_bucket
                    classification["confidence"] = ml_res.confidence
                    classification["classified_by"] = "ml"
                    classification["requires_llm"] = True
            except Exception:
                pass

        # 6. Layer 3: Mock LLM Disambiguation (zero external API calls)
        llm_reasoning = None
        if classification.get("requires_llm"):
            llm_res = mock_llm.classify(event.model_dump())
            classification["bucket"] = llm_res.bucket
            classification["confidence"] = llm_res.confidence
            classification["classified_by"] = "llm"
            classification["requires_llm"] = False
            llm_reasoning = llm_res.reasoning

        # 7. Layer 4: Strategy Router
        decision = route_strategy(classification, db)

        # Find strategy_id
        strat_obj = None
        if decision.strategy and decision.bucket:
            strat_obj = db.query(RecoveryStrategy).filter(
                RecoveryStrategy.name == decision.strategy,
                RecoveryStrategy.applicable_bucket == decision.bucket
            ).first()

        # 8. Persist RecoveryDecisionRecord
        # Note: If permanently_failed (retry cap), decision.bucket is None -> recorded as 'Unknown'
        dec_bucket = decision.bucket or "Unknown"
        decision_record = RecoveryDecisionRecord(
            transaction_id=tx_id,
            bucket=dec_bucket,
            strategy_id=str(strat_obj.id) if strat_obj else None,
            classified_by=decision.classified_by,
            confidence=decision.confidence,
            requires_llm=decision.requires_llm,
            next_action=decision.next_action,
            reasoning=llm_reasoning,
            llm_provider="mock",
            llm_model="mock-deterministic",
            status="pending"
        )
        db.add(decision_record)
        db.flush()

        # Handle Terminal State (attempt_count = 4)
        if classification.get("failure_code") == "permanently_failed":
            txn.status = "permanently_failed"
            decision_record.status = "rejected"
            db.add(PaymentAttempt(
                transaction_id=tx_id,
                attempt_number=4,
                gateway_used="razorpay_mock",
                decline_code="retry_cap_exceeded",
                attempted_at=sc["exec_time"],
                succeeded=False
            ))
            continue

        # Handle Regulatory Block (e.g. missed pre-debit notice)
        if decision.regulatory_block and not strat_obj:
            txn.status = "regulatory_blocked"
            decision_record.status = "rejected"
            db.add(PaymentAttempt(
                transaction_id=tx_id,
                attempt_number=sc["attempt_count"],
                gateway_used="razorpay_mock",
                decline_code=reg_result.failure_code or "regulatory_block",
                attempted_at=sc["exec_time"],
                succeeded=False
            ))
            continue

        # 9. Safety Validation (Layer 4b)
        strategy_name = decision.strategy
        strategy_bucket = decision.bucket
        rejection_reason = validate_execution(
            event,
            decision_record,
            strategy_name=strategy_name,
            strategy_applicable_bucket=strategy_bucket
        )

        if rejection_reason:
            decision_record.status = "rejected"
            txn.status = "safety_rejected"
            db.add(PaymentAttempt(
                transaction_id=tx_id,
                attempt_number=sc["attempt_count"],
                gateway_used="razorpay_mock",
                decline_code=rejection_reason,
                attempted_at=sc["exec_time"],
                succeeded=False
            ))
            continue

        # 10. Gateway Simulator Execution (Layer 4c)
        gateway_status = await gateway_sim.execute_strategy(
            strategy_name=strategy_name or "unknown",
            payload={},
            bucket=decision.bucket,
            current_time=sc["exec_time"]
        )

        # 11. Create RecoveryAction
        action = RecoveryAction(
            transaction_id=tx_id,
            strategy_id=str(strat_obj.id) if strat_obj else "strat_sim",
            classified_by=decision.classified_by,
            predicted_bucket=dec_bucket,
            confidence=decision.confidence,
            llm_reasoning=llm_reasoning,
            llm_provider="mock",
            idempotency_key=f"idemp_batch_{idx}_{tx_id}",
            status=gateway_status
        )
        db.add(action)

        decision_record.status = gateway_status

        # Multi-attempt showcase: insert prior failed attempts for transactions 1-10
        if sc.get("is_multi_attempt"):
            # Attempt 1: Failed
            db.add(PaymentAttempt(
                transaction_id=tx_id,
                attempt_number=1,
                gateway_used="primary_gateway",
                decline_code=sc["code"],
                attempted_at=sc["exec_time"] - datetime.timedelta(hours=2),
                succeeded=False
            ))
            # Attempt 2: Final outcome from recovery
            final_succ = (gateway_status == "executed")
            db.add(PaymentAttempt(
                transaction_id=tx_id,
                attempt_number=2,
                gateway_used="secondary_gateway",
                decline_code=None if final_succ else "retry_failed",
                attempted_at=sc["exec_time"],
                succeeded=final_succ
            ))
            if final_succ:
                txn.status = "recovered"
            else:
                txn.status = "failed"
        else:
            if gateway_status == "executed":
                txn.status = "recovered"
                db.add(PaymentAttempt(
                    transaction_id=tx_id,
                    attempt_number=sc["attempt_count"],
                    gateway_used="primary_gateway",
                    decline_code=None,
                    attempted_at=sc["exec_time"],
                    succeeded=True
                ))
            else:
                txn.status = "failed"
                db.add(PaymentAttempt(
                    transaction_id=tx_id,
                    attempt_number=sc["attempt_count"],
                    gateway_used="primary_gateway",
                    decline_code=sc["code"],
                    attempted_at=sc["exec_time"],
                    succeeded=False
                ))

    # Commit all 150 transactions and outcomes
    db.commit()

    # 12. Return database-aggregated batch summary
    return get_batch_summary(db, merchant_id="demo_batch")
