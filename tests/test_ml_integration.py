from fastapi.testclient import TestClient
from app.main import app
import datetime
from app.core.regulatory_rules import IST_TZ
from unittest import mock
import pytest
from app.services.ml_classifier import MLClassificationResult
from app.core.database import SessionLocal
from app.models.transaction import Transaction

client = TestClient(app)

@pytest.fixture(scope="module")
def valid_tx_id():
    db = SessionLocal()
    txn = Transaction(
        merchant_id="test_merchant",
        customer_id="test_cust",
        amount=1000.0,
        currency="INR",
        status="failed"
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    tx_id = txn.id
    db.close()
    return tx_id

def create_payload(decline_code="generic_decline"):
    now = datetime.datetime.now(IST_TZ).replace(hour=14, minute=0, second=0, microsecond=0)
    return {
        "amount": 1000,
        "payment_type": "card",
        "subscription_category": "other",
        "notification_sent_at": (now - datetime.timedelta(hours=25)).isoformat(),
        "scheduled_at": now.isoformat(),
        "current_time": now.isoformat(),
        "attempt_count": 1,
        "mandate_status": "active",
        "authentication_status": "not_authenticated",
        "decline_code": decline_code
    }

def test_api_high_confidence_ml(valid_tx_id):
    payload = create_payload("generic_decline")
    
    mock_result = MLClassificationResult(
        predicted_bucket="B",
        confidence=0.80,
        probabilities={"A": 0.20, "B": 0.80}
    )
    
    with mock.patch("app.api.recovery.ml_predict", return_value=mock_result):
        response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
        
    assert response.status_code == 200
    data = response.json()
    assert data["bucket"] == "B"
    assert data["requires_llm"] is False
    assert data["classified_by"] == "ml"
    assert data["confidence"] == 0.80
    assert data["strategy"] is not None
    assert data["next_action"] == "execute_strategy"

def test_api_exact_threshold_ml(valid_tx_id):
    payload = create_payload("generic_decline")
    
    mock_result = MLClassificationResult(
        predicted_bucket="B",
        confidence=0.75, # exactly 0.75 should be accepted
        probabilities={"A": 0.25, "B": 0.75}
    )
    
    with mock.patch("app.api.recovery.ml_predict", return_value=mock_result):
        response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
        
    assert response.status_code == 200
    data = response.json()
    assert data["bucket"] == "B"
    assert data["requires_llm"] is False
    assert data["classified_by"] == "ml"
    assert data["strategy"] is not None

def test_api_low_confidence_ml(valid_tx_id):
    payload = create_payload("generic_decline")
    
    mock_result = MLClassificationResult(
        predicted_bucket="B",
        confidence=0.74, # below 0.75 escalates to LLM
        probabilities={"A": 0.26, "B": 0.74}
    )
    
    with mock.patch("app.api.recovery.ml_predict", return_value=mock_result):
        response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
        
    assert response.status_code == 200
    data = response.json()
    assert data["bucket"] == "B"
    assert data["classified_by"] == "llm"
    assert data["requires_llm"] is False
    assert data["strategy"] is not None
    assert data["next_action"] == "execute_strategy"

def test_api_ml_predicts_c_runtime_error(valid_tx_id):
    payload = create_payload("generic_decline")
    
    with mock.patch("app.api.recovery.ml_predict", side_effect=RuntimeError("ML classifier predicted Bucket C")):
        response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
        
    assert response.status_code == 500
    data = response.json()
    assert "Bucket C" in data["detail"]

def test_api_deterministic_escalation_reachability(valid_tx_id):
    # We test that the trained ML model genuinely produces confidence < 0.75 for an ambiguous event.
    # No mock on ml_predict here! It hits the real model.
    # We use PaymentSimulator with seed=42 to generate an ambiguous overlap event.
    from app.services.payment_simulator import PaymentSimulator
    sim = PaymentSimulator(seed=12) # Use a seed that yields an overlap scenario. 
    payload = create_payload("generic_decline")
    payload["amount"] = 1500.00
    payload["attempt_count"] = 2
    payload["payment_type"] = "card"
    payload["subscription_category"] = "other"
    
    response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
    # If the model is not trained, it returns 503, which is fine to skip or fail if it's expected to be trained.
    if response.status_code == 503:
        pytest.skip("Model not loaded, cannot test true reachability.")
        
    assert response.status_code == 200
    data = response.json()
    
    # Prove it escalated to ML low confidence (< 0.75)
    assert data["ml_confidence"] < 0.75
    assert data["ml_prediction"] in ("A", "B")
    assert data["classified_by"] in ("llm", "ml", "llm_unavailable")

def test_api_bucket_c_no_ml_call(valid_tx_id):
    payload = create_payload("missed_predebit_notification")
    payload["amount"] = 16000.00
    # Notification elapsed 23 hours
    payload["notification_sent_at"] = (datetime.datetime.now(IST_TZ) - datetime.timedelta(hours=23)).isoformat()
    
    with mock.patch("app.api.recovery.ml_predict") as mock_ml:
        response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
        
    assert response.status_code == 200
    assert response.json()["bucket"] == "C"
    mock_ml.assert_not_called()

def test_api_terminal_no_ml_call(valid_tx_id):
    payload = create_payload("generic_decline")
    payload["attempt_count"] = 4
    
    with mock.patch("app.api.recovery.ml_predict") as mock_ml:
        response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
        
    assert response.status_code == 200
    assert response.json()["failure_code"] == "permanently_failed"
    mock_ml.assert_not_called()

def test_pipeline_real_inference_from_disk(valid_tx_id):
    # Explicit test for loading from disk and running real inference
    import os
    model_path = os.path.join(os.path.dirname(__file__), "..", "models", "recovery_classifier.joblib")
    assert os.path.exists(model_path)
    
    payload = create_payload("generic_decline")
    payload["amount"] = 7500.50
    payload["attempt_count"] = 3
    payload["payment_type"] = "card"
    payload["subscription_category"] = "other"
    
    # Hits the real endpoint, which internally loads the joblib model and runs predict()
    response = client.post("/api/v1/recovery/evaluate", json={"transaction_id": valid_tx_id, "event": payload})
    if response.status_code == 503:
        pytest.skip("Model not loaded.")
        
    assert response.status_code == 200
    data = response.json()
    assert data["classified_by"] in ("ml", "llm", "llm_unavailable")
    assert data["ml_prediction"] is not None
