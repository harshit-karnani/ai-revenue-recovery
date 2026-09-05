import os
import sys

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import SessionLocal
from app.models.failure_reason import FailureReason
from app.models.recovery_strategy import RecoveryStrategy

FAILURE_REASONS = [
    # Bucket A
    {"decline_code": "insufficient_funds", "bucket": "A", "description": "Not enough funds in customer account", "is_ambiguous": False},
    {"decline_code": "expired_card", "bucket": "A", "description": "Card has expired", "is_ambiguous": False},
    {"decline_code": "invalid_card", "bucket": "A", "description": "Card details are invalid", "is_ambiguous": False},
    {"decline_code": "card_blocked", "bucket": "A", "description": "Card blocked by issuer", "is_ambiguous": False},
    
    # Bucket B
    {"decline_code": "generic_decline", "bucket": "B", "description": "Generic bank decline", "is_ambiguous": True},
    {"decline_code": "do_not_honor", "bucket": "B", "description": "Bank declined to honor transaction", "is_is_ambiguous": True},
    {"decline_code": "processing_error", "bucket": "B", "description": "Temporary processing error", "is_ambiguous": True},
    {"decline_code": "timeout", "bucket": "B", "description": "Network timeout", "is_ambiguous": True},
    
    # Bucket C
    {"decline_code": "missed_predebit_notification", "bucket": "C", "description": "Pre-debit notification requirement not met", "is_ambiguous": False},
    {"decline_code": "afa_reauth_required", "bucket": "C", "description": "Transaction requires Additional Factor Authentication", "is_ambiguous": False},
    {"decline_code": "execution_window_block", "bucket": "C", "description": "Attempted during NPCI execution blocked window", "is_ambiguous": False},
    {"decline_code": "mandate_expired", "bucket": "C", "description": "Recurring mandate has expired", "is_ambiguous": False},
]

STRATEGIES = [
    {"name": "delay_retry", "applicable_bucket": "A", "description": "Retry after a delay (e.g., payday)"},
    {"name": "delay_retry", "applicable_bucket": "C", "description": "Retry after a delay (e.g., pre-debit wait)"},
    {"name": "notify_customer", "applicable_bucket": "A", "description": "Ask customer to update payment info"},
    {"name": "short_delay_retry", "applicable_bucket": "B", "description": "Retry quickly to bypass transient error"},
    {"name": "switch_gateway", "applicable_bucket": "B", "description": "Retry using an alternative payment gateway"},
    {"name": "reschedule_valid_window", "applicable_bucket": "C", "description": "Reschedule to a valid NPCI execution window"},
    {"name": "trigger_reauthentication_link", "applicable_bucket": "C", "description": "Send customer a link for AFA"},
    {"name": "refresh_mandate", "applicable_bucket": "C", "description": "Ask customer to re-establish mandate"},
]

def run_seed():
    db = SessionLocal()
    try:
        inserted_reasons = 0
        existing_reasons = 0
        inserted_strategies = 0
        existing_strategies = 0

        for r in FAILURE_REASONS:
            # Handle slight typo in my hardcoded array above
            is_ambig = r.get("is_ambiguous") if "is_ambiguous" in r else r.get("is_is_ambiguous", False)
            existing = db.query(FailureReason).filter(FailureReason.decline_code == r["decline_code"]).first()
            if not existing:
                fr = FailureReason(
                    decline_code=r["decline_code"],
                    bucket=r["bucket"],
                    description=r["description"],
                    is_ambiguous=is_ambig,
                    source_type="simulated"
                )
                db.add(fr)
                inserted_reasons += 1
            else:
                existing_reasons += 1
                
        for s in STRATEGIES:
            existing = db.query(RecoveryStrategy).filter(
                RecoveryStrategy.name == s["name"],
                RecoveryStrategy.applicable_bucket == s["applicable_bucket"]
            ).first()
            if not existing:
                rs = RecoveryStrategy(
                    name=s["name"],
                    applicable_bucket=s["applicable_bucket"],
                    description=s["description"]
                )
                db.add(rs)
                inserted_strategies += 1
            else:
                existing_strategies += 1

        db.commit()
        
        print(f"Seed completed.")
        print(f"Failure Reasons: {inserted_reasons} inserted, {existing_reasons} existed.")
        print(f"Strategies: {inserted_strategies} inserted, {existing_strategies} existed.")

    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_seed()
