import os
import pytest
from unittest import mock
import joblib
from app.services.ml_classifier import _load_model, predict, ModelNotLoadedError
from app.schemas.payment import PaymentEvent
import datetime
from app.core.regulatory_rules import IST_TZ

@pytest.fixture
def mock_event():
    now = datetime.datetime.now(IST_TZ)
    return PaymentEvent(
        amount=1000,
        payment_type="card",
        subscription_category="other",
        notification_sent_at=(now - datetime.timedelta(hours=25)).isoformat(),
        scheduled_at=now.isoformat(),
        current_time=now.isoformat(),
        attempt_count=1,
        mandate_status="active",
        authentication_status="not_authenticated",
        decline_code="generic_decline"
    )

def test_missing_model_produces_error(mock_event):
    # Temporarily hide the model if it exists
    with mock.patch('os.path.exists', return_value=False):
        with pytest.raises(ModelNotLoadedError) as exc:
            _load_model()
        assert "ML model is unavailable" in str(exc.value)

def test_forced_c_prediction_raises_runtime_error(mock_event):
    # Mock a model that returns 'C'
    class MockCModel:
        classes_ = ["A", "B", "C"]
        def predict_proba(self, X):
            return [[0.1, 0.1, 0.8]]
        def predict(self, X):
            return ["C"]

    with mock.patch('app.services.ml_classifier._load_model', return_value=MockCModel()):
        with pytest.raises(RuntimeError) as exc:
            predict(mock_event)
        assert "Bucket C" in str(exc.value)

def test_valid_probabilities(mock_event):
    # Mock a valid model returning A
    class MockValidModel:
        classes_ = ["A", "B"]
        def predict_proba(self, X):
            return [[0.85, 0.15]]
        def predict(self, X):
            return ["A"]

    with mock.patch('app.services.ml_classifier._load_model', return_value=MockValidModel()):
        result = predict(mock_event)
        assert result.predicted_bucket == "A"
        assert result.confidence == 0.85
        assert result.probabilities["A"] == 0.85
        assert result.probabilities["B"] == 0.15

from app.services.ml_classifier import _load_model, predict, ModelNotLoadedError, is_confident

def test_is_confident_logic():
    assert is_confident(0.90) is True
    assert is_confident(0.7501) is True
    assert is_confident(0.75) is True
    assert is_confident(0.749999) is False
    assert is_confident(0.74) is False
    assert is_confident(0.25) is False

