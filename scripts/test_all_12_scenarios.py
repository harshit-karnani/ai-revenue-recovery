import os
import sys
import json
import datetime

# Ensure app is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.core.regulatory_rules import IST_TZ

client = TestClient(app)

def run_all_tests():
    now = datetime.datetime.now(IST_TZ)
    exec_14 = now.replace(hour=14, minute=0, second=0, microsecond=0)
    notif_valid = exec_14 - datetime.timedelta(hours=25)
    notif_invalid = exec_14 - datetime.timedelta(hours=6) # < 24h
    
    exec_morning = now.replace(hour=11, minute=15, second=0, microsecond=0)
    notif_morning = exec_morning - datetime.timedelta(hours=25)
    
    exec_evening = now.replace(hour=18, minute=30, second=0, microsecond=0)
    notif_evening = exec_evening - datetime.timedelta(hours=25)

    print("=" * 70)
    print("FARRE 12-SCENARIO END-TO-END VERIFICATION SUITE")
    print("=" * 70)

    scenarios = [
        {
            "id": "1. Bucket A: Insufficient Funds",
            "amount": 1200.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds",
            "expected_bucket": "A",
            "expected_classified_by": "rules",
            "expected_strategy": "delay_retry",
            "expect_exec_status": "executed"
        },
        {
            "id": "2. Bucket A: Expired Card",
            "amount": 850.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "expired_card",
            "expected_bucket": "A",
            "expected_classified_by": "rules",
            "expected_strategy": "notify_customer",
            "expect_exec_status": "executed"
        },
        {
            "id": "3. Bucket B: Generic Decline (High-Conf ML >= 0.75)",
            "amount": 1200.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "other",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline",
            "expected_bucket": "B",
            "expected_classified_by": "ml",
            "expected_ml_conf_ge": 0.75,
            "expect_exec_status": "executed"
        },
        {
            "id": "4. Bucket B: Contextual Ambiguity (ML < 0.75 -> LLM)",
            "amount": 1500.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "other",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 2,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline",
            "expected_classified_by": "llm",
            "expected_ml_conf_lt": 0.75,
            "expect_exec_status": "executed"
        },
        {
            "id": "5. Bucket C: Missed Pre-Debit (<24h)",
            "amount": 999.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_invalid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds",
            "expected_bucket": "C",
            "expected_classified_by": "rules",
            "expected_regulatory_block": True,
            "expect_exec_fail_code": 403
        },
        {
            "id": "6. Bucket C: AFA Limit Exceeded (>Rs 15,000)",
            "amount": 18500.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds",
            "expected_bucket": "C",
            "expected_classified_by": "rules",
            "expected_regulatory_block": True,
            "expect_exec_fail_code": 403
        },
        {
            "id": "7. Bucket C: NPCI Morning Window (10:00-13:00 IST)",
            "amount": 499.0,
            "currency": "INR",
            "payment_type": "upi_autopay",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_morning.isoformat(),
            "scheduled_at": exec_morning.isoformat(),
            "current_time": exec_morning.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline",
            "expected_bucket": "C",
            "expected_classified_by": "rules",
            "expected_regulatory_block": True,
            "expect_exec_fail_code": 403
        },
        {
            "id": "8. Bucket C: NPCI Evening Window (17:00-21:30 IST)",
            "amount": 499.0,
            "currency": "INR",
            "payment_type": "upi_autopay",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_evening.isoformat(),
            "scheduled_at": exec_evening.isoformat(),
            "current_time": exec_evening.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline",
            "expected_bucket": "C",
            "expected_classified_by": "rules",
            "expected_regulatory_block": True,
            "expect_exec_fail_code": 403
        },
        {
            "id": "9. Invariant: Retry Cap (Attempt = 4)",
            "amount": 1500.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 4,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "insufficient_funds",
            "expected_bucket": None,
            "expected_classified_by": "rules",
            "expected_failure_code": "permanently_failed",
            "expected_next_action": "terminate_pipeline",
            "expect_exec_fail_code": 403
        },
        {
            "id": "10. Invariant: Unseen Decline Code",
            "amount": 600.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "zzz_not_real_999",
            "expected_classified_by": "ml",
            "expect_exec_status": "executed"
        },
        {
            "id": "11. Invariant: LLM Failure (Unresolved Fail-Closed)",
            "amount": 1500.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "other",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 2,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline",
            "force_llm_failure": True,
            "expected_classified_by": "llm_unavailable",
            "expect_exec_fail_code": 403
        },
        {
            "id": "12. Invariant: LLM Attempts Bucket C (Safety Trap)",
            "amount": 1500.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "other",
            "notification_sent_at": notif_valid.isoformat(),
            "scheduled_at": exec_14.isoformat(),
            "current_time": exec_14.isoformat(),
            "attempt_count": 2,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": "generic_decline",
            "force_llm_c_prediction": True,
            "expect_eval_status_code": 500
        }
    ]

    passed_count = 0
    for idx, sc in enumerate(scenarios, 1):
        name = sc["id"]
        # Create demo transaction
        txn_res = client.post("/api/v1/recovery/demo/create-transaction", json={"amount": sc["amount"], "currency": sc["currency"]})
        assert txn_res.status_code == 200
        txn_id = txn_res.json()["transaction_id"]

        event_payload = {
            "amount": sc["amount"],
            "currency": sc["currency"],
            "payment_type": sc["payment_type"],
            "subscription_category": sc["subscription_category"],
            "notification_sent_at": sc["notification_sent_at"],
            "scheduled_at": sc["scheduled_at"],
            "current_time": sc["current_time"],
            "attempt_count": sc["attempt_count"],
            "mandate_status": sc["mandate_status"],
            "authentication_status": sc["authentication_status"],
            "decline_code": sc["decline_code"]
        }
        if sc.get("force_llm_failure"):
            event_payload["force_llm_failure"] = True
        if sc.get("force_llm_c_prediction"):
            event_payload["force_llm_c_prediction"] = True

        eval_req = {
            "transaction_id": txn_id,
            "event": event_payload
        }

        eval_res = client.post("/api/v1/recovery/evaluate", json=eval_req)
        
        # Check expected 500 safety trap
        if sc.get("expect_eval_status_code") == 500:
            assert eval_res.status_code == 500
            assert "Safety Violation: LLM output Bucket C" in eval_res.json()["detail"]
            print(f"[{idx}/12] PASS: {name} -> Caught Safety Trap (HTTP 500)")
            passed_count += 1
            continue

        assert eval_res.status_code == 200, f"Evaluate failed for {name}: {eval_res.text}"
        eval_data = eval_res.json()

        if "expected_bucket" in sc:
            assert eval_data["bucket"] == sc["expected_bucket"], f"Expected bucket {sc['expected_bucket']}, got {eval_data['bucket']}"
        if "expected_classified_by" in sc:
            assert eval_data["classified_by"] == sc["expected_classified_by"], f"Expected classified_by {sc['expected_classified_by']}, got {eval_data['classified_by']}"
        if "expected_strategy" in sc:
            assert eval_data["strategy"] == sc["expected_strategy"], f"Expected strategy {sc['expected_strategy']}, got {eval_data['strategy']}"
        if "expected_regulatory_block" in sc:
            assert eval_data["regulatory_block"] == sc["expected_regulatory_block"], f"Expected reg_block {sc['expected_regulatory_block']}, got {eval_data['regulatory_block']}"
        if "expected_ml_conf_ge" in sc:
            assert eval_data["ml_confidence"] >= sc["expected_ml_conf_ge"], f"Expected ml_conf >= {sc['expected_ml_conf_ge']}, got {eval_data['ml_confidence']}"
        if "expected_ml_conf_lt" in sc:
            assert eval_data["ml_confidence"] < sc["expected_ml_conf_lt"], f"Expected ml_conf < {sc['expected_ml_conf_lt']}, got {eval_data['ml_confidence']}"

        dec_id = eval_data["decision_id"]

        # Execute
        exec_req = {
            "decision_id": dec_id,
            "transaction_id": txn_id,
            "idempotency_key": f"idem_test_{idx}_{txn_id}"
        }
        exec_res = client.post("/api/v1/recovery/execute", json=exec_req)

        if "expect_exec_status" in sc:
            assert exec_res.status_code == 200, f"Exec failed: {exec_res.text}"
            assert exec_res.json()["status"] == sc["expect_exec_status"]
            print(f"[{idx}/12] PASS: {name} -> Evaluated (Bucket {eval_data['bucket']}, By {eval_data['classified_by']}) & Executed ({exec_res.json()['status']})")
        elif "expect_exec_fail_code" in sc:
            assert exec_res.status_code == sc["expect_exec_fail_code"], f"Expected exec code {sc['expect_exec_fail_code']}, got {exec_res.status_code}: {exec_res.text}"
            print(f"[{idx}/12] PASS: {name} -> Evaluated (Bucket {eval_data['bucket']}, By {eval_data['classified_by']}) & Blocked at Safety Firewall (HTTP {exec_res.status_code}: {exec_res.json()['detail']})")
        
        passed_count += 1

    print("=" * 70)
    print(f"ALL {passed_count}/{len(scenarios)} SCENARIOS PASSED WITH 100% ACCURACY!")
    print("=" * 70)

if __name__ == "__main__":
    run_all_tests()
