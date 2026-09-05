import pytest
import datetime
import asyncio
import httpx
import zoneinfo
from unittest import mock
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.core.database import SessionLocal
from app.core.regulatory_rules import IST_TZ
from app.schemas.payment import PaymentEvent
from app.models.transaction import Transaction
from app.models.recovery_strategy import RecoveryStrategy
from app.models.recovery_decision_record import RecoveryDecisionRecord
from app.models.recovery_action import RecoveryAction
from app.models.strategy_performance import StrategyPerformance
from app.services.safety_validator import (
    validate_execution,
    SAFETY_RETRY_CAP_EXCEEDED,
    SAFETY_BUCKET_C_FORBIDDEN,
    SAFETY_INVALID_STRATEGY,
    SAFETY_STRATEGY_UNAUTHORIZED,
    SAFETY_MORNING_WINDOW_BLOCKED,
    SAFETY_EVENING_WINDOW_BLOCKED,
    SAFETY_DUPLICATE_EXECUTION,
    SAFETY_INVALID_AMOUNT,
    SAFETY_UNRESOLVED_STATE,
    SAFETY_INVALID_STATUS,
    SAFETY_PREDEBIT_BLIND_RETRY_FORBIDDEN,
    SAFETY_AFA_BLIND_RETRY_FORBIDDEN,
    SAFETY_MANDATE_INACTIVE
)
from app.services.gateway_simulator import GatewaySimulator
from app.services.strategy_router import get_best_strategy
from app.llm.service import classify_with_llm, get_llm_provider
from app.llm.mock_provider import MockProvider

client = TestClient(app)

def setup_clean_db():
    db = SessionLocal()
    db.execute(text("DELETE FROM recovery_actions"))
    db.execute(text("DELETE FROM recovery_decisions"))
    db.execute(text("DELETE FROM strategy_performance"))
    db.commit()
    return db

# =====================================================================
# 1. SAFETY VALIDATOR: ALL 12 INVARIANTS TESTED
# =====================================================================

def test_safety_validator_12_invariants():
    # Base safe decision & event
    decision = RecoveryDecisionRecord(
        transaction_id="tx_safe",
        bucket="B",
        strategy_id="strat_uuid_123",
        classified_by="llm",
        status="pending",
        next_action="execute_strategy",
        requires_llm=False
    )
    event = PaymentEvent(
        amount=100.0,
        payment_type="card",
        subscription_category="other",
        scheduled_at=datetime.datetime.now(datetime.timezone.utc),
        current_time=datetime.datetime.now(datetime.timezone.utc),
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_required"
    )

    # Invariant 0: Baseline Safe
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") is None

    # Invariant 1: Permanently failed / retry cap exceeded
    event.attempt_count = 4
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_RETRY_CAP_EXCEEDED
    event.attempt_count = 1

    # Invariant 2: Bucket C forbidden from gateway execution
    decision.bucket = "C"
    assert validate_execution(event, decision, strategy_name="delay_retry", strategy_applicable_bucket="C") == SAFETY_BUCKET_C_FORBIDDEN
    decision.bucket = "B"

    # Invariant 3: Unknown / missing strategy
    decision.strategy_id = None
    assert validate_execution(event, decision, strategy_name=None, strategy_applicable_bucket=None) == SAFETY_INVALID_STRATEGY
    decision.strategy_id = "strat_uuid_123"

    # Invariant 4: Non-positive amount
    event.amount = 0
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_INVALID_AMOUNT
    event.amount = 100.0

    # Invariant 5: Duplicate execution (already executing / executed)
    decision.status = "executing"
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_DUPLICATE_EXECUTION
    decision.status = "executed"
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_DUPLICATE_EXECUTION
    decision.status = "pending"

    # Invariant 6: Unresolved LLM state
    decision.requires_llm = True
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_UNRESOLVED_STATE
    decision.requires_llm = False

    # Invariant 7: Strategy unauthorized for bucket
    assert validate_execution(event, decision, strategy_name="delay_retry", strategy_applicable_bucket="A") == SAFETY_STRATEGY_UNAUTHORIZED

    # Invariant 8: Morning execution-window block (10:00 - 13:00 IST for UPI)
    event.payment_type = "upi_autopay"
    event.current_time = datetime.datetime.now(IST_TZ).replace(hour=11, minute=0, second=0)
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_MORNING_WINDOW_BLOCKED

    # Invariant 9: Evening execution-window block (17:00 - 21:30 IST for UPI)
    event.current_time = datetime.datetime.now(IST_TZ).replace(hour=18, minute=0, second=0)
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_EVENING_WINDOW_BLOCKED
    event.payment_type = "card"

    # Invariant 10: Pre-debit blind retry without delay_retry
    now = datetime.datetime.now(IST_TZ)
    event.current_time = now
    event.notification_sent_at = now - datetime.timedelta(hours=10) # < 24h
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_PREDEBIT_BLIND_RETRY_FORBIDDEN
    event.notification_sent_at = None

    # Invariant 11: AFA blind retry without trigger_reauthentication_link
    event.amount = 20000.0 # > 15000 AFA limit
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_AFA_BLIND_RETRY_FORBIDDEN
    event.amount = 100.0

    # Invariant 12: Inactive mandate status
    event.mandate_status = "suspended"
    assert validate_execution(event, decision, strategy_name="short_delay_retry", strategy_applicable_bucket="B") == SAFETY_MANDATE_INACTIVE
    event.mandate_status = "active"

# =====================================================================
# 2. LLM PROVIDER: DETERMINISM, ISOLATION & BOUNDARIES
# =====================================================================

def test_llm_provider_isolation_and_boundaries():
    # 1. Verify MockProvider is selected and is an instance of MockProvider with zero network
    provider = get_llm_provider()
    assert isinstance(provider, MockProvider)

    # 2. Successful A classification
    res_a = classify_with_llm({"amount": 1500})
    assert res_a.bucket == "A"
    assert 0 <= res_a.confidence <= 1
    assert res_a.provider == "mock"

    # 3. Successful B classification
    res_b = classify_with_llm({"amount": 500})
    assert res_b.bucket == "B"
    assert 0 <= res_b.confidence <= 1

    # 4. Malformed JSON handling
    with pytest.raises(ValueError, match="Malformed JSON"):
        classify_with_llm({"force_malformed_json": True})

    # 5. Markdown-fenced JSON handling
    res_fenced = classify_with_llm({"force_markdown_fenced": True})
    assert res_fenced.bucket == "B"
    assert res_fenced.confidence == 0.88

    # 6. Invalid confidence out of bounds (< 0 or > 1)
    with pytest.raises(ValueError, match="Confidence out of bounds"):
        classify_with_llm({"force_invalid_confidence": True})

    # 7. Unknown bucket (e.g. Z)
    with pytest.raises(ValueError, match="Invalid bucket"):
        classify_with_llm({"force_unknown_bucket": True})

    # 8. Bucket C violation
    with pytest.raises(ValueError, match="Safety Violation: LLM output Bucket C"):
        classify_with_llm({"force_llm_c_prediction": True})

    # 9. Missing fields
    with pytest.raises(ValueError, match="Missing expected field"):
        classify_with_llm({"force_missing_fields": True})

# =====================================================================
# 3. LLM FAILURE LADDER END-TO-END IN /evaluate
# =====================================================================

def test_llm_failure_ladder_end_to_end():
    from app.services.ml_classifier import MLClassificationResult
    db = SessionLocal()
    txn = Transaction(merchant_id="m1", customer_id="c1", amount=500.0, currency="INR", status="failed")
    db.add(txn)
    db.commit()
    db.refresh(txn)
    tx_id = txn.id
    db.close()

    now = datetime.datetime.now(IST_TZ).replace(hour=14, minute=0, second=0)
    base_payload = {
        "amount": 500,
        "payment_type": "card",
        "subscription_category": "other",
        "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
        "scheduled_at": now.isoformat(),
        "current_time": now.isoformat(),
        "attempt_count": 1,
        "mandate_status": "active",
        "authentication_status": "not_authenticated",
        "decline_code": "generic_decline"
    }

    # Low-confidence ML result (0.70 < 0.75 threshold) triggers LLM
    low_conf_ml = MLClassificationResult(
        predicted_bucket="B",
        confidence=0.70,
        probabilities={"A": 0.30, "B": 0.70}
    )

    # Case A: Normal low-confidence ML -> Mock LLM succeeds (Bucket B)
    with mock.patch("app.api.recovery.ml_predict", return_value=low_conf_ml):
        resp_success = client.post("/api/v1/recovery/evaluate", json={"transaction_id": tx_id, "event": base_payload})
    assert resp_success.status_code == 200
    data_success = resp_success.json()
    assert data_success["bucket"] == "B"
    assert data_success["classified_by"] == "llm"
    assert data_success["requires_llm"] is False
    assert data_success["strategy"] is not None
    assert data_success["next_action"] == "execute_strategy"

    # Case B: Mock LLM succeeds (Bucket A for amount=1500)
    payload_a = dict(base_payload)
    payload_a["amount"] = 1500.0
    with mock.patch("app.api.recovery.ml_predict", return_value=low_conf_ml):
        resp_a = client.post("/api/v1/recovery/evaluate", json={"transaction_id": tx_id, "event": payload_a})
    assert resp_a.status_code == 200
    assert resp_a.json()["bucket"] == "A"
    assert resp_a.json()["classified_by"] == "llm"
    assert resp_a.json()["strategy"] == "delay_retry"

    # Case C: LLM failure (timeout / API error) -> FAIL-CLOSED: preserves unresolved state, strategy=None, next_action="llm_unavailable"
    gateway_call_count = 0
    async def spy_gateway(*args, **kwargs):
        nonlocal gateway_call_count
        gateway_call_count += 1
        return "executed"

    with mock.patch("app.api.recovery.ml_predict", return_value=low_conf_ml):
        with mock.patch("app.api.recovery.classify_with_llm", side_effect=RuntimeError("Simulated LLM Timeout")):
            resp_fallback = client.post("/api/v1/recovery/evaluate", json={"transaction_id": tx_id, "event": base_payload})
    assert resp_fallback.status_code == 200
    data_fallback = resp_fallback.json()
    assert data_fallback["bucket"] is None
    assert data_fallback["classified_by"] == "llm_unavailable"
    assert data_fallback["requires_llm"] is True
    assert data_fallback["strategy"] is None
    assert data_fallback["strategy_id"] is None
    assert data_fallback["next_action"] == "llm_unavailable"

    # Verify persisted decision record directly in database
    db = SessionLocal()
    persisted_dec = db.query(RecoveryDecisionRecord).filter(RecoveryDecisionRecord.id == data_fallback["decision_id"]).first()
    assert persisted_dec.bucket in (None, "Unknown")
    assert persisted_dec.bucket not in ("A", "B")
    assert persisted_dec.strategy_id is None
    assert persisted_dec.requires_llm is True
    assert persisted_dec.classified_by == "llm_unavailable"
    assert persisted_dec.next_action == "llm_unavailable"
    assert persisted_dec.status == "pending"

    # Snapshot StrategyPerformance attempt counts before /execute
    perf_before = db.query(StrategyPerformance).all()
    attempts_before = sum(p.attempt_count for p in perf_before)
    db.close()

    # Verify that calling /execute on this unresolved decision is rejected by SafetyValidator (SAFETY_UNRESOLVED_STATE)
    with mock.patch.object(GatewaySimulator, "execute_strategy", spy_gateway):
        resp_exec_blocked = client.post(
            "/api/v1/recovery/execute",
            json={"decision_id": data_fallback["decision_id"], "transaction_id": tx_id, "idempotency_key": "unresolved-key-1"}
        )
    assert resp_exec_blocked.status_code == 403
    assert "SAFETY_UNRESOLVED_STATE" in resp_exec_blocked.json()["detail"]
    assert gateway_call_count == 0  # Gateway was NEVER called

    # Verify StrategyPerformance was NOT updated
    db = SessionLocal()
    perf_after = db.query(StrategyPerformance).all()
    attempts_after = sum(p.attempt_count for p in perf_after)
    assert attempts_after == attempts_before
    db.close()

    # Case D: LLM malformed JSON -> FAIL-CLOSED: preserves unresolved state
    with mock.patch("app.api.recovery.ml_predict", return_value=low_conf_ml):
        with mock.patch("app.api.recovery.classify_with_llm", side_effect=ValueError("Malformed JSON returned by LLM")):
            resp_malformed = client.post("/api/v1/recovery/evaluate", json={"transaction_id": tx_id, "event": base_payload})
    assert resp_malformed.status_code == 200
    assert resp_malformed.json()["bucket"] is None
    assert resp_malformed.json()["requires_llm"] is True
    assert resp_malformed.json()["next_action"] == "llm_unavailable"

    # Case E: LLM invalid confidence / unknown bucket -> FAIL-CLOSED: preserves unresolved state
    with mock.patch("app.api.recovery.ml_predict", return_value=low_conf_ml):
        with mock.patch("app.api.recovery.classify_with_llm", side_effect=ValueError("Confidence out of bounds")):
            resp_invalid = client.post("/api/v1/recovery/evaluate", json={"transaction_id": tx_id, "event": base_payload})
    assert resp_invalid.status_code == 200
    assert resp_invalid.json()["bucket"] is None
    assert resp_invalid.json()["requires_llm"] is True
    assert resp_invalid.json()["next_action"] == "llm_unavailable"

    # Case F: LLM outputs Bucket C -> HTTP 500 Safety Violation
    with mock.patch("app.api.recovery.ml_predict", return_value=low_conf_ml):
        with mock.patch("app.api.recovery.classify_with_llm", side_effect=ValueError("Safety Violation: LLM output Bucket C")):
            resp_c = client.post("/api/v1/recovery/evaluate", json={"transaction_id": tx_id, "event": base_payload})
    assert resp_c.status_code == 500
    assert "Safety Violation: LLM output Bucket C" in resp_c.json()["detail"]

# =====================================================================
# 4. ADAPTIVE ROUTING: MIN_SAMPLE=5 BOUNDARY & PREFERENCE
# =====================================================================

def test_adaptive_routing_logic():
    db = setup_clean_db()

    # Query or create strategies for Bucket B
    strat_default = db.query(RecoveryStrategy).filter(RecoveryStrategy.name == "short_delay_retry", RecoveryStrategy.applicable_bucket == "B").first()
    if not strat_default:
        strat_default = RecoveryStrategy(name="short_delay_retry", applicable_bucket="B", description="Default")
        db.add(strat_default)

    strat_alt = db.query(RecoveryStrategy).filter(RecoveryStrategy.name == "switch_gateway", RecoveryStrategy.applicable_bucket == "B").first()
    if not strat_alt:
        strat_alt = RecoveryStrategy(name="switch_gateway", applicable_bucket="B", description="Alternative")
        db.add(strat_alt)

    strat_bucket_a = db.query(RecoveryStrategy).filter(RecoveryStrategy.name == "delay_retry", RecoveryStrategy.applicable_bucket == "A").first()
    if not strat_bucket_a:
        strat_bucket_a = RecoveryStrategy(name="delay_retry", applicable_bucket="A", description="Bucket A Strat")
        db.add(strat_bucket_a)

    db.commit()

    # 1. Below MIN_SAMPLE=5: strat_alt has 1 attempt, 1 success (100% rate). Default has 0 attempts.
    # Below MIN_SAMPLE=5 threshold, seeded fallback must still win.
    perf_alt = StrategyPerformance(strategy_id=strat_alt.id, bucket="B", attempt_count=1, success_count=1)
    db.add(perf_alt)
    db.commit()

    chosen_below = get_best_strategy(db, "B", "short_delay_retry")
    assert chosen_below == "short_delay_retry"

    # 2. At MIN_SAMPLE=5: strat_alt has 8 successes out of 10 attempts (80%), strat_default has 3 out of 5 (60%).
    perf_alt.attempt_count = 10
    perf_alt.success_count = 8

    perf_default = StrategyPerformance(strategy_id=strat_default.id, bucket="B", attempt_count=5, success_count=3)
    db.add(perf_default)
    db.commit()

    chosen_above = get_best_strategy(db, "B", "short_delay_retry")
    assert chosen_above == "switch_gateway" # 80% > 60%

    # 3. Unauthorized strategy cannot be selected even with 100% success rate
    perf_unauth = StrategyPerformance(strategy_id=strat_bucket_a.id, bucket="A", attempt_count=20, success_count=20)
    db.add(perf_unauth)
    db.commit()

    chosen_auth = get_best_strategy(db, "B", "short_delay_retry")
    assert chosen_auth == "switch_gateway" # Bucket A's 100% cannot be chosen for Bucket B

    # 4. Bucket C and permanently_failed cannot enter adaptive routing
    assert get_best_strategy(db, "C", "delay_retry") == "delay_retry"
    assert get_best_strategy(db, None, "fallback") == "fallback"

    db.close()

# =====================================================================
# 5. GATEWAY SIMULATOR: DETERMINISM & 8 BOUNDARY TIME CHECKS
# =====================================================================

def test_gateway_simulator_deterministic_and_boundaries():
    simulator = GatewaySimulator(seed=100)

    base_date = datetime.date(2026, 8, 26)

    # 8 Boundary Times
    # 1. 09:59 IST -> already valid
    t1 = datetime.datetime.combine(base_date, datetime.time(9, 59), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t1).time() == datetime.time(9, 59)

    # 2. 10:00 IST -> lands in morning block, next is 13:00 today
    t2 = datetime.datetime.combine(base_date, datetime.time(10, 0), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t2).time() == datetime.time(13, 0)

    # 3. 12:59 IST -> lands in morning block, next is 13:00 today
    t3 = datetime.datetime.combine(base_date, datetime.time(12, 59), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t3).time() == datetime.time(13, 0)

    # 4. 13:00 IST -> already valid afternoon window
    t4 = datetime.datetime.combine(base_date, datetime.time(13, 0), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t4).time() == datetime.time(13, 0)

    # 5. 16:59 IST -> already valid afternoon window
    t5 = datetime.datetime.combine(base_date, datetime.time(16, 59), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t5).time() == datetime.time(16, 59)

    # 6. 17:00 IST -> lands in evening block, next is 21:30 today
    t6 = datetime.datetime.combine(base_date, datetime.time(17, 0), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t6).time() == datetime.time(21, 30)

    # 7. 21:29 IST -> lands in evening block, next is 21:30 today
    t7 = datetime.datetime.combine(base_date, datetime.time(21, 29), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t7).time() == datetime.time(21, 30)

    # 8. 21:30 IST -> already valid night window
    t8 = datetime.datetime.combine(base_date, datetime.time(21, 30), tzinfo=IST_TZ)
    assert simulator.calculate_rescheduled_time(t8).time() == datetime.time(21, 30)

# =====================================================================
# 6. CONCURRENCY & IDEMPOTENCY: SPY PROVING EXACTLY ONCE EXECUTION
# =====================================================================

@pytest.mark.asyncio
async def test_execution_idempotency_concurrency():
    db = setup_clean_db()

    # 1. Setup valid transaction, strategy, decision
    txn = Transaction(merchant_id="m_conc", customer_id="c_conc", amount=500.0, currency="INR", status="failed")
    db.add(txn)
    db.commit()
    db.refresh(txn)

    strategy = db.query(RecoveryStrategy).filter(RecoveryStrategy.name == "short_delay_retry", RecoveryStrategy.applicable_bucket == "B").first()
    if not strategy:
        strategy = RecoveryStrategy(name="short_delay_retry", applicable_bucket="B", description="Short delay")
        db.add(strategy)
        db.commit()
        db.refresh(strategy)

    decision = RecoveryDecisionRecord(
        transaction_id=txn.id,
        bucket="B",
        strategy_id=strategy.id,
        classified_by="llm",
        status="pending",
        next_action="execute_strategy",
        requires_llm=False
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    gateway_call_count = 0

    original_execute_strategy = GatewaySimulator.execute_strategy

    async def spy_execute_strategy(self, *args, **kwargs):
        nonlocal gateway_call_count
        gateway_call_count += 1
        return await original_execute_strategy(self, *args, **kwargs)

    transport = httpx.ASGITransport(app=app)
    with mock.patch.object(GatewaySimulator, "execute_strategy", spy_execute_strategy):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client_session:
            req = {
                "decision_id": decision.id,
                "transaction_id": txn.id,
                "idempotency_key": "idemp-concurrency-key-999"
            }
            # Fire 5 concurrent requests with identical idempotency_key
            tasks = [client_session.post("/api/v1/recovery/execute", json=req) for _ in range(5)]
            responses = await asyncio.gather(*tasks)

    status_codes = [r.status_code for r in responses]

    # Exactly one HTTP 200 and four HTTP 409
    assert status_codes.count(200) == 1
    assert status_codes.count(409) == 4

    # GatewaySimulator called exactly once
    assert gateway_call_count == 1

    # Exactly one RecoveryAction owns the idempotency key in DB
    actions = db.query(RecoveryAction).filter(RecoveryAction.idempotency_key == "idemp-concurrency-key-999").all()
    assert len(actions) == 1
    assert actions[0].status == "executed"

    # StrategyPerformance incremented exactly once
    perf = db.query(StrategyPerformance).filter(StrategyPerformance.strategy_id == strategy.id).first()
    assert perf.attempt_count == 1
    assert perf.success_count == 1

    # 2. Replay idempotency: re-calling /execute with the same key returns 200 and does NOT double-increment performance
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client_session:
        replay_resp = await client_session.post("/api/v1/recovery/execute", json=req)
        assert replay_resp.status_code == 200
        assert replay_resp.json()["status"] == "executed"

    db.refresh(perf)
    assert perf.attempt_count == 1
    assert perf.success_count == 1

    db.close()
