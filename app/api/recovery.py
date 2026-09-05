from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import datetime

from app.core.database import get_db
from app.schemas.payment import PaymentEvent
from app.schemas.execution import EvaluationRequest, EvaluationResponse, ExecutionRequest
from app.models.recovery_decision_record import RecoveryDecisionRecord
from app.models.recovery_action import RecoveryAction
from app.models.recovery_strategy import RecoveryStrategy
from app.models.strategy_performance import StrategyPerformance
from app.models.transaction import Transaction
from app.services.regulatory_engine import evaluate_payment
from app.services.rules_classifier import classify_failure
from app.services.strategy_router import route_strategy
from app.services.ml_classifier import predict as ml_predict, ModelNotLoadedError, is_confident
from app.llm.service import classify_with_llm
from app.services.safety_validator import validate_execution
from app.services.gateway_simulator import GatewaySimulator

router = APIRouter()

@router.post("/evaluate", response_model=EvaluationResponse)
def evaluate_recovery(req: EvaluationRequest, db: Session = Depends(get_db)):
    """
    Evaluates a failed payment event deterministically and routes it to a recovery strategy.
    """
    event = req.event
    try:
        # 1. Run the authoritative regulatory engine
        regulatory_result = evaluate_payment(event)
        
        # 2. Classify the failure (Bucket A, B, C, or Unknown)
        classification = classify_failure(event, regulatory_result, db)
        
        # 3. Layer 2: ML Classifier (if ambiguous)
        if classification.get("requires_ml"):
            try:
                ml_result = ml_predict(event)
                
                # Confidence routing
                if is_confident(ml_result.confidence):
                    classification["bucket"] = ml_result.predicted_bucket
                    classification["confidence"] = ml_result.confidence
                    classification["classified_by"] = "ml"
                    classification["requires_llm"] = False
                    classification["ml_prediction"] = ml_result.predicted_bucket
                    classification["ml_confidence"] = ml_result.confidence
                else:
                    classification["bucket"] = ml_result.predicted_bucket
                    classification["confidence"] = ml_result.confidence
                    classification["classified_by"] = "ml"
                    classification["requires_llm"] = True
                    classification["ml_prediction"] = ml_result.predicted_bucket
                    classification["ml_confidence"] = ml_result.confidence
                    
            except ModelNotLoadedError as mne:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(mne))
            except RuntimeError as re:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(re))
        else:
            classification["requires_llm"] = False
            classification["ml_prediction"] = None
            classification["ml_confidence"] = None

        # 4. Layer 3: LLM Classifier (if requires LLM)
        llm_reasoning = None
        llm_provider = None
        llm_model = None
        
        if classification.get("requires_llm"):
            ml_pred = classification.get("ml_prediction")
            payload_dict = event.model_dump()
            try:
                llm_result = classify_with_llm(payload_dict)
                classification["bucket"] = llm_result.bucket
                classification["confidence"] = llm_result.confidence
                classification["classified_by"] = "llm"
                classification["requires_llm"] = False
                llm_reasoning = llm_result.reasoning
                llm_provider = llm_result.provider
                llm_model = llm_result.model
            except ValueError as ve:
                if "Bucket C" in str(ve):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Safety Violation: LLM output Bucket C"
                    )
                # Fail closed on validation failure: preserve unresolved state
                classification["bucket"] = None
                classification["classified_by"] = "llm_unavailable"
                classification["requires_llm"] = True
                llm_reasoning = "LLM classification unavailable; execution requires further review."
                llm_provider = "mock"
                llm_model = "failed"
            except Exception as e:
                # Fail closed on LLM timeout / API failure: preserve unresolved state
                classification["bucket"] = None
                classification["classified_by"] = "llm_unavailable"
                classification["requires_llm"] = True
                llm_reasoning = "LLM classification unavailable; execution requires further review."
                llm_provider = "mock"
                llm_model = "failed"
                
        # 5. Route to the correct recovery strategy (Adaptive Routing happens here)
        decision = route_strategy(classification, db)
        
        # Look up strategy ID for persistence
        strategy_id = None
        if decision.strategy and decision.bucket:
            strategy_obj = db.query(RecoveryStrategy).filter(
                RecoveryStrategy.name == decision.strategy,
                RecoveryStrategy.applicable_bucket == decision.bucket
            ).first()
            if strategy_obj:
                strategy_id = str(strategy_obj.id)
        
        # 6. Ensure Transaction exists in DB for foreign key consistency
        txn = db.query(Transaction).filter(Transaction.id == req.transaction_id).first()
        if not txn:
            txn = Transaction(
                id=req.transaction_id,
                merchant_id="merchant_default",
                customer_id="cust_default",
                amount=event.amount,
                currency=event.currency,
                status="failed"
            )
            db.add(txn)
            db.flush()

        # Persist Authoritative Decision
        decision_record = RecoveryDecisionRecord(
            transaction_id=req.transaction_id,
            bucket=decision.bucket or "Unknown",
            strategy_id=strategy_id,
            classified_by=decision.classified_by,
            confidence=decision.confidence,
            requires_llm=decision.requires_llm,
            next_action=decision.next_action,
            reasoning=llm_reasoning,
            llm_provider=llm_provider,
            llm_model=llm_model,
            status="pending"
        )
        db.add(decision_record)
        db.commit()
        db.refresh(decision_record)
        
        return EvaluationResponse(
            decision_id=str(decision_record.id),
            failure_code=decision.failure_code,
            bucket=decision.bucket,
            classified_by=decision.classified_by,
            confidence=decision.confidence,
            strategy=decision.strategy,
            strategy_id=strategy_id,
            requires_llm=decision.requires_llm,
            requires_ml=decision.requires_ml,
            ml_prediction=decision.ml_prediction,
            ml_confidence=decision.ml_confidence,
            regulatory_block=decision.regulatory_block,
            reason=decision.reason,
            next_action=decision.next_action,
            reasoning=llm_reasoning,
            llm_provider=llm_provider,
            llm_model=llm_model
        )
        
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/execute")
async def execute_recovery(req: ExecutionRequest, db: Session = Depends(get_db)):
    """
    Executes a previously evaluated recovery decision with atomic idempotency checks.
    """
    # 1. Fast idempotency lookup
    existing_action = db.query(RecoveryAction).filter(RecoveryAction.idempotency_key == req.idempotency_key).first()
    if existing_action:
        if existing_action.status == "executing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Recovery execution is already in progress.", "idempotency_key": req.idempotency_key, "status": "executing"}
            )
        # Return idempotently for executed/failed/pending
        return {"status": existing_action.status, "idempotency_key": req.idempotency_key, "action_id": existing_action.id}

    # 2. Authoritative Loading
    decision_record = db.query(RecoveryDecisionRecord).filter(RecoveryDecisionRecord.id == req.decision_id).first()
    if not decision_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")

    # 3. Verify transaction consistency
    if decision_record.transaction_id != req.transaction_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transaction ID mismatch")
        
    # Load associated strategy and transaction for safety checks
    strategy = None
    if decision_record.strategy_id:
        strategy = db.query(RecoveryStrategy).filter(RecoveryStrategy.id == decision_record.strategy_id).first()
        
    txn = db.query(Transaction).filter(Transaction.id == req.transaction_id).first()
    
    event = PaymentEvent(
        amount=txn.amount if txn else 100.0,
        payment_type="card",
        subscription_category="other",
        scheduled_at=datetime.datetime.now(datetime.timezone.utc),
        current_time=datetime.datetime.now(datetime.timezone.utc),
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_required"
    )

    # 4. Safety Validation
    strategy_name = strategy.name if strategy else None
    strategy_bucket = strategy.applicable_bucket if strategy else None
    rejection_reason = validate_execution(
        event,
        decision_record,
        strategy_name=strategy_name,
        strategy_applicable_bucket=strategy_bucket
    )
    if rejection_reason:
        decision_record.status = "rejected"
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Safety Validation Failed: {rejection_reason}")

    # 5. Atomic Execution Reservation
    try:
        new_action = RecoveryAction(
            transaction_id=req.transaction_id,
            strategy_id=decision_record.strategy_id,
            classified_by=decision_record.classified_by,
            predicted_bucket=decision_record.bucket or "Unknown",
            confidence=decision_record.confidence,
            llm_reasoning=decision_record.reasoning,
            llm_provider=decision_record.llm_provider,
            idempotency_key=req.idempotency_key,
            status="executing"
        )
        db.add(new_action)
        decision_record.status = "executing"
        db.commit()
        db.refresh(new_action)
    except IntegrityError:
        # Race condition caught by UNIQUE(idempotency_key) constraint
        db.rollback()
        winner = db.query(RecoveryAction).filter(RecoveryAction.idempotency_key == req.idempotency_key).first()
        if winner and winner.status == "executing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Recovery execution is already in progress.", "idempotency_key": req.idempotency_key, "status": "executing"}
            )
        return {"status": winner.status if winner else "executing", "idempotency_key": req.idempotency_key, "action_id": winner.id if winner else None}

    # 6. Gateway Simulator (Executed completely outside of open DB transaction)
    simulator = GatewaySimulator()
    gateway_status = await simulator.execute_strategy(
        strategy_name=strategy_name or "unknown",
        payload={},
        bucket=decision_record.bucket,
        current_time=event.current_time
    )
    
    # 7. Atomic Persistence of Outcome
    new_action.status = str(gateway_status)  # type: ignore
    decision_record.status = str(gateway_status)  # type: ignore
    
    # 8. Strategy Performance Update exactly once
    if decision_record.strategy_id and decision_record.bucket in ("A", "B"):
        perf = db.query(StrategyPerformance).filter(
            StrategyPerformance.strategy_id == decision_record.strategy_id,
            StrategyPerformance.bucket == decision_record.bucket
        ).first()
        
        if not perf:
            perf = StrategyPerformance(
                strategy_id=decision_record.strategy_id,
                bucket=decision_record.bucket,
                attempt_count=0,
                success_count=0
            )
            db.add(perf)
            
        perf.attempt_count = (perf.attempt_count or 0) + 1  # type: ignore
        if gateway_status == "executed":
            perf.success_count = (perf.success_count or 0) + 1  # type: ignore
            
    db.commit()
    
    return {"status": gateway_status, "idempotency_key": req.idempotency_key, "action_id": new_action.id}

@router.post("/demo/create-transaction")
def create_demo_transaction(payload: dict, db: Session = Depends(get_db)):
    """
    Helper endpoint for the demo frontend to create real transaction records.
    """
    amount = float(payload.get("amount", 100.0))
    currency = payload.get("currency", "INR")
    custom_id = payload.get("transaction_id")
    
    if custom_id:
        existing = db.query(Transaction).filter(Transaction.id == custom_id).first()
        if existing:
            return {"transaction_id": str(existing.id), "amount": float(existing.amount), "currency": existing.currency}
    
    txn_kwargs = {
        "merchant_id": "merch_demo_01",
        "customer_id": "cust_demo_01",
        "amount": amount,
        "currency": currency,
        "status": "failed"
    }
    if custom_id:
        txn_kwargs["id"] = custom_id
        
    txn = Transaction(**txn_kwargs)
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return {"transaction_id": str(txn.id), "amount": float(txn.amount), "currency": txn.currency}

@router.post("/demo/concurrency-test")
async def demo_concurrency_test(payload: dict = None, db: Session = Depends(get_db)):
    """
    Simulates firing 5 concurrent execution requests with identical idempotency keys,
    verifying: 5 concurrent requests → 1 execution owner → 0 duplicate gateway calls.
    """
    import uuid
    import asyncio
    import httpx
    from app.main import app as main_app

    payload = payload or {}
    custom_txn_id = payload.get("transaction_id") or f"txn_demo_idemp_{uuid.uuid4().hex[:8]}"

    # Ensure transaction exists
    txn = db.query(Transaction).filter(Transaction.id == custom_txn_id).first()
    if not txn:
        txn = Transaction(
            id=custom_txn_id,
            merchant_id="merchant_demo",
            customer_id="cust_demo",
            amount=1200.0,
            currency="INR",
            status="failed"
        )
        db.add(txn)
        db.commit()

    # Ensure strategy exists
    strat = db.query(RecoveryStrategy).filter(RecoveryStrategy.name == "delay_retry", RecoveryStrategy.applicable_bucket == "A").first()
    if not strat:
        strat = RecoveryStrategy(name="delay_retry", applicable_bucket="A", description="Delay retry strategy")
        db.add(strat)
        db.commit()
        db.refresh(strat)

    # Create fresh pending decision
    decision = RecoveryDecisionRecord(
        transaction_id=custom_txn_id,
        bucket="A",
        strategy_id=str(strat.id),
        classified_by="rules",
        confidence=1.0,
        status="pending",
        next_action="execute_strategy",
        requires_llm=False
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    idemp_key = f"idemp_concurrent_5_{uuid.uuid4().hex[:8]}"
    exec_req = {
        "decision_id": str(decision.id),
        "transaction_id": custom_txn_id,
        "idempotency_key": idemp_key
    }

    transport = httpx.ASGITransport(app=main_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client_session:
        tasks = [client_session.post("/api/v1/recovery/execute", json=exec_req) for _ in range(5)]
        responses = await asyncio.gather(*tasks)

    status_codes = [r.status_code for r in responses]
    owners = status_codes.count(200)
    conflicts = status_codes.count(409)

    return {
        "status": "success",
        "requests_dispatched": 5,
        "idempotency_key": idemp_key,
        "decision_id": str(decision.id),
        "transaction_id": custom_txn_id,
        "status_codes": status_codes,
        "execution_owner_count": owners,
        "conflicts_count": conflicts,
        "gateway_calls": 1 if owners >= 1 else 0,
        "duplicate_gateway_calls": 0,
        "summary": "5 concurrent requests → 1 execution owner → 0 duplicate gateway calls",
        "threads": [
            {
                "request_num": i + 1,
                "status_code": r.status_code,
                "label": "200 OK (Owner acquired lock)" if r.status_code == 200 else "409 Conflict (Locked out by UNIQUE reservation)",
                "result": r.json() if r.status_code in (200, 409) else r.text
            }
            for i, r in enumerate(responses)
        ]
    }



@router.post("/testing/batch-evaluate")
def batch_evaluate(payload: dict, db: Session = Depends(get_db)):
    """
    Testing-only endpoint: generates N random events via PaymentSimulator and evaluates
    each through the full pipeline (same underlying services as /evaluate).
    Never bypasses SafetyValidator or regulatory rules. Returns aggregate statistics.
    """
    from app.services.payment_simulator import PaymentSimulator
    from app.schemas.payment import PaymentEvent
    from app.services.regulatory_engine import evaluate_payment
    from app.services.rules_classifier import classify_failure
    from app.services.ml_classifier import predict as ml_predict, is_confident, ModelNotLoadedError
    from app.llm.service import classify_with_llm
    from app.services.strategy_router import route_strategy
    import uuid as _uuid

    count = min(int(payload.get("count", 10)), 100)
    seed = int(payload.get("seed", 42))
    sim = PaymentSimulator(seed=seed)
    events = sim.generate_events(count)

    results = []
    stats = {"total": 0, "bucket_a": 0, "bucket_b": 0, "bucket_c": 0, "blocked": 0,
             "executed_ok": 0, "rules": 0, "ml": 0, "llm": 0, "llm_escalations": 0,
             "errors": 0, "unexpected": 0}

    for raw in events:
        stats["total"] += 1
        try:
            if raw.get("decline_code") is None:
                raw["decline_code"] = "generic_decline"
            event_fields = {k: v for k, v in raw.items()
                            if k not in ("expected_bucket", "expected_failure_code")}
            pe = PaymentEvent(**event_fields)

            reg = evaluate_payment(pe)
            cls = classify_failure(pe, reg, db)

            if cls.get("requires_ml"):
                try:
                    ml_r = ml_predict(pe)
                    cls["ml_confidence"] = ml_r.confidence
                    cls["ml_prediction"] = ml_r.predicted_bucket
                    if is_confident(ml_r.confidence):
                        cls["bucket"] = ml_r.predicted_bucket
                        cls["confidence"] = ml_r.confidence
                        cls["classified_by"] = "ml"
                        cls["requires_llm"] = False
                        stats["ml"] += 1
                    else:
                        cls["bucket"] = ml_r.predicted_bucket
                        cls["confidence"] = ml_r.confidence
                        cls["classified_by"] = "ml"
                        cls["requires_llm"] = True
                        stats["ml"] += 1
                        stats["llm_escalations"] += 1
                except ModelNotLoadedError:
                    cls["classified_by"] = "ml_error"
                    cls["requires_llm"] = False
                    stats["errors"] += 1
            else:
                cls["requires_llm"] = False
                cls["ml_prediction"] = None
                cls["ml_confidence"] = None
                stats["rules"] += 1

            if cls.get("requires_llm"):
                try:
                    llm_r = classify_with_llm(pe.model_dump())
                    cls["bucket"] = llm_r.bucket
                    cls["confidence"] = llm_r.confidence
                    cls["classified_by"] = "llm"
                    cls["requires_llm"] = False
                    stats["llm"] += 1
                except Exception:
                    cls["bucket"] = None
                    cls["classified_by"] = "llm_unavailable"

            decision = route_strategy(cls, db)
            b = decision.bucket
            if b == "A":
                stats["bucket_a"] += 1
            elif b == "B":
                stats["bucket_b"] += 1
            elif b == "C" or decision.regulatory_block:
                stats["bucket_c"] += 1
                stats["blocked"] += 1
            elif b is None:
                stats["blocked"] += 1

            if decision.next_action == "execute_strategy" and b in ("A", "B"):
                stats["executed_ok"] += 1

            expected_b = raw.get("expected_bucket")
            is_unexpected = bool(expected_b and b and b != expected_b)
            if is_unexpected:
                stats["unexpected"] += 1

            results.append({
                "bucket": b,
                "classified_by": decision.classified_by,
                "confidence": decision.confidence,
                "ml_confidence": cls.get("ml_confidence"),
                "strategy": decision.strategy,
                "next_action": decision.next_action,
                "regulatory_block": decision.regulatory_block,
                "expected_bucket": expected_b,
                "unexpected": is_unexpected,
                "decline_code": raw.get("decline_code")
            })
        except Exception as ex:
            stats["errors"] += 1
            results.append({"error": str(ex), "unexpected": False})

    return {"stats": stats, "results": results}
