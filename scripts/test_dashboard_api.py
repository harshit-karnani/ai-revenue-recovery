import urllib.request
import json

def test_api():
    print("Testing GET /api/v1/dashboard/batch-summary ...")
    req = urllib.request.Request("http://127.0.0.1:8000/api/v1/dashboard/batch-summary")
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(f"  Status: {res.status}")
        print(f"  Transactions: {data['total_transactions']}")
        print(f"  Amount at risk: INR {data['total_amount_at_risk']:,.2f}")
        print(f"  Amount recovered: INR {data['total_amount_recovered']:,.2f}")

    print("\nTesting POST /api/v1/dashboard/run-batch ...")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/dashboard/run-batch",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(f"  Status: {res.status}")
        print(f"  Transactions: {data['total_transactions']}")
        print(f"  Amount at risk: INR {data['total_amount_at_risk']:,.2f}")
        print(f"  Amount recovered: INR {data['total_amount_recovered']:,.2f}")
        print(f"  Recovery Rate: {data['recovery_rate_by_amount'] * 100:.2f}%")

    print("\nTesting POST /api/v1/recovery/evaluate (Manual test flow preserved) ...")
    payload = {
        "transaction_id": "txn_manual_test_01",
        "event": {
            "amount": 1200.0,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "decline_code": "insufficient_funds",
            "attempt_count": 1,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "notification_sent_at": "2026-08-30T13:00:00+05:30",
            "scheduled_at": "2026-08-31T14:00:00+05:30",
            "current_time": "2026-08-31T14:00:00+05:30"
        }
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/recovery/evaluate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(f"  Manual Evaluate Status: {res.status}")
        print(f"  Bucket: {data.get('bucket')}")
        print(f"  Strategy: {data.get('strategy')}")
        print(f"  Next Action: {data.get('next_action')}")

    print("\nALL HTTP API TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_api()
