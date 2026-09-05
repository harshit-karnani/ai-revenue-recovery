import os
import sys
import json
import datetime

# Ensure app is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.transaction import Transaction
from app.core.regulatory_rules import IST_TZ

client = TestClient(app)

def create_mock_transaction(amount: float) -> str:
    db = SessionLocal()
    try:
        txn = Transaction(
            merchant_id="merch_123",
            customer_id="cust_123",
            amount=amount,
            currency="INR",
            status="failed"
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        return str(txn.id)
    finally:
        db.close()

def run_tests():
    results = {}
    now = datetime.datetime.now(IST_TZ)
    
    # 1. ₹0.01
    txn_id_1 = create_mock_transaction(0.01)
    payload_1 = {
        "transaction_id": txn_id_1,
        "event": {
            "amount": 0.01,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
            "scheduled_at": now.replace(hour=14, minute=0, second=0).isoformat(),
            "current_time": now.replace(hour=14, minute=0, second=0).isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds"
        }
    }
    resp_eval_1 = client.post("/api/v1/recovery/evaluate", json=payload_1)
    dec_1 = resp_eval_1.json()
    resp_exec_1 = client.post("/api/v1/recovery/execute", json={
        "decision_id": dec_1.get("decision_id"),
        "transaction_id": txn_id_1,
        "idempotency_key": f"idem_001_{txn_id_1}"
    })
    results["scenario_1_small_amount"] = {
        "evaluate_request": payload_1,
        "evaluate_response": dec_1,
        "execute_status_code": resp_exec_1.status_code,
        "execute_response": resp_exec_1.json()
    }

    # 2. ₹50,00,000 (Exceeds AFA ₹15,000 limit)
    txn_id_2 = create_mock_transaction(5000000.0)
    payload_2 = {
        "transaction_id": txn_id_2,
        "event": {
            "amount": 5000000.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
            "scheduled_at": now.replace(hour=14, minute=0, second=0).isoformat(),
            "current_time": now.replace(hour=14, minute=0, second=0).isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline"
        }
    }
    resp_eval_2 = client.post("/api/v1/recovery/evaluate", json=payload_2)
    dec_2 = resp_eval_2.json()
    resp_exec_2 = client.post("/api/v1/recovery/execute", json={
        "decision_id": dec_2.get("decision_id"),
        "transaction_id": txn_id_2,
        "idempotency_key": f"idem_afa_{txn_id_2}"
    })
    results["scenario_2_afa_exceeded"] = {
        "evaluate_request": payload_2,
        "evaluate_response": dec_2,
        "execute_status_code": resp_exec_2.status_code,
        "execute_response": resp_exec_2.json()
    }

    # 3. Unseen decline code "zzz_not_real_999"
    txn_id_3 = create_mock_transaction(500.0)
    payload_3 = {
        "transaction_id": txn_id_3,
        "event": {
            "amount": 500.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
            "scheduled_at": now.replace(hour=14, minute=0, second=0).isoformat(),
            "current_time": now.replace(hour=14, minute=0, second=0).isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "zzz_not_real_999"
        }
    }
    resp_eval_3 = client.post("/api/v1/recovery/evaluate", json=payload_3)
    dec_3 = resp_eval_3.json()
    resp_exec_3 = client.post("/api/v1/recovery/execute", json={
        "decision_id": dec_3.get("decision_id"),
        "transaction_id": txn_id_3,
        "idempotency_key": f"idem_unseen_{txn_id_3}"
    })
    results["scenario_3_unseen_decline_code"] = {
        "evaluate_request": payload_3,
        "evaluate_response": dec_3,
        "execute_status_code": resp_exec_3.status_code,
        "execute_response": resp_exec_3.json()
    }

    # 4. attempt_count = 3 (allowed retry)
    txn_id_4 = create_mock_transaction(1200.0)
    payload_4 = {
        "transaction_id": txn_id_4,
        "event": {
            "amount": 1200.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
            "scheduled_at": now.replace(hour=14, minute=0, second=0).isoformat(),
            "current_time": now.replace(hour=14, minute=0, second=0).isoformat(),
            "attempt_count": 3,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds"
        }
    }
    resp_eval_4 = client.post("/api/v1/recovery/evaluate", json=payload_4)
    dec_4 = resp_eval_4.json()
    resp_exec_4 = client.post("/api/v1/recovery/execute", json={
        "decision_id": dec_4.get("decision_id"),
        "transaction_id": txn_id_4,
        "idempotency_key": f"idem_att3_{txn_id_4}"
    })
    results["scenario_4_attempt_count_3"] = {
        "evaluate_request": payload_4,
        "evaluate_response": dec_4,
        "execute_status_code": resp_exec_4.status_code,
        "execute_response": resp_exec_4.json()
    }

    # 5. attempt_count = 4 (terminal retry cap reached)
    txn_id_5 = create_mock_transaction(1200.0)
    payload_5 = {
        "transaction_id": txn_id_5,
        "event": {
            "amount": 1200.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
            "scheduled_at": now.replace(hour=14, minute=0, second=0).isoformat(),
            "current_time": now.replace(hour=14, minute=0, second=0).isoformat(),
            "attempt_count": 4,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds"
        }
    }
    resp_eval_5 = client.post("/api/v1/recovery/evaluate", json=payload_5)
    dec_5 = resp_eval_5.json()
    resp_exec_5 = client.post("/api/v1/recovery/execute", json={
        "decision_id": dec_5.get("decision_id"),
        "transaction_id": txn_id_5,
        "idempotency_key": f"idem_att4_{txn_id_5}"
    })
    results["scenario_5_attempt_count_4_terminal"] = {
        "evaluate_request": payload_5,
        "evaluate_response": dec_5,
        "execute_status_code": resp_exec_5.status_code,
        "execute_response": resp_exec_5.json()
    }

    # 6. Execution window boundaries
    window_tests = [
        ("09:59:59", 9, 59, 59, "Allowed pre-morning"),
        ("10:00:00", 10, 0, 0, "Blocked morning start"),
        ("12:59:59", 12, 59, 59, "Blocked morning end"),
        ("13:00:00", 13, 0, 0, "Allowed afternoon start"),
        ("17:00:00", 17, 0, 0, "Blocked evening start"),
        ("21:30:00", 21, 30, 0, "Allowed night start")
    ]
    window_results = []
    for label, h, m, s, desc in window_tests:
        t = now.replace(hour=h, minute=m, second=s, microsecond=0)
        txn_w = create_mock_transaction(1000.0)
        payload_w = {
            "transaction_id": txn_w,
            "event": {
                "amount": 1000.0,
                "currency": "INR",
                "payment_type": "upi_autopay",
                "subscription_category": "ecommerce_subscription",
                "notification_sent_at": (t - datetime.timedelta(hours=25)).isoformat(),
                "scheduled_at": t.isoformat(),
                "current_time": t.isoformat(),
                "attempt_count": 1,
                "mandate_status": "active",
                "authentication_status": "not_authenticated",
                "decline_code": "generic_decline"
            }
        }
        resp_eval_w = client.post("/api/v1/recovery/evaluate", json=payload_w)
        window_results.append({
            "time_ist": label,
            "description": desc,
            "status_code": resp_eval_w.status_code,
            "response": resp_eval_w.json()
        })
    results["scenario_6_window_boundaries"] = window_results

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_tests()
