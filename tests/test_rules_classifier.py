import pytest
import datetime
from app.schemas.payment import PaymentEvent, RegulatoryEvaluationResult
from app.services.rules_classifier import classify_failure
from app.models.failure_reason import FailureReason
from app.core.regulatory_rules import IST_TZ

# Mock DB Session
class MockSession:
    def __init__(self, failure_reasons):
        self.reasons = {fr.decline_code: fr for fr in failure_reasons}

    def query(self, *args, **kwargs):
        return self

    def filter(self, condition):
        # We assume the condition is FailureReason.decline_code == code
        # We extract the code value from the condition by parsing the string representation (hacky for mock, but works for simple tests)
        self.current_code = condition.right.value
        return self

    def first(self):
        return self.reasons.get(self.current_code)

@pytest.fixture
def mock_db():
    reasons = [
        FailureReason(decline_code="insufficient_funds", bucket="A", description="No funds", is_ambiguous=False),
        FailureReason(decline_code="generic_decline", bucket="B", description="Generic", is_ambiguous=True),
    ]
    return MockSession(reasons)

def test_classifier_terminal_failure(mock_db):
    event = PaymentEvent(
        amount=1000, payment_type="card", subscription_category="other",
        scheduled_at=datetime.datetime.now(IST_TZ), current_time=datetime.datetime.now(IST_TZ),
        attempt_count=4, mandate_status="active", authentication_status="not_authenticated",
        decline_code=None
    )
    reg_result = RegulatoryEvaluationResult(
        allowed=False, failure_code="permanently_failed", reason="Retry cap exceeded",
        authentication_required=False, retry_allowed=False
    )
    
    result = classify_failure(event, reg_result, mock_db)
    
    assert result["failure_code"] == "permanently_failed"
    assert result["bucket"] is None
    assert result["requires_ml"] is False
    assert result["regulatory_block"] is False

def test_classifier_regulatory_failure(mock_db):
    event = PaymentEvent(
        amount=1000, payment_type="card", subscription_category="other",
        scheduled_at=datetime.datetime.now(IST_TZ), current_time=datetime.datetime.now(IST_TZ),
        attempt_count=1, mandate_status="active", authentication_status="not_authenticated",
        decline_code=None
    )
    reg_result = RegulatoryEvaluationResult(
        allowed=False, failure_code="missed_predebit_notification", reason="Pre-debit failed",
        authentication_required=False, retry_allowed=True
    )
    
    result = classify_failure(event, reg_result, mock_db)
    
    assert result["failure_code"] == "missed_predebit_notification"
    assert result["bucket"] == "C"
    assert result["requires_ml"] is False
    assert result["regulatory_block"] is True

def test_classifier_bucket_a(mock_db):
    event = PaymentEvent(
        amount=1000, payment_type="card", subscription_category="other",
        scheduled_at=datetime.datetime.now(IST_TZ), current_time=datetime.datetime.now(IST_TZ),
        attempt_count=1, mandate_status="active", authentication_status="not_authenticated",
        decline_code="insufficient_funds"
    )
    reg_result = RegulatoryEvaluationResult(allowed=True)
    
    result = classify_failure(event, reg_result, mock_db)
    
    assert result["bucket"] == "A"
    assert result["requires_ml"] is False
    assert result["confidence"] == 1.0
    assert result["regulatory_block"] is False

def test_classifier_bucket_b(mock_db):
    event = PaymentEvent(
        amount=1000, payment_type="card", subscription_category="other",
        scheduled_at=datetime.datetime.now(IST_TZ), current_time=datetime.datetime.now(IST_TZ),
        attempt_count=1, mandate_status="active", authentication_status="not_authenticated",
        decline_code="generic_decline"
    )
    reg_result = RegulatoryEvaluationResult(allowed=True)
    
    result = classify_failure(event, reg_result, mock_db)
    
    assert result["bucket"] == "B"
    assert result["requires_ml"] is True
    assert result["confidence"] is None
    assert result["regulatory_block"] is False

def test_classifier_unknown(mock_db):
    event = PaymentEvent(
        amount=1000, payment_type="card", subscription_category="other",
        scheduled_at=datetime.datetime.now(IST_TZ), current_time=datetime.datetime.now(IST_TZ),
        attempt_count=1, mandate_status="active", authentication_status="not_authenticated",
        decline_code="some_weird_error"
    )
    reg_result = RegulatoryEvaluationResult(allowed=True)
    
    result = classify_failure(event, reg_result, mock_db)
    
    assert result["bucket"] is None
    assert result["requires_ml"] is True
    assert result["confidence"] is None
    assert result["regulatory_block"] is False

def test_classifier_missing_decline_code(mock_db):
    event = PaymentEvent(
        amount=1000, payment_type="card", subscription_category="other",
        scheduled_at=datetime.datetime.now(IST_TZ), current_time=datetime.datetime.now(IST_TZ),
        attempt_count=1, mandate_status="active", authentication_status="not_authenticated",
        decline_code=None
    )
    reg_result = RegulatoryEvaluationResult(allowed=True)
    
    with pytest.raises(ValueError, match="Missing decline code"):
        classify_failure(event, reg_result, mock_db)
