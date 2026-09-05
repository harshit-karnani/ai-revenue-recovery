from typing import Optional, Dict, Any
from app.schemas.payment import PaymentEvent, RegulatoryEvaluationResult
from app.models.failure_reason import FailureReason
from sqlalchemy.orm import Session

def classify_failure(
    event: PaymentEvent,
    regulatory_result: RegulatoryEvaluationResult,
    db: Session
) -> Dict[str, Any]:
    """
    Deterministically classifies a failed payment based on regulatory results and gateway decline codes.
    """
    # 1. Check terminal retry-cap result
    # The regulatory engine evaluates this first. If it's permanently_failed, it's terminal.
    if not regulatory_result.allowed and regulatory_result.failure_code == "permanently_failed":
        return {
            "failure_code": "permanently_failed",
            "bucket": None,
            "requires_ml": False,
            "confidence": 1.0,
            "regulatory_block": False,
            "reason": "Retry cap exceeded."
        }

    # 2. Check regulatory failure (Bucket C)
    if not regulatory_result.allowed:
        # A genuine regulatory failure fired (e.g. missed_predebit_notification, afa_reauth_required, etc.)
        return {
            "failure_code": regulatory_result.failure_code,
            "bucket": "C",
            "requires_ml": False,
            "confidence": 1.0,
            "regulatory_block": True,
            "reason": regulatory_result.reason or "Regulatory block."
        }

    # 3. If regulatory evaluation allows the payment, we MUST have a decline code.
    if not event.decline_code:
        raise ValueError("Missing decline code. The regulatory engine allowed the payment, but no gateway decline code was provided.")

    decline_code = event.decline_code
    
    # Lookup the decline code taxonomy from DB
    failure_reason = db.query(FailureReason).filter(FailureReason.decline_code == decline_code).first()

    # 5. Unknown cases
    if not failure_reason:
        return {
            "failure_code": decline_code,
            "bucket": None,
            "requires_ml": True,
            "confidence": None,
            "regulatory_block": False,
            "reason": "unknown_decline_code"
        }

    # 3 & 4. Deterministic vs Ambiguous taxonomy
    if failure_reason.bucket == "A":
        return {
            "failure_code": decline_code,
            "bucket": "A",
            "requires_ml": False,
            "confidence": 1.0,
            "regulatory_block": False,
            "reason": failure_reason.description
        }
    elif failure_reason.bucket == "B":
        return {
            "failure_code": decline_code,
            "bucket": "B",
            "requires_ml": True,
            "confidence": None,
            "regulatory_block": False,
            "reason": failure_reason.description
        }
    else:
        # If the DB has a Bucket C code but it wasn't caught by the regulatory engine, 
        # it is technically an anomaly, but we'll flag it for ML review or handle as unknown.
        return {
            "failure_code": decline_code,
            "bucket": None,
            "requires_ml": True,
            "confidence": None,
            "regulatory_block": False,
            "reason": "Unexpected Bucket C code from gateway."
        }
